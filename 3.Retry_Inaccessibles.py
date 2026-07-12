#!/usr/bin/env python
# coding: utf-8
"""
3.Retry_Inaccessibles.py
------------------------
Retries every address in data/Adresses_Inaccessibles.csv using an improved
autocomplete-trigger strategy.  On success the record is moved to
data/Liste_Prospection.csv and removed from the inaccessibles file.

Root cause of the original failures
-------------------------------------
send_keys(address) types all characters in one shot (< 1 ms total).
Angular mat-autocomplete debounces input events and only fires its API call
after ~300 ms of inactivity, so the dropdown never appears and a
TimeoutException is thrown.

Fix
---
* Type each character individually with a 50 ms gap (CHAR_DELAY).
* Wait POST_TYPE_PAUSE seconds after the last keystroke.
* If still no suggestion, dispatch a native HTMLInputElement 'input' event
  via JavaScript as a second attempt.
* Rate-limit modal is detected in BOTH TimeoutException AND
  ElementClickInterceptedException paths (the modal can overlay the input).
"""

import csv
import os
import time

import pandas as pd

# ── Sharding ────────────────────────────────────────────────────────────────────
# In Phase 2 both GitHub workflows run this script in parallel on separate
# runners (separate IPs => separate hourly rate-limit budgets). Each takes a
# disjoint slice of the inaccessibles list keyed by its shard so they never
# retry the same address. Defaults (0/1) reproduce single-runner behaviour.
#
# Concurrency-safety of the CSV writes:
#   * Both shards only APPEND rescued rows to Liste_Prospection.csv; the
#     union-merge commit (see commit_changes) merges concurrent appends cleanly.
#   * Only shard 0 ever REWRITES Adresses_Inaccessibles.csv (reconcile step),
#     giving that file a single writer so removed rows are never resurrected by
#     the union merge.
SHARD_INDEX = int(os.environ.get("SHARD_INDEX", "0"))
SHARD_COUNT = int(os.environ.get("SHARD_COUNT", "1"))
IS_RECONCILER = SHARD_INDEX == 0
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ── Paths ──────────────────────────────────────────────────────────────────────
INACCESSIBLE_PATH = "data/Adresses_Inaccessibles.csv"
LISTED_PATH       = "data/Liste_Prospection.csv"
SEARCH_URL        = "https://espace-evaluation.sherbrooke.ca/consultation-du-role/recherche"

# ── Tuning ─────────────────────────────────────────────────────────────────────
CHAR_DELAY       = 0.05   # seconds between individual keystrokes
POST_TYPE_PAUSE  = 0.6    # seconds after last keystroke
SUGGEST_TIMEOUT  = 5      # seconds to wait for mat-option
FIELD_TIMEOUT    = 30     # seconds to wait for required page fields
OPT_TIMEOUT      = 3      # seconds for optional fields
RATE_LIMIT_SLEEP = 1800   # 30 min pause when hourly limit is reached
REQUEST_DELAY    = 3      # seconds between addresses
COMMIT_EVERY     = 300    # seconds between git auto-saves

# ── Output columns ─────────────────────────────────────────────────────────────
LISTED_COLS = [
    "ADRESSE", "RUE", "NB_LOGEMENTS", "DATE_CONSTRUCTION",
    "NO_ZONE", "GRILLEUSAGE", "ARRONDISSEMENT",
    "NOM_PROPRIETAIRE", "ADRESSE_PROPRIETAIRE", "DATE_INSCRIPTION",
    "URL", "GOOGLE_MAPS",
]

_DRIVER_PATH = ChromeDriverManager().install()


def make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    return webdriver.Chrome(service=Service(_DRIVER_PATH), options=opts)


def commit_changes() -> None:
    os.system('git config user.name  "github-actions[bot]"')
    os.system('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"')
    os.system(f'git add "{LISTED_PATH}" "{INACCESSIBLE_PATH}"')
    os.system("git commit -m 'Retry inaccessibles — auto-save' || echo 'No changes to commit'")
    # Union merge (not rebase): lets two parallel shards append to
    # Liste_Prospection.csv without clobbering each other. No force-push — a
    # failed push is simply retried on the next commit cycle. See CLAUDE.md.
    os.system(
        "git pull --no-rebase -s recursive -X union && git push "
        "|| echo 'Push failed — will retry next commit cycle'"
    )


def search_address(driver, wait, address):
    """Type address char-by-char then wait for mat-autocomplete suggestion."""
    inp = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, 'input[placeholder="Adresse..."]')
    ))
    inp.click()
    inp.clear()

    # Strategy 1: slow char-by-char typing
    for char in address:
        inp.send_keys(char)
        time.sleep(CHAR_DELAY)
    time.sleep(POST_TYPE_PAUSE)

    try:
        return WebDriverWait(driver, SUGGEST_TIMEOUT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "mat-option.mat-mdc-option"))
        )
    except TimeoutException:
        pass

    # Strategy 2: native JS InputEvent fallback
    driver.execute_script(
        """
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        setter.call(arguments[0], arguments[1]);
        arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
        """,
        inp, address,
    )
    time.sleep(POST_TYPE_PAUSE)
    return WebDriverWait(driver, SUGGEST_TIMEOUT).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "mat-option.mat-mdc-option"))
    )


def get_cell(driver, wait, xpath):
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    driver.execute_script("arguments[0].scrollIntoView(true);", el)
    return wait.until(EC.visibility_of(el)).text.strip()


def optional_cell(driver, xpath):
    try:
        w = WebDriverWait(driver, OPT_TIMEOUT)
        el = w.until(EC.presence_of_element_located((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        return w.until(EC.visibility_of(el)).text.strip()
    except Exception:
        return ""


def is_rate_limited(driver):
    try:
        return "Limite de consultations" in driver.page_source
    except Exception:
        return False


def _scrape_fields(driver, wait, row):
    """Scrape all property fields after suggestion is clicked. Returns list."""
    owner_name        = get_cell(driver, wait, '//tr[td[text()="Nom:"]]/td[2]')
    owner_address     = get_cell(driver, wait, '//tr[td[text()="Adresse Postale:"]]/td[2]')
    inscription_date  = get_cell(driver, wait,
                                 '//tr[td[contains(text(),"inscription au r")]]/td[2]')
    construction_date = optional_cell(driver,
                                      '//tr[td[text()="Ann\u00e9e de construction:"]]/td[2]')
    units             = optional_cell(driver, '//tr[td[text()="Nombre de logements:"]]/td[2]')
    return [
        row["ADRESSE"], row["RUE"], units, construction_date,
        row["NO_ZONE"], row["GRILLEUSAGE"], row["ARRONDISSEMENT"],
        owner_name, owner_address, inscription_date,
        driver.current_url, row.get("GOOGLE_MAPS", ""),
    ]


def _handle_rate_limit(driver, rescued, label=""):
    import datetime as _dt
    now = _dt.datetime.utcnow()
    next_hour = (now + _dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    sleep_time = max(int((next_hour - now).total_seconds()) + 120, 120)
    print(
        f"[RATE-LIMIT{label}]  Hourly limit reached after {len(rescued)} rescues. "
        f"Sleeping {sleep_time // 60}m {sleep_time % 60}s until next UTC-hour reset ..."
    )
    save_progress()
    time.sleep(sleep_time)
    driver.get(SEARCH_URL)


def reconcile_inaccessibles():
    """Rewrite Adresses_Inaccessibles.csv, dropping every address that now
    appears in Liste_Prospection.csv (i.e. rescued by either shard).

    Only shard 0 runs this, so the file has a single writer and the union-merge
    commit never resurrects removed rows. Reads both files fresh from disk so it
    also cleans up rows rescued by the other shard."""
    try:
        inacc  = pd.read_csv(INACCESSIBLE_PATH, encoding="utf-8-sig")
        listed = pd.read_csv(LISTED_PATH, encoding="utf-8-sig")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return
    listed_addr = set(listed.get("ADRESSE", pd.Series(dtype=str)).dropna())
    before = len(inacc)
    inacc = inacc[~inacc["ADRESSE"].isin(listed_addr)]
    if len(inacc) != before:
        inacc.to_csv(INACCESSIBLE_PATH, index=False, encoding="utf-8-sig")
        print(f"  -> Reconciled: dropped {before - len(inacc)} rescued row(s) "
              f"from Adresses_Inaccessibles.csv")


def save_progress():
    """Persist progress: reconcile the inaccessibles file (shard 0 only) then
    commit the appended rescues. Rescued rows are already appended to
    Liste_Prospection.csv during the loop, so shard >0 only needs to commit."""
    if IS_RECONCILER:
        reconcile_inaccessibles()
    commit_changes()


def main():
    if not os.path.exists(INACCESSIBLE_PATH):
        print("data/Adresses_Inaccessibles.csv not found — nothing to retry.")
        return

    inacc_df = pd.read_csv(INACCESSIBLE_PATH, encoding="utf-8-sig")
    if inacc_df.empty:
        print("Adresses_Inaccessibles.csv is empty — nothing to retry.")
        return

    if not os.path.exists(LISTED_PATH):
        with open(LISTED_PATH, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(LISTED_COLS)

    # Skip anything already rescued (present in Liste_Prospection.csv). This
    # prevents re-scraping — and duplicate Liste rows — when a row was rescued
    # by the other shard but not yet reconciled out of the inaccessibles file.
    try:
        already_listed = set(
            pd.read_csv(LISTED_PATH, encoding="utf-8-sig")
            .get("ADRESSE", pd.Series(dtype=str)).dropna()
        )
    except (FileNotFoundError, pd.errors.EmptyDataError):
        already_listed = set()

    # Assign a disjoint slice of the inaccessibles to this shard.
    work = [
        (idx, row) for i, (idx, row) in enumerate(inacc_df.iterrows())
        if i % SHARD_COUNT == SHARD_INDEX and str(row["ADRESSE"]) not in already_listed
    ]
    total = len(work)
    print(f"Shard {SHARD_INDEX + 1}/{SHARD_COUNT}: retrying {total} of "
          f"{len(inacc_df)} inaccessible addresses ...\n")

    if total == 0:
        print("Nothing to retry for this shard.")
        save_progress()   # shard 0 still reconciles rows the other shard rescued
        return

    driver      = make_driver()
    wait        = WebDriverWait(driver, FIELD_TIMEOUT)
    rescued     = []
    last_commit = time.time()

    for idx, row in work:
        a = str(row["ADRESSE"])
        time.sleep(REQUEST_DELAY)

        try:
            driver.get(SEARCH_URL)
            suggestion = search_address(driver, wait, a)
            suggestion.click()
            fields = _scrape_fields(driver, wait, row)
            with open(LISTED_PATH, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(fields)
            rescued.append(idx)
            print(f"[OK]   {a}  ({len(rescued)}/{total})")

        except TimeoutException:
            if is_rate_limited(driver):
                _handle_rate_limit(driver, rescued)
                # Retry same address after waking up
                try:
                    suggestion = search_address(driver, wait, a)
                    suggestion.click()
                    fields = _scrape_fields(driver, wait, row)
                    with open(LISTED_PATH, "a", newline="", encoding="utf-8-sig") as f:
                        csv.writer(f).writerow(fields)
                    rescued.append(idx)
                    print(f"[OK-RETRY]  {a}")
                except Exception as e2:
                    print(f"[STILL-FAIL] {a}: {e2}")
            else:
                print(f"[FAIL] {a} — no autocomplete suggestion")

        except ElementClickInterceptedException as e:
            # Rate-limit modal can intercept clicks to the input itself
            if is_rate_limited(driver):
                _handle_rate_limit(driver, rescued, " (click-intercepted)")
                try:
                    suggestion = search_address(driver, wait, a)
                    suggestion.click()
                    fields = _scrape_fields(driver, wait, row)
                    with open(LISTED_PATH, "a", newline="", encoding="utf-8-sig") as f:
                        csv.writer(f).writerow(fields)
                    rescued.append(idx)
                    print(f"[OK-RETRY]  {a}")
                except Exception as e2:
                    print(f"[STILL-FAIL] {a}: {e2}")
            else:
                print(f"[ERR]  {a}: {str(e)[:120]}")
                try: driver.get(SEARCH_URL)
                except Exception: pass

        except WebDriverException as e:
            err = str(e)
            if "invalid session id" in err or "target window already closed" in err:
                print("[FATAL] Driver session lost — stopping.")
                break
            print(f"[ERR]  {a}: {err[:120]}")
            try: driver.get(SEARCH_URL)
            except Exception: pass

        except Exception as e:
            print(f"[ERR]  {a}: {str(e)[:120]}")
            try: driver.get(SEARCH_URL)
            except Exception: pass

        if time.time() - last_commit > COMMIT_EVERY:
            save_progress()
            last_commit = time.time()

    driver.quit()
    save_progress()

    remaining = total - len(rescued)
    print(f"\n{'=' * 56}")
    print(f"Rescued  : {len(rescued)}/{total}")
    print(f"Remaining: {remaining}")
    print(f"{'=' * 56}")
    save_progress()
    print("Done.")


if __name__ == "__main__":
    main()
