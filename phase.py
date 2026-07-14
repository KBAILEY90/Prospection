#!/usr/bin/env python
# coding: utf-8
"""
phase.py — decide which script the scraper workflows should run.

Two-phase strategy (see CLAUDE.md "Two-phase scraping"):

  * Phase 1 "prospection" — new Zonage addresses still remain to be scraped.
    Both workflows run 2.Prospection.py on disjoint shards to burn through the
    remaining Zonage.csv addresses as fast as two GitHub runners allow.

  * Phase 2 "retry" — every Zonage address has been attempted (it is now in
    Liste_Prospection.csv OR Adresses_Inaccessibles.csv). New inaccessibles
    stop arriving, so both workflows switch to 3.Retry_Inaccessibles.py and
    drain the now-stationary inaccessibles pile down toward the target rate.

Prints exactly one word to stdout: "prospection" or "retry".
The decision mirrors 2.Prospection.py's own "done" logic, so the phase flips
to "retry" on the exact run where prospection would otherwise print
"Nothing left to process."
"""

import pandas as pd

ZONAGE_PATH       = "data/Zonage.csv"
LISTED_PATH       = "data/Liste_Prospection.csv"
INACCESSIBLE_PATH = "data/Adresses_Inaccessibles.csv"


def _addr_series(path):
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.Series(dtype=str)
    return df.get("ADRESSE", pd.Series(dtype=str))


def remaining_new_addresses() -> int:
    zonage = _addr_series(ZONAGE_PATH).dropna()
    done = set(
        pd.concat([_addr_series(LISTED_PATH), _addr_series(INACCESSIBLE_PATH)]).dropna()
    )
    return sum(1 for a in zonage if a not in done)


if __name__ == "__main__":
    print("prospection" if remaining_new_addresses() > 0 else "retry")
