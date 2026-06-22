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

Current benchmark (Jun 19, 2026): ~12.2% — target is ≤10%.

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

---

## How the scripts work

- **Prospection** builds a `done` set from both CSVs at startup — never re-searches an address
- **Retry** on success: appends rescued row to `Liste_Prospection.csv` AND removes it from `Adresses_Inaccessibles.csv`
- **Rate limit**: city website resets hourly ("Limite de consultations") — retry sleeps until next UTC hour + 120s

---

## Bugs already fixed — do not revert

1. **Force-push bug** (`2.Prospection.py`): old code was `git push || git push --force` — silently overwrote retry commits. Fixed to `git pull --rebase && git push || echo 'Push failed'`
2. **Retry commit_changes**: replaced fragile multi-line push block with rebase-abort-on-failure pattern

---

## Why the rate is stuck at ~12%
New addresses arrive at ~12–15% inaccessible (rate limiting hits mid-run), creating a floor. The retry script must rescue faster than prospection adds new inaccessibles. Possible lever: reduce addresses processed per prospection run to give retry breathing room.

---

## Progress history

| Date     | Inaccessible | Total Processed | Rate  |
|----------|-------------|-----------------|-------|
| Apr 12   | 1,142       | ~6,662          | 17.1% |
| Apr 26   | 2,464       | ~19,808         | 12.4% |
| May 4    | 2,659       | ~21,393         | 12.4% |
| May 23   | 3,223       | ~26,721         | 12.1% |
| Jun 19   | ~3,275      | ~26,794         | 12.2% |

Processing pace: ~490 addresses/day. Est. ~43k addresses remain → ~late August 2026 to finish Zonage.csv.

---

## Session notes
Full context is also stored in Google Drive:
`Real Estate > Plexes > Gesbrooke > Prospection > PROJECT_NOTES.md`
Drive folder ID: `10kUQg2czZQ9GBiw7WtCKs-3JVUewgMSX`
