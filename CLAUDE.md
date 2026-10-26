# Prospection — Claude Code Instructions

## STATUS: project complete — all scraper workflows DISABLED (Oct 26 2026)

The lists are done, so the five scraper workflows (`retry.yml`, `main.yml`, `shard1.yml`, `shard2.yml`, `shard3.yml`) were **disabled manually on Oct 26 2026** (`gh workflow disable`). Nothing runs on a schedule any more except GitHub's own "Dependency Graph" job (runs only when dependency files change; free). The code, workflow files, and data are all kept intact.

- **To turn it back on:** `gh workflow enable <file>` for each of the five files (e.g. `gh workflow enable retry.yml --repo KBAILEY90/Prospection`). Each shard has its own `SHARD_INDEX`/`SHARD_COUNT=5` in its YAML, so re-enable **all five** or the missing shards' slices are never retried.
- **Why stopped:** first pass finished Sep 6 2026 (53,106/53,106 unique addresses). Retry had been reporting `Rescued: 0` for weeks — see "Why the retry backlog doesn't drain" below. More runs could not change the lists, but they were burning ~38 runner-hours/day and committing a 22 MB CSV constantly (the repo reached ~443 MB).
- **Final state of the data (Oct 15 2026):** 51,998 rows listed, ~1,353 still in `Adresses_Inaccessibles.csv`. Roughly 88% of those have no match on the site at all (nothing to rescue). Roughly 10–12% (~170) are multi-unit addresses that need the unbuilt "pick a matricule" step; deliberately left unresolved.
- **Cost:** none. The repo is public, so Actions minutes are free (Oct 2026 used 56,738 min; list value ≈ $340). **If this repo is ever made private those minutes would be billed/exhausted almost immediately** — disable the workflows first.

## What this project is
Automated scraper that looks up zoning info and owner names for Quebec addresses from `data/Zonage.csv`. As of Sep 6 2026, the first-pass scrape of every unique address is **complete** — until Oct 26 2026 all 5 GitHub Actions workflows ran `3.Retry_Inaccessibles.py` (sharded 5 ways) to drain the remaining inaccessible backlog (now disabled, see STATUS above). `2.Prospection.py` is kept in the repo, unused for now, in case `Zonage.csv` ever grows.

**Goal:** ≤10% inaccessible rate in `data/Adresses_Inaccessibles.csv` with ≥1,000 combined rows. (Achieved — rate was ~2.6% as of Sep 6 2026. Remaining work is optimization/completionist cleanup, not required to hit the target.)

---

## Checking the current status

```bash
git pull
wc -l data/Liste_Prospection.csv data/Adresses_Inaccessibles.csv
```

Calculate:
- **Listed rows** = `Liste_Prospection.csv` line count − 1 (header)
- **Inaccessible rows** = `Adresses_Inaccessibles.csv` line count − 1 (header)
- **Inaccessible %** = Inaccessible ÷ (Listed + Inaccessible) × 100

**Caution on "remaining" math:** do NOT compute remaining as `Zonage.csv row count − (Listed + Inaccessible)`. `Zonage.csv` has 55,575 *rows* but only **53,106 unique addresses** (407 addresses appear more than once, e.g. multiple units at one civic address) — the scripts dedupe by address string, so that arithmetic overstates remaining work by ~2,469. Trust the script's own printed `Remaining` line (or `Already done` vs the 53,106 unique-address total) over a row-count subtraction.

Current benchmark (Sep 6, 2026): ~2.6% — target is ≤10%, already well cleared. (Rate rose from 12.2% to 14.4% Jun 19 → Jul 14 due to the force-push bug below; fixed Jul 14, then fell steadily as first-pass scraping finished and retry kept draining the backlog.)

---

## Key files

*(All five workflow files below are **disabled** as of Oct 26 2026 — see STATUS at the top. The schedules listed are what they ran at before being disabled.)*

| File | Purpose |
|------|---------|
| `2.Prospection.py` | Main scraper — **currently unused** (first pass complete), kept for if `Zonage.csv` grows |
| `3.Retry_Inaccessibles.py` | Retries inaccessibles — now runs sharded 5 ways across all 5 workflows below |
| `data/Zonage.csv` | Source address list — 55,575 rows, **53,106 unique addresses** (see caution above) |
| `data/Liste_Prospection.csv` | Successfully scraped addresses |
| `data/Adresses_Inaccessibles.csv` | Addresses that hit rate limit — the shrinking retry backlog |
| `.github/workflows/retry.yml` | Retry shard 0 of 5 — hourly at :00 (was the original unsharded retry job) |
| `.github/workflows/main.yml` | Retry shard 1 of 5 — hourly at :00 (was prospection shard 0, was `2.Prospection.py`) |
| `.github/workflows/shard1.yml` | Retry shard 2 of 5 — hourly at :15 (was prospection shard 1, was `canary-test.yml`) |
| `.github/workflows/shard2.yml` | Retry shard 3 of 5 — hourly at :30 (was prospection shard 2) |
| `.github/workflows/shard3.yml` | Retry shard 4 of 5 — hourly at :45 (was prospection shard 3) |

---

## How the scripts work

- **Prospection** builds a `done` set from both CSVs at startup — never re-searches an address
- **Retry** on success: appends rescued row to `Liste_Prospection.csv` AND removes it from `Adresses_Inaccessibles.csv`
- **Retry sharding** (Sep 6 2026): filters `Adresses_Inaccessibles.csv` down to this shard's slice (same md5-hash partition as prospection) before shuffling. `_save_progress` re-reads the live on-disk file and removes only this run's rescued addresses **by value** — it does NOT rewrite the file from the in-memory (shard-filtered) DataFrame. Do not "simplify" this back to a full-DataFrame overwrite — that would delete every other shard's rows on every save.
- **Rate limit**: city website resets hourly ("Limite de consultations") — retry sleeps until next UTC hour + 120s

---

## Bugs already fixed — do not revert

1. **Force-push bug** (`2.Prospection.py`) — fixed TWICE, do not reintroduce any `--force*` flag:
   - v1: `git push || git push --force` silently overwrote retry commits.
   - v2 (regression, fixed Jul 8 2026): `... && git push || git push --force-with-lease` — the lease matched because the pull had just fetched, so it still overwrote retry's rescue commits (observed as `(forced update)` on origin/main). Now: `git pull --no-rebase -s recursive -X union && git push || echo 'Push failed'`.
2. **Retry commit_changes**: replaced fragile multi-line push block with rebase-abort-on-failure pattern
3. **Autocomplete debounce bug** (fixed Jul 8 2026): `2.Prospection.py` used one-shot `send_keys(a)`; Angular's debounced mat-autocomplete never fired → TimeoutException → address wrongly marked inaccessible. This was the ~12–15% inflow floor. Backported the retry script's fix (char-by-char typing + JS `input`-event fallback). Also raised `MAX_RETRIES` 0→1.
4. **Retry head-of-file grind** (fixed Jul 14 2026): `3.Retry_Inaccessibles.py` processed rows in file order; permanently-dead addresses accumulate at the head, so every run burned hours re-failing them before reaching rescuable rows. Now shuffles the order each run (`inacc_df.sample(frac=1)`).
5. **RETRACTED — "site changed underneath the scripts" was a wrong root cause** (investigated Sep 7 → Oct 15 2026; see "Why the retry backlog doesn't drain" below). The retry search **works** — confirmed locally with the production code and from CI's own logs. Things this investigation tried that were **not** the cause and need not be revisited: the cookie-consent dialog (CookieConsent v3, `#cc-main`; it appears on CI runners but not on a fresh local profile, and no evidence it affects results), the duplicate hidden `Adresse...` input (`get_visible_input()` is harmless and can stay), `navigator.webdriver` masking, `--headless=new`, an app "loading" state (the `div.loader` text stays in the DOM forever, so a text check is always true), and the claim that the autocomplete needs a full keydown/input/keyup sequence (a flawed manual test; plain Selenium `send_keys` works). Several of these were deployed as speculative changes (webdriver masking flags + CDP script, `--headless=new`, `[DIAG]` logging with `get_log`) — they are unnecessary and may be removed.

Note: fixes #1v2 and #3 were first pushed Jul 8 but were themselves erased by an in-flight workflow run still executing the old force-push code. Re-deployed Jul 14. If a `(forced update)` ever appears on origin/main again, check that these fixes are still present.

---

## Why the retry backlog doesn't drain (root cause found Oct 15 2026)

The backlog (`Adresses_Inaccessibles.csv`, ~1,353 rows) is mostly **not rescuable by this approach**, and retry runs report `Rescued: 0` because of what the backlog now contains — not because anything is broken:

1. **~88% have no match at all.** The site's autocomplete calls a vendor API: `https://vplus.modellium.com/api/espace-evaluation.sherbrooke.ca/role/cpr/autocompleteaddress?input=<address>` (needs no auth; sends `RateLimit-Limit: 300` per 60s). It returns `[]` for these — the address string isn't in the role under that spelling. Nothing to rescue. (40-address sample: 35 empty.)
2. **~10–12% are multi-matricule addresses** (condo/multi-unit style: 2–8 matricules each). The API returns matches; after the suggestion is clicked the UI shows a **"Matricule" dropdown** and does not load the detail page until one is chosen. `_scrape_fields` waits `FIELD_TIMEOUT` (30s) for the `Nom:` cell, times out, and `main()`'s generic `except TimeoutException` prints **`[FAIL] … no autocomplete suggestion` — a misleading label**: the suggestion *did* appear. In a CI log, a `[FAIL]` with **no preceding `[DIAG]`** is this case (25 of 263 in the Oct 15 shard-4 run).
3. The detail page is directly addressable: `https://espace-evaluation.sherbrooke.ca/consultation-du-role/role?matricule=<MATRICULE>` (this is the `URL` column format), and the API supplies the matricules. Direct loads scrape fine with the existing selectors (the owner text fills in a moment after the `Nom:` cell appears — wait for non-empty text). Unit-level pages can be sub-lots (e.g. a unit whose usage is vacant land), so "which matricule represents the address" is an open **data-model decision** (first matricule? one row per unit?) — not yet made.

**How this was found (reuse it):** don't iterate via CI cancel-after-N-minutes cycles — they cost hours and Python's stdout buffering hid output. Instead (a) `curl` the autocomplete API for sample backlog addresses to see which even have matches; (b) install `selenium` in a throwaway venv and run the real `make_driver`/`search_address`/`_scrape_fields` locally on known-hit addresses (the cookie dialog doesn't even show locally; pandas can be stubbed if the machine's app-control blocks its DLL); (c) split CI `[FAIL]` lines by presence of the preceding `[DIAG]` line. The earlier "site broke" theory came from testing only addresses that legitimately have no match and never running a known-good control.

---

## Why the rate was rising (root cause found Jul 14 2026)
Git history showed 178 commits in 7 days, ALL from prospection — zero surviving retry commits despite retry running 12×/day. Prospection's force-push fallback was erasing every retry rescue. Combined with the debounce bug feeding ~75 false inaccessibles/day, the rate climbed 12.2% → 14.4%. Both causes fixed; retry and prospection run on separate GitHub runners (separate IPs → separate hourly quotas), so retry is free parallel throughput — do NOT pause it to "give prospection room"; they don't compete.

---

## Progress history

| Date     | Inaccessible | Total Processed | Rate  |
|----------|-------------|-----------------|-------|
| Apr 12   | 1,142       | ~6,662          | 17.1% |
| Apr 26   | 2,464       | ~19,808         | 12.4% |
| May 4    | 2,659       | ~21,393         | 12.4% |
| May 23   | 3,223       | ~26,721         | 12.1% |
| Jun 19   | ~3,275      | ~26,794         | 12.2% |
| Jun 23   | 5,175       | 38,870          | 13.3% |
| Jul 8    | 6,167       | 43,926          | 14.0% |
| Jul 14   | 6,626       | 46,069          | 14.4% |

Processing pace: ~352/day observed Jul 7 → Jul 14. Est. ~24k first-pass addresses remain → ~mid-September 2026 at that pace, with the backlog draining in parallel via retry now that its rescues persist. Throughput ceiling is the city site's hourly quota (~15/hr per runner); no code change moves it.

---

## Parallel scraper shards (added Jul 19 2026)

**Canary test result (Jul 17 2026):** ran `canary-test.yml` (manual duplicate of `main.yml`) concurrently with a live prospection run for ~4 hours. Both hit `RATE_LIMIT` independently, roughly once per hour, on their own schedule, with no mutual slowdown — confirming Sherbrooke's hourly limit is scoped **per-runner**, not shared across GitHub's IP pool. Retry's log (running the same window) also showed uninterrupted progress. Conclusion: concurrent jobs are real additional throughput, not contention.

**Bug found by the same test:** with two unsharded jobs both scanning the full remaining address list from the top, 88 addresses got scraped twice (each duplicate wastes one rate-limited request for nothing). Fixed in `2.Prospection.py` (Jul 19 2026): `SHARD_INDEX`/`SHARD_COUNT` env vars partition the address space by a stable md5 hash of each address, so concurrent jobs each own a disjoint slice with zero coordination or locking needed. `SHARD_COUNT=1` (unset) is a no-op — do not deploy a `SHARD_COUNT` change to one workflow without updating all shard workflows in the same commit, or the unassigned index range never gets processed.

**Current setup:** 4 parallel prospection shards, one job each, staggered 15 min apart (`main.yml`=0 :00, `shard1.yml`=1 :15, `shard2.yml`=2 :30, `shard3.yml`=3 :45), all with `SHARD_COUNT=4`. `retry.yml` is unaffected — single job, no sharding needed since it's not in a race with itself.

**Why 4 and not more:** the per-runner-quota finding was validated at N=2, not N=10. A municipal site is more likely to have a coarse abuse threshold (e.g. blocking a whole datacenter IP range) than to scale linearly forever, and if that trips, it likely breaks *all* shards at once, not just the excess ones — worse than staying at a lower N. 4 was chosen as a cautious doubling of the validated baseline.

**Scale-up plan:** watch shard behavior for a few days for any sign of a shared/coarser limit — unexpected `RATE_LIMIT` clustering across shards, unusual error rates, or per-shard throughput below the ~15/hr baseline. If clean, consider stepping to 6, then re-assess before going further. Don't jump straight to a high N (e.g. 10) without incremental validation.

---

## Retry sharding — first pass complete (Sep 6 2026)

**What happened:** all 4 prospection shards independently logged `Remaining: 0` / "Nothing left to process" — the first-pass scrape of every unique address in `Zonage.csv` (53,106 of them) is done. This is what caused the apparent "only 10 new addresses" between two status checks that looked like a slowdown — it wasn't decay, first-pass work had simply run out. (This is also how the 55,575-vs-53,106 row/unique-address discrepancy above was discovered.)

**The pivot:** rather than let the 4 idle prospection shards sit doing nothing every hour, they were repointed to run `3.Retry_Inaccessibles.py` instead, folded into a 5-way shard scheme alongside the original `retry.yml` (now shard 0). Same non-collision guarantee as prospection sharding: `SHARD_INDEX`/`SHARD_COUNT` env vars, same md5-hash partition function (duplicated into `3.Retry_Inaccessibles.py`), so no two retry shards ever attempt the same address.

**A real bug caught before deploying this:** `_save_progress` originally did `inacc_df.drop(index=rescued).to_csv(...)` — a full overwrite of `Adresses_Inaccessibles.csv` from whatever `inacc_df` held in memory. That was safe when `inacc_df` was the complete backlog, but once sharded it only holds ~1/5 of the rows — the naive overwrite would have silently deleted every *other* shard's rows on every periodic save. Fixed to re-read the file fresh and remove only the rescued addresses **by value** (`isin()`), which is also robust to the file having changed on disk mid-run (e.g. a `git pull` merging in another shard's commits). See the code comment on `_save_progress` — do not revert to the DataFrame-based overwrite.

Also hardened retry's own `commit_changes()` to use the same union-merge pull (`git pull --no-rebase -s recursive -X union`) that prospection's shards use, instead of plain `git pull --rebase` — with 5 concurrent jobs committing to the same two CSVs, merge conflicts are now the expected case, not the exception.

**Current setup:** 5 retry shards, hourly, staggered (`retry.yml`=0 :00, `main.yml`=1 :00, `shard1.yml`=2 :15, `shard2.yml`=3 :30, `shard3.yml`=4 :45), all `SHARD_COUNT=5`.

**On extending the per-runner-quota assumption to retry:** the canary test (above) validated independent hourly quotas specifically for *prospection*-type jobs. This change assumes the same holds for retry-type jobs on separate runners, since the mechanism (separate GitHub-hosted VM → separate egress IP) is identical regardless of which script runs — but this specific extension has not been separately canary-tested. Worth a similar concurrent-log comparison if retry shards ever show unexpected `RATE_LIMIT` clustering.

**`2.Prospection.py` is not deleted** — if `Zonage.csv` ever gains new rows (a new source-data pull), the script and its shard-aware logic are ready to point workflows back at it.

---

## Progress history (continued)

| Date     | Inaccessible | Total Processed | Rate  |
|----------|-------------|-----------------|-------|
| Jul 25   | ~1,300      | ~46,500         | 11.3% |
| Sep 6 (pre-retry-sharding) | 1,877 → 1,416 (same day, retry draining) | ~53,340 | 3.5% → 2.6% |

First-pass scraping complete as of Sep 6 2026 (53,106/53,106 unique addresses attempted). Remaining work is retry continuing to rescue addresses out of the inaccessible pile — every rescue lowers the rate further, but there's no more "total processed" growth from new addresses, only backlog movement between the two CSVs.

---

## "90% of GitHub Actions storage" email (Oct 26 2026) — investigated

**Not caused by this repo.** All Actions-storage usage on the account (every month since Jun 2026) was attributed to a **different repo, PhonoLeaf** (archived, private; website since migrated to Everbloom-Technologies / Cloudflare Pages). This repo (public) has no storage usage, 0 artifacts and 0 caches, and its minutes are free.

- PhonoLeaf held a **constant ~565 MB (13.25 GB-hours/day) every day from Sep 11 onward** — right after its last Pages deploys on Sep 10 — that never expired, and the meter was still accruing on Oct 26. It was invisible to the API: 0 artifacts, 0 caches, 0 releases, no Git LFS; its only workflow (`deploy.yml`) uploads a Pages artifact that normally expires after 1 day. Best guess (unproven): leftover storage GitHub wasn't expiring, possibly because the repo is archived. Free-allowance math: 500 MB × 744 h ≈ 372 GB-hours/month, so a flat 565 MB crosses 90% around the 26th every month. Net cost was $0.00 even in months over the allowance (Aug 2026: 890 GB-hours).
- **Resolution: PhonoLeaf was deleted on Oct 26 2026** (`gh repo delete KBAILEY90/PhonoLeaf --yes`) at the owner's request, since the site had long since moved to the Everbloom-Technologies / Cloudflare Pages migration and was working. It was archived, private, 62 MB, 0 forks/issues, last push Sep 10 2026. No local backup was taken. GitHub documents that many deleted repos can be restored from Settings → Repositories → Deleted repositories for ~90 days (not verified for this one). Expect the storage meter to stop accruing; confirm on or after Nov 1 2026 (the "Actions storage" row for PhonoLeaf should be gone). If an "Actions storage" email arrives again, it is not from this repo — re-run the billing query below to see which repo it is.
- **How to read billing from the CLI** (the old `/settings/billing/actions` endpoints now return 410): `gh auth refresh -h github.com -s user`, then `gh api "users/<user>/settings/billing/usage?year=2026&month=10&day=<d>"` (per-day) or `.../usage/summary`. Rows are per `sku` + `repositoryName`; "Actions storage" is in GigabyteHours, "Actions Linux" in Minutes.

---

## Session notes
Full context is also stored in Google Drive:
`Real Estate > Plexes > Gesbrooke > Prospection > PROJECT_NOTES.md`
Drive folder ID: `10kUQg2czZQ9GBiw7WtCKs-3JVUewgMSX`
