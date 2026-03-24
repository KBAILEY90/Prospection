#!/usr/bin/env python
# coding: utf-8

"""
2.Prospection.py - Optimised parallel scraper
==============================================
Improvements over original:
  * BUG FIX #1  XPath apostrophe: uses contains() to match "inscription au r"
                so U+2019 vs U+0027 never causes a mismatch again.
  * BUG FIX #2  optional_cell() for building fields (vacant lots lack them).
  * BUG FIX #3  Column-name guard: handles both GOOGLE_MAPS and GMAPS_URL.
  * PERF       N_WORKERS parallel Chrome instances share a work queue.
  * PERF       Removed fixed 1 s sleep between addresses (wait.until is enough).
  * FIX        Navigate to search page per address (clean Angular state).
  * PERF       Thread-safe CSV writes with in-memory duplicate guard.
  * FIX        Retry logic: up to MAX_RETRIES attempts per address before giving up.
  * FIX        Overlay/intercept handler: dismiss dialog instead of sleeping 60 s.
  * DEBUG      Rich error context logged on every failure (URL, input value,
               visible options, any dialog text).
"""

import csv
import os
import time
import threading
from queue import Queue, Empty
import concurrent.futures

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    NoSuchElementException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# -- Configuration -------------------------------------------------------------
N_WORKERS      = 2       # parallel Chrome instances (safe for GH Actions 2-vCPU)
TIMEOUT        = 30      # seconds -- required page elements (raised from 5 to 30 to reduce false timeouts)
OPT_TIMEOUT    = 2       # seconds -- optional fields (may be absent on vacant lots)
COMMIT_EVERY   = 300     # seconds between git auto-commits
MAX_RETRIES    = 0       # max extra attempts per address before marking inaccessible
RATE_LIMIT_SLEEP = 1800  # seconds to pause when the site's hourly query limit is hit
REQUEST_DELAY  = 15      # seconds to wait between addresses (throttle to stay within hourly limit)
SEARCH_URL     = "https://espace-evaluation.sherbrooke.ca/consultation-du-role/recherche"

inaccessible_path = "data/Adresses_Inaccessibles.csv"
listed_path       = "data/Liste_Prospection.csv"
zonage_path       = "data/Zonage.csv"

# -- Load source data ----------------------------------------------------------
joined_df = pd.read_csv(zonage_path, encoding="utf-8-sig")
gmaps_col = "GOOGLE_MAPS" if "GOOGLE_MAPS" in joined_df.columns else "GMAPS_URL"

COLUMNS = [
    "ADRESSE", "RUE", "NB_LOGEMENTS", "DATE_CONSTRUCTION",
    "NO_ZONE", "GRILLEUSAGE", "ARRONDISSEMENT",
    "NOM_PROPRIETAIRE", "ADRESSE_PROPRIETAIRE", "DATE_INSCRIPTION",
    "URL", "GOOGLE_MAPS",
]
ERROR_COLS = list(joined_df.columns)

os.makedirs("errors", exist_ok=True)

# Initialise output CSVs if missing
for path, header in [(listed_path, COLUMNS), (inaccessible_path, ERROR_COLS)]:
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(header)

# Build todo list (skip already done)
listed_df       = pd.read_csv(listed_path,       encoding="utf-8-sig")
inaccessible_df = pd.read_csv(inaccessible_path, encoding="utf-8-sig")

done = set(
    pd.concat([
        listed_df.get("ADRESSE",       pd.Series(dtype=str)),
        inaccessible_df.get("ADRESSE", pd.Series(dtype=str)),
    ]).dropna()
)

todo = [a for a in joined_df["ADRESSE"].tolist() if a not in done]
total = len(todo)
print(f"Total addresses : {len(joined_df)}")
print(f"Already done    : {len(done)}")
print(f"Remaining       : {total}")

if not todo:
    print("Nothing left to process. Exiting.")
    raise SystemExit(0)

# -- Shared state --------------------------------------------------------------
address_queue = Queue()
for a in todo:
    address_queue.put(a)

write_lock  = threading.Lock()   # guards listed_path writes
inacc_lock  = threading.Lock()   # guards inaccessible_path writes + inacc_seen
stats_lock  = threading.Lock()   # guards stats dict

inacc_seen  = set(inaccessible_df.get("ADRESSE", pd.Series(dtype=str)).dropna())
stats       = {"ok": 0, "fail": 0}
_t0         = time.time()

# -- Helpers -------------------------------------------------------------------
def make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts
    )


def get_cell(wait: WebDriverWait, driver, xpath: str) -> str:
    """Required field -- raises TimeoutException if not found."""
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    driver.execute_script("arguments[0].scrollIntoView(true);", el)
    return wait.until(EC.visibility_of(el)).text.strip()


def optional_cell(driver, xpath: str) -> str:
    """Optional field -- returns '' if absent (e.g. vacant lots)."""
    try:
        w  = WebDriverWait(driver, OPT_TIMEOUT)
        el = w.until(EC.presence_of_element_located((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        return w.until(EC.visibility_of(el)).text.strip()
    except Exception:
        return ""


def get_error_context(driver) -> str:
    """
    Collect diagnostic info from the current page state to help explain why
    an address failed. Logged alongside every FAIL/RETRY line.
    """
    parts = []

    # Where are we?
    try:
        parts.append(f"url={driver.current_url}")
    except Exception:
        parts.append("url=N/A")

    # What's in the search input?
    try:
        val = driver.find_element(
            By.CSS_SELECTOR, 'input[placeholder="Adresse..."]'
        ).get_attribute("value")
        parts.append(f"input='{val}'")
    except Exception:
        parts.append("input=N/A")

    # Are there autocomplete options visible?
    try:
        opts = driver.find_elements(By.CSS_SELECTOR, "mat-option")
        if opts:
            parts.append(f"options=[{', '.join(o.text[:25] for o in opts[:3])}]")
        else:
            parts.append("options=none")
    except Exception:
        parts.append("options=error")

    # Is there a "no results" message?
    try:
        no_res = driver.find_elements(
            By.XPATH,
            '//*[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),'
            '"aucun") or contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"no result")]',
        )
        if no_res:
            parts.append(f"no_results='{no_res[0].text[:40]}'")
    except Exception:
        pass

    # Any visible dialog / overlay?
    try:
        dialogs = driver.find_elements(
            By.CSS_SELECTOR, '[role="dialog"], [class*="modal"], [class*="overlay"]'
        )
        visible = [d for d in dialogs if d.is_displayed()]
        if visible:
            parts.append(f"dialog='{visible[0].text[:60]}'")
    except Exception:
        pass

    return "  |  ".join(parts)


def dismiss_overlay(driver) -> bool:
    """
    Try to close any cookie-consent or modal overlay that might be
    intercepting clicks. Returns True if something was dismissed.
    """
    selectors = [
        # Generic close / accept buttons
        'button[class*="close"]',
        'button[class*="accept"]',
        'button[class*="agree"]',
        'button[class*="ok"]',
        '[class*="cookie"] button',
        '[class*="consent"] button',
        '[aria-label*="close"]',
        '[aria-label*="fermer"]',
        # Angular Material dialog close
        'mat-dialog-container button',
    ]
    for sel in selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed():
                btn.click()
                time.sleep(0.5)
                return True
        except (NoSuchElementException, Exception):
            continue
    return False


def safe_write_listed(fields: list) -> None:
    with write_lock:
        with open(listed_path, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(fields)


def safe_write_inaccessible(row) -> None:
    with inacc_lock:
        if row["ADRESSE"] not in inacc_seen:
            inacc_seen.add(row["ADRESSE"])
            with open(inaccessible_path, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(list(row))


def commit_changes() -> None:
    os.system('git config user.name  "github-actions[bot]"')
    os.system('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"')
    os.system(f'git add "{listed_path}" "{inaccessible_path}"')
    os.system("git commit -m 'Auto-save progress' || echo 'No changes to commit'")
    os.system("git pull --rebase && git push || git push")


# -- Worker --------------------------------------------------------------------
def worker(worker_id: int) -> None:
    driver = make_driver()
    wait   = WebDriverWait(driver, TIMEOUT)
    last_commit = time.time()
    print(f"[W{worker_id}] Ready", flush=True)

    while True:
        try:
            a = address_queue.get_nowait()
        except Empty:
            break

        row = joined_df.loc[joined_df["ADRESSE"] == a].iloc[0]

        success      = False
        last_err     = ""
        rate_limited = False

        for attempt in range(MAX_RETRIES + 1):
            try:
                # -- Navigate to search page for clean Angular state ----------
                driver.get(SEARCH_URL)

                # -- Search ---------------------------------------------------
                inp = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'input[placeholder="Adresse..."]')
                ))
                inp.click()
                inp.send_keys(a)

                # Wait for autocomplete suggestion
                suggestion = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "mat-option.mat-mdc-option")
                ))
                suggestion.click()

                # -- Extract data ---------------------------------------------
                ownerName    = get_cell(wait, driver, '//tr[td[text()="Nom:"]]/td[2]')
                ownerAddress = get_cell(wait, driver, '//tr[td[text()="Adresse Postale:"]]/td[2]')

                # FIX: contains() avoids U+2019 (curled ') vs U+0027 (straight ') mismatch
                inscriptionDate  = get_cell(
                    wait, driver,
                    '//tr[td[contains(text(),"inscription au r")]]/td[2]'
                )
                # Optional -- vacant lots won't have these rows
                constructionDate = optional_cell(
                    driver, '//tr[td[text()="Ann\u00e9e de construction:"]]/td[2]'
                )
                units = optional_cell(
                    driver, '//tr[td[text()="Nombre de logements:"]]/td[2]'
                )

                url   = driver.current_url
                gmaps = row.get(gmaps_col, "")

                safe_write_listed([
                    a, row["RUE"], units, constructionDate,
                    row["NO_ZONE"], row["GRILLEUSAGE"], row["ARRONDISSEMENT"],
                    ownerName, ownerAddress, inscriptionDate, url, gmaps,
                ])

                with stats_lock:
                    stats["ok"] += 1
                    done_n = stats["ok"] + stats["fail"]
                    remaining = address_queue.qsize()
                    rate = done_n / max(time.time() - _t0, 1)
                    eta_min = remaining / rate / 60 if rate > 0 else 0
                    retry_tag = f" (retry {attempt})" if attempt > 0 else ""
                    print(
                        f"[W{worker_id}] OK {a:<35}{retry_tag} "
                        f"({done_n}/{total})  ~{remaining} left  "
                        f"ETA {eta_min:.0f} min",
                        flush=True,
                    )

                success = True
                break  # exit retry loop

            except ElementClickInterceptedException as e:
                ctx = get_error_context(driver)
                safe_name = a.replace(" ", "_")[:40]
                driver.save_screenshot(f"errors/w{worker_id}_{safe_name}_a{attempt}.png")

                # Try to dismiss whatever is blocking the click
                dismissed = dismiss_overlay(driver)

                # Detect the site's hourly consultation rate limit
                if "Limite de consultations" in ctx:
                    print(
                        f"[W{worker_id}] RATE_LIMIT {a} -- hourly limit reached, "
                        f"sleeping {RATE_LIMIT_SLEEP}s then re-queuing",
                        flush=True,
                    )
                    time.sleep(RATE_LIMIT_SLEEP)
                    address_queue.put(a)   # re-queue address to retry after limit resets
                    rate_limited = True
                    break

                print(
                    f"[W{worker_id}] INTERCEPTED attempt={attempt} {a} "
                    f"(overlay_dismissed={dismissed})  {ctx}",
                    flush=True,
                )
                last_err = f"ElementClickInterceptedException  {ctx}"
                # Short pause before retry
                time.sleep(2)

            except TimeoutException as e:
                ctx = get_error_context(driver)
                safe_name = a.replace(" ", "_")[:40]
                driver.save_screenshot(f"errors/w{worker_id}_{safe_name}_a{attempt}.png")

                print(
                    f"[W{worker_id}] TIMEOUT attempt={attempt} {a}  {ctx}",
                    flush=True,
                )
                last_err = f"TimeoutException  {ctx}"
                # Brief pause before retry
                time.sleep(1)

            except Exception as e:
                err = str(e)
                ctx = get_error_context(driver)
                safe_name = a.replace(" ", "_")[:40]
                driver.save_screenshot(f"errors/w{worker_id}_{safe_name}_a{attempt}.png")

                if "invalid session id" in err or "target window already closed" in err:
                    print(f"[W{worker_id}] FATAL Session lost -- stopping worker", flush=True)
                    driver.quit()
                    return

                print(
                    f"[W{worker_id}] ERROR attempt={attempt} {a}: {err[:120]}  {ctx}",
                    flush=True,
                )
                last_err = f"{err[:80]}  {ctx}"
                time.sleep(1)

        # -- After all attempts -----------------------------------------------
        if not success and not rate_limited:
            with stats_lock:
                stats["fail"] += 1
                done_n = stats["ok"] + stats["fail"]
                print(
                    f"[W{worker_id}] FAIL {a} after {MAX_RETRIES + 1} attempts: "
                    f"{last_err[:120]}  ({done_n}/{total})",
                    flush=True,
                )
            safe_write_inaccessible(row)

        # Throttle requests to stay within the site's hourly query limit
        if not rate_limited:
            time.sleep(REQUEST_DELAY)

        # Periodic git commit
        if time.time() - last_commit > COMMIT_EVERY:
            commit_changes()
            last_commit = time.time()

    driver.quit()
    print(f"[W{worker_id}] Finished", flush=True)


# -- Main ----------------------------------------------------------------------
if __name__ == "__main__":
    _t0 = time.time()
    print(f"Launching {N_WORKERS} parallel worker(s)...", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(worker, i + 1): i for i in range(N_WORKERS)}
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as exc:
                print(f"Worker {futures[f] + 1} raised: {exc}", flush=True)

    elapsed  = time.time() - _t0
    ok, fail = stats["ok"], stats["fail"]
    done_n   = ok + fail
    rate     = done_n / elapsed if elapsed > 0 else 0

    print(f"\n{'=' * 56}")
    print(f"Finished in {elapsed:.0f} s  |  OK {ok}  FAIL {fail}  |  {rate:.2f} addr/s")
    print(f"{'=' * 56}", flush=True)

    commit_changes()
    print("All done.", flush=True)
