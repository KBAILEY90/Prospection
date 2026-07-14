# Prospection — Claude Code Instructions

## What this project is
Automated scraper that looks up zoning info and owner names for Quebec addresses from `data/Zonage.csv`. Two GitHub Actions workflows run continuously:
- `main.yml` — hourly (:00), **shard 0**
- `retry.yml` — every 2 hours (:30), **shard 1**

Both workflows are **phase-aware** (see *Two-phase scraping* below): each run first calls `phase.py`, then runs *either* `2.Prospection.py` (finish new addresses) *or* `3.Retry_Inaccessibles.py` (drain inaccessibles) depending on whether any Zonage address is still un-attempted.

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

Current benchmark (Jul 12, 2026): ~14.2% — target is ≤10%. The rate is *expected* to rise during Phase 1 (both runners push new addresses through, so inaccessibles pile up faster than they are rescued) and then fall in Phase 2. Judge success by the *final* rate once Zonage is exhausted, not the intermediate.

---

## Key files

| File | Purpose |
|------|---------|
| `2.Prospection.py` | Main scraper — runs hourly via GitHub Actions |
| `3.Retry_Inaccessibles.py` | Retries inaccessibles — runs every 2h |
| `data/Zonage.csv` | Source address list (~70k total addresses) |
| `data/Liste_Prospection.csv` | Successfully scraped addresses |
| `data/Adresses_Inaccessibles.csv` | Addresses that hit rate limit |
| `phase.py` | Decides `prospection` vs `retry` for a run; both workflows call it first |
| `.github/workflows/main.yml` | Hourly workflow, shard 0 (phase-aware) |
| `.github/workflows/retry.yml` | 2-hourly workflow, shard 1 (phase-aware) |

---

## How the scripts work

- **Prospection** builds a `done` set from both CSVs at startup — never re-searches an address
- **Retry** on success: appends rescued row to `Liste_Prospection.csv`; the rescued row is later removed from `Adresses_Inaccessibles.csv` by the **reconcile** step (see below)
- **Rate limit**: city website resets hourly ("Limite de consultations") — scripts sleep until next UTC hour + 120s. The limit is **per IP**; each workflow runs on its own GitHub runner (own IP), so the two shards have **independent** hourly budgets and do not compete.
- **Sharding** (`SHARD_INDEX` / `SHARD_COUNT` env vars, default `0`/`1` = single-runner): each runner takes a disjoint modulo slice of the work so the two shards never scrape the same address.

### Write-safety model (important — parallel runners share the CSVs)
- Commits use **union merge** (`git pull --no-rebase -s recursive -X union && git push`), never force-push. Union merges concurrent **appends** cleanly.
- Both scripts only **append** to `Liste_Prospection.csv`, with an in-memory duplicate guard.
- `Adresses_Inaccessibles.csv` is **appended** by prospection but only **rewritten** by the retry **reconcile** step, which runs on **shard 0 only**. Single-writer + union-merge means removed rows are never resurrected (union would resurrect deletions if two runners rewrote it concurrently — hence the single-writer rule).
- Retry skips any address already in `Liste_Prospection.csv`, so rows rescued by the other shard are never re-scraped before reconcile catches up.

---

## Bugs already fixed — do not revert

1. **Force-push bug**: old code was `git push || git push --force` — silently overwrote the other workflow's commits. Both `2.Prospection.py`'s in-script `commit_changes` and the retry commit now use `git pull --no-rebase -s recursive -X union && git push || echo 'Push failed'`. **Never** reintroduce any `--force` / `--force-with-lease` fallback — with two parallel shards it silently drops the other shard's work.
2. **Union merge, not rebase**, in retry's `commit_changes`: required so two shards appending to `Liste_Prospection.csv` don't clobber each other. (An earlier plain `--rebase` was fine for a single runner but conflicts under parallel appends.)
3. **Single-writer reconcile**: only shard 0 rewrites `Adresses_Inaccessibles.csv`. Do not let shard 1 (or a parallel retry) rewrite it — union merge resurrects deletions, so concurrent rewrites lose rescues.
4. **Listed dedup guard** (`2.Prospection.py` `safe_write_listed`): skips an address already written, so parallel shards / re-queued addresses can't create duplicate rows.

---

## Two-phase scraping
The two runners have **independent** per-IP rate-limit budgets, so we use both in each phase instead of splitting effort:

- **Phase 1 — finish new addresses.** While any Zonage address is un-attempted, `phase.py` returns `prospection` and **both** workflows run `2.Prospection.py` on disjoint shards (shard 0 = main, shard 1 = retry). This burns through the remaining Zonage list at ~2× speed. The inaccessibles pile *grows* during this phase — that's expected and recoverable; those rows are rate-limit casualties, not real failures.
- **Phase 2 — drain inaccessibles.** Once every Zonage address is in `Liste_Prospection.csv` ∪ `Adresses_Inaccessibles.csv`, `phase.py` returns `retry` and **both** workflows run `3.Retry_Inaccessibles.py` on disjoint shards against the now-**stationary** pile. Stopping the inflow of new inaccessibles is what lets retry finally catch up and pull the rate below 10%.

The phase flip is automatic and needs no manual switch: `phase.py` mirrors prospection's own `done` logic, so it returns `retry` exactly when prospection would otherwise print "Nothing left to process."

**Target math:** at the full Zonage (~55,575 addresses), ≤10% means getting inaccessibles down to **~5,557**. Phase 2's job is to drain the pile below that.

### Why the earlier single-lever approach stalled at ~12%
Before two-phase, prospection (both new addresses) and retry (rescues) ran at the same time, and retry — running every 2h and sleeping ~an hour each time it hit the limit — couldn't rescue faster than prospection added new inaccessibles. The pile was a **moving target**. Two-phase fixes this by stopping the inflow (finish Phase 1) before draining (Phase 2).

---

## Progress history

| Date     | Inaccessible | Total Processed | Rate  |
|----------|-------------|-----------------|-------|
| Apr 12   | 1,142       | ~6,662          | 17.1% |
| Apr 26   | 2,464       | ~19,808         | 12.4% |
| May 4    | 2,659       | ~21,393         | 12.4% |
| May 23   | 3,223       | ~26,721         | 12.1% |
| Jun 19   | ~3,275      | ~26,794         | 12.2% |
| Jul 12   | 6,445       | 45,282          | 14.2% |

Processing pace jumped to ~800 addresses/day by Jul 12. As of Jul 12, ~10,293 new addresses remain (Zonage has ~55,575 rows). **Two-phase scraping** went live Jul 12: with both runners on new addresses, Phase 1 should finish in ~6–7 days, after which Phase 2 drains the inaccessibles pile.

---

## Session notes
Full context is also stored in Google Drive:
`Real Estate > Plexes > Gesbrooke > Prospection > PROJECT_NOTES.md`
Drive folder ID: `10kUQg2czZQ9GBiw7WtCKs-3JVUewgMSX`
