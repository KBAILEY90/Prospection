# Prospection — Claude Code Instructions

## What this project is
Automated scraper that looks up zoning info and owner names for Quebec addresses from `data/Zonage.csv`. Two GitHub Actions workflows run continuously:
- `2.Prospection.py` — processes new addresses every hour (:00)
- `3.Retry_Inaccessibles.py` — retries failed addresses every 2 hours (:30)

**Goal:** ≤10% inaccessible rate in `data/Adresses_Inaccessibles.csv` with ≥1,000 combined rows.

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

Current benchmark (Jul 14, 2026): ~14.4% — target is ≤10%. (Rate rose steadily since Jun 19 because retry's rescue commits were being force-push-wiped; fixes deployed Jul 14, see bug list below.)

---

## Key files

| File | Purpose |
|------|---------|
| `2.Prospection.py` | Main scraper — runs hourly via GitHub Actions |
| `3.Retry_Inaccessibles.py` | Retries inaccessibles — runs every 2h |
| `data/Zonage.csv` | Source address list (~70k total addresses) |
| `data/Liste_Prospection.csv` | Successfully scraped addresses |
| `data/Adresses_Inaccessibles.csv` | Addresses that hit rate limit |
| `.github/workflows/main.yml` | Prospection shard 0 of 4 — hourly at :00 |
| `.github/workflows/shard1.yml` | Prospection shard 1 of 4 — hourly at :15 (was `canary-test.yml`) |
| `.github/workflows/shard2.yml` | Prospection shard 2 of 4 — hourly at :30 |
| `.github/workflows/shard3.yml` | Prospection shard 3 of 4 — hourly at :45 |
| `.github/workflows/retry.yml` | Retry workflow schedule (unsharded, single job) |

---

## How the scripts work

- **Prospection** builds a `done` set from both CSVs at startup — never re-searches an address
- **Retry** on success: appends rescued row to `Liste_Prospection.csv` AND removes it from `Adresses_Inaccessibles.csv`
- **Rate limit**: city website resets hourly ("Limite de consultations") — retry sleeps until next UTC hour + 120s

---

## Bugs already fixed — do not revert

1. **Force-push bug** (`2.Prospection.py`) — fixed TWICE, do not reintroduce any `--force*` flag:
   - v1: `git push || git push --force` silently overwrote retry commits.
   - v2 (regression, fixed Jul 8 2026): `... && git push || git push --force-with-lease` — the lease matched because the pull had just fetched, so it still overwrote retry's rescue commits (observed as `(forced update)` on origin/main). Now: `git pull --no-rebase -s recursive -X union && git push || echo 'Push failed'`.
2. **Retry commit_changes**: replaced fragile multi-line push block with rebase-abort-on-failure pattern
3. **Autocomplete debounce bug** (fixed Jul 8 2026): `2.Prospection.py` used one-shot `send_keys(a)`; Angular's debounced mat-autocomplete never fired → TimeoutException → address wrongly marked inaccessible. This was the ~12–15% inflow floor. Backported the retry script's fix (char-by-char typing + JS `input`-event fallback). Also raised `MAX_RETRIES` 0→1.
4. **Retry head-of-file grind** (fixed Jul 14 2026): `3.Retry_Inaccessibles.py` processed rows in file order; permanently-dead addresses accumulate at the head, so every run burned hours re-failing them before reaching rescuable rows. Now shuffles the order each run (`inacc_df.sample(frac=1)`).

Note: fixes #1v2 and #3 were first pushed Jul 8 but were themselves erased by an in-flight workflow run still executing the old force-push code. Re-deployed Jul 14. If a `(forced update)` ever appears on origin/main again, check that these fixes are still present.

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

## Session notes
Full context is also stored in Google Drive:
`Real Estate > Plexes > Gesbrooke > Prospection > PROJECT_NOTES.md`
Drive folder ID: `10kUQg2czZQ9GBiw7WtCKs-3JVUewgMSX`
