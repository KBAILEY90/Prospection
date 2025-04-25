#!/usr/bin/env python
# coding: utf-8

# In[42]:


import csv
import os
import sys
import time
import pandas as pd
import papermill as pm
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

city = "SHERBROOKE"
inaccessible_path = "data/Adresses Inaccessibles.csv"
listed_path = "data/Liste Prospection.csv"
zonage_path = "data/Zonage.csv"


# In[43]:


# Create screenshot directory if needed
os.makedirs("errors", exist_ok=True)

def get_cell(xpath):
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    driver.execute_script("arguments[0].scrollIntoView(true);", el)
    return wait.until(EC.visibility_of(el)).text.strip()


# In[44]:


# Uncomment if 1.Zonage needs to be refreshed
#pm.execute_notebook('1.Zoning.ipynb', '1.Zoning.output.ipynb')
joined_df = pd.read_csv(zonage_path, encoding='utf-8-sig')


# In[45]:


columns = [
    "ADRESSE", "RUE", "NB_LOGEMENTS", "DATE_CONSTRUCTION", "NO_ZONE", "GRILLEUSAGE",
    "ARRONDISSEMENT", "NOM_PROPRIETAIRE", "ADRESSE_PROPRIETAIRE", "DATE_INSCRIPTION",
    "URL", "GOOGLE_MAPS"
]

errorLogColumns = joined_df.columns

if os.path.exists(inaccessible_path):
    inaccessible_df = pd.read_csv(inaccessible_path, encoding='utf-8-sig')
else:
    with open(inaccessible_path, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(errorLogColumns)
    inaccessible_df = pd.read_csv(inaccessible_path, encoding='utf-8-sig')

listed_addresses = pd.Series(dtype=str)
inaccessible_addresses = pd.Series(dtype=str)

if os.path.exists(listed_path):
    listed_df = pd.read_csv(listed_path, encoding='utf-8-sig')
    listed_addresses = listed_df["ADRESSE"]
else:
    with open(listed_path, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
    listed_df = pd.read_csv(listed_path, encoding='utf-8-sig')
    listed_addresses = pd.Series(dtype=str)

if "ADRESSE" in inaccessible_df.columns:
    inaccessible_addresses = inaccessible_df["ADRESSE"]

excluded_addresses = pd.concat([listed_addresses, inaccessible_addresses]).dropna().unique()
todo_addresses = joined_df[~joined_df["ADRESSE"].isin(excluded_addresses)]["ADRESSE"]

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
wait = WebDriverWait(driver, 5)

driver.get("https://espace-evaluation.sherbrooke.ca/consultation-du-role/recherche")

for a in todo_addresses:
    time.sleep(1)
    row = joined_df.loc[joined_df['ADRESSE'] == a].iloc[0]

    try:
        inputs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'input[placeholder="Adresse..."]')))
        visible_inputs = [el for el in inputs if el.is_displayed() and el.is_enabled()]
        search_input = visible_inputs[0]
        driver.execute_script("arguments[0].scrollIntoView(true);", search_input)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[placeholder="Adresse..."]')))
        search_input.clear()
        search_input.click()
        search_input.send_keys(a)
        time.sleep(0.3)

        suggestion = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'mat-option.mat-mdc-option')))
        suggestion.click()

        ownerName = get_cell('//tr[td[text()="Nom:"]]/td[2]')
        ownerAddress = get_cell('//tr[td[text()="Adresse Postale:"]]/td[2]')
        inscriptionDate = get_cell('//tr[td[text()="Date d’inscription au rôle:"]]/td[2]')
        constructionDate = get_cell('//tr[td[text()="Année de construction:"]]/td[2]')
        units = get_cell('//tr[td[text()="Nombre de logements:"]]/td[2]')
        url = driver.current_url

        fields = [
            a, row['RUE'], units, constructionDate, row['NO_ZONE'], row['GRILLEUSAGE'],
            ownerName, ownerAddress, inscriptionDate, url, row['GOOGLE_MAPS']
        ]

        with open(listed_path, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(fields)

        new_search = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'ion-icon.icon-search')))
        new_search.click()

    except Exception as e:
        driver.save_screenshot(f"errors/{a.replace(' ', '_')}.png")

        if "element click intercepted" in str(e):
            try:
                temp_df = pd.read_csv(inaccessible_path, encoding='utf-8-sig')
                temp_df = temp_df.iloc[:-1]
                temp_df.to_csv(inaccessible_path, index=False, encoding='utf-8-sig')
            except Exception as csv_err:
                print(f"CSV trimming failed: {csv_err}")
            print("Hourly limit reached. Closing driver.")
            driver.quit()
            break

        elif "invalid session id" in str(e) or "target window already closed" in str(e):
            print("Driver was closed manually. Terminating script.")
            driver.quit()
            break

        else:
            print(f"Failed to process address {a}: {str(e)}")
            if len(inaccessible_df[inaccessible_df['ADRESSE'] == a]) == 0:
                try:
                    with open(inaccessible_path, 'a', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(row)
                except Exception as log_err:
                    print(f"Failed to log inaccessible address: {log_err}")
            continue

driver.quit()

