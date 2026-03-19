# Prospection – Bug Analysis & Fix

## Summary

Almost all addresses are landing in `Adresses_Inaccessibles.csv` due to **one primary bug** in `2.Prospection.py`. A secondary bug affects a smaller subset. Both are documented and fixed below.

---

## Bug #1 — PRIMARY (affects every single address)

### What's wrong

The XPath used to extract the inscription date is:

```python
# ORIGINAL (broken):
inscriptionDate = get_cell('//tr[td[text()="Date d\'inscription au rôle:"]]/td[2]')
```

The apostrophe in the Python string is **U+0027** (straight apostrophe).
But the Sherbrooke evaluation website renders the label with **U+2019** (curled right single quotation mark).

**Verified with JavaScript in the browser:**
- Straight apostrophe XPath match: NOT FOUND
- Curled apostrophe XPath match: 2014-10-01 ✓

Because the XPath never matches, `wait.until()` times out after **5 seconds on every address**. The TimeoutException goes to the except block, and the address is logged to `Adresses_Inaccessibles.csv`. This happens 100% of the time.

### The fix

```python
# FIXED - use contains() to avoid apostrophe type sensitivity:
inscriptionDate = get_cell('//tr[td[contains(text(),"inscription au r")]]/td[2]')
```

---

## Bug #2 — SECONDARY (affects vacant lots)

### What's wrong

Properties without a building (vacant land in habitation zones) lack "Année de construction:" and "Nombre de logements:" rows on the evaluation page. The required get_cell() call times out after 5s and logs the address as inaccessible.

### The fix

Use an optional_cell() helper that returns empty string instead of raising:

```python
def optional_cell(xpath, timeout=3):
    try:
        el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        return WebDriverWait(driver, timeout).until(EC.visibility_of(el)).text.strip()
    except Exception:
        return ''

constructionDate = optional_cell('//tr[td[text()="Année de construction:"]]/td[2]')
units            = optional_cell('//tr[td[text()="Nombre de logements:"]]/td[2]')
```

---

## Bug #3 — MINOR (column name inconsistency)

### What's wrong

`1.Zoning.py` creates the column as `GMAPS_URL` but `2.Prospection.py` accesses `row['GOOGLE_MAPS']`. If 1.Zoning.py is re-run, 2.Prospection.py crashes with a KeyError on the first address.

### The fix

In `1.Zoning.py`, rename the column:
```python
joined_df["GOOGLE_MAPS"] = joined_df.apply(...)   # was GMAPS_URL
```

---

## What to expect after the fix

- **Bug #1 fixed**: The vast majority of previously-failed addresses will now be scraped successfully.
- **Bug #2 fixed**: Vacant lots will be saved with blank fields instead of failing.
- **Bug #3 fixed**: Re-running 1.Zoning.py won't break 2.Prospection.py.

**Important**: Before re-running, clear or rename `data/Adresses_Inaccessibles.csv` so those addresses are retried. They were not truly inaccessible — they all hit the apostrophe timeout.

The fixed code is in `analysis/2.Prospection_fixed.py`.
