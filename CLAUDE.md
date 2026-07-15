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
| `.github/workflows/main.yml` | Prospection workflow schedule |
| `.github/workflows/retry.yml` | Retry workflow schedule |
| `.github/workflows/canary-test.yml` | Manual-only (`workflow_dispatch`), no schedule — see below |

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

## Canary test workflow (added Jul 14 2026)
`canary-test.yml` is a manual-only duplicate of `main.yml`, used to test whether Sherbrooke's hourly rate limit is scoped per-runner-IP (in which case a 3rd standing scraper job would add real throughput) or shared/broader across GitHub's IP pool (in which case a 3rd job wouldn't help and would waste runner minutes).

**How to run the test:** trigger it manually from the Actions tab while a scheduled prospection or retry run is already in progress.
**How to read it:** compare the two runs' logs for `RATE_LIMIT` lines.
- Independent timing (each hits its own limit on its own schedule) → quotas are separate → safe to add a 3rd standing job.
- Simultaneous / one run starves the other → quota is shared → don't add a 3rd job.

Not yet run as of Jul 14 2026 — do this before adding any permanent 3rd scraper job.

---

## Session notes
Full context is also stored in Google Drive:
`Real Estate > Plexes > Gesbrooke > Prospection > PROJECT_NOTES.md`
Drive folder ID: `10kUQg2czZQ9GBiw7WtCKs-3JVUewgMSX`
