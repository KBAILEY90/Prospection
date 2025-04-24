#!/usr/bin/env python
# coding: utf-8

# In[35]:


import geopandas as gpd
import pandas as pd
from urllib.parse import quote_plus
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import os
import csv  
import time
import sys
import papermill as pm

folderPath = "G:\\My Drive\\Real Estate\\Plexes\\Gesbrooke\\Prospection\\"
city = "SHERBROOKE"


# In[36]:


def get_cell(xpath):
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    driver.execute_script("arguments[0].scrollIntoView(true);", el)
    return wait.until(EC.visibility_of(el)).text.strip()


# In[39]:


# Uncomment if 1.Zonage needs to be refreshed
#pm.execute_notebook('1.Zoning.ipynb', '1.Zoning.output.ipynb')
joined_df = pd.read_csv('Zonage.csv', encoding='utf-8-sig')


# In[ ]:


############## PREPARE ##############
columns = [
    "ADRESSE",
    "RUE",
    "NB_LOGEMENTS",
    "DATE_CONSTRUCTION",
    "NO_ZONE",
    "GRILLEUSAGE",
    "ARRONDISSEMENT",
    "NOM_PROPRIETAIRE",
    "ADRESSE_PROPRIETAIRE",
    "DATE_INSCRIPTION",
    "URL",
    "GOOGLE_MAPS"
]

errorLogColumns = joined_df.columns

# Load inaccessible addresses
inaccessible_path = f"{folderPath}Adresses Inaccessibles.csv"
if os.path.exists(inaccessible_path):
    inaccessible_df = pd.read_csv(inaccessible_path, encoding='ISO-8859-1')
else:
    with open(inaccessible_path, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(errorLogColumns)
    inaccessible_df = pd.read_csv(inaccessible_path, encoding='ISO-8859-1')

# Initialize empty series for filters if files are missing
listed_addresses = pd.Series(dtype=str)
inaccessible_addresses = pd.Series(dtype=str)

# Load listed addresses
listed_path = f"{folderPath}Liste Prospection.csv"
if os.path.exists(listed_path):
    listed_df = pd.read_csv(listed_path, encoding='ISO-8859-1')
    listed_addresses = listed_df["ADRESSE"]

# Load inaccessible addresses
if "ADRESSE" in inaccessible_df.columns:
    inaccessible_addresses = inaccessible_df["ADRESSE"]

# Exclude addresses in either listed or inaccessible
excluded_addresses = pd.concat([listed_addresses, inaccessible_addresses]).dropna().unique()
todo_addresses = joined_df[~joined_df["ADRESSE"].isin(excluded_addresses)]["ADRESSE"]

    

########### START SESSION ###########
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
wait = WebDriverWait(driver, 5)

# Go to the site
driver.get("https://espace-evaluation.sherbrooke.ca/consultation-du-role/recherche")



for a in todo_addresses:
    
    time.sleep(1)
    row = joined_df.loc[joined_df['ADRESSE'] == a].iloc[0]

    try:
        ############### INPUT ###############
        inputs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'input[placeholder="Adresse..."]')))
        visible_inputs = [el for el in inputs if el.is_displayed() and el.is_enabled()]
        search_input = visible_inputs[0]  
        search_input.clear()  # Ensure input is cleared  
        search_input.click()
        search_input.send_keys(a)
        time.sleep(0.3)
    
        suggestion = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'mat-option.mat-mdc-option')))
        suggestion.click()
            
    
        ############### SCRAPE ###############
        ownerName = get_cell('//tr[td[text()="Nom:"]]/td[2]')
        ownerAddress = get_cell('//tr[td[text()="Adresse Postale:"]]/td[2]')
        inscriptionDate = get_cell('//tr[td[text()="Date d’inscription au rôle:"]]/td[2]')
        constructionDate = get_cell('//tr[td[text()="Année de construction:"]]/td[2]')
        units = get_cell('//tr[td[text()="Nombre de logements:"]]/td[2]')
    
        url = driver.current_url
    
        
        ############ POPULATE CSV ###########

        fields = [
            a,
            row['RUE'],
            units,
            constructionDate,
            row['NO_ZONE'],
            row['GRILLEUSAGE'],
            ownerName,
            ownerAddress,
            inscriptionDate,
            url,
            row['GOOGLE_MAPS']
        ]

    
        with open(f"{folderPath}Liste Prospection.csv", 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(fields)

        
        new_search = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'ion-icon.icon-search')))
        new_search.click()


    except Exception as e:
        # Hourly limit pop-up appeared
        if "element click intercepted" in str(e):
            print("Hourly limit reached. Closing driver.")
            # Remove last error from csv since this fail happens after two errors. It saves the first in the file, but shouldn't.
            temp_df = pd.read_csv(f"{folderPath}Adresses Inaccessibles.csv")
            temp_df = temp_df.iloc[:-1]
            temp_df.to_csv(f"{folderPath}Adresses Inaccessibles.csv", index=False)  
            driver.quit()
            sys.exit()

        else:
            print(f"Failed to process address {a}: {str(e)}")
            # If not present in error log, add it. But if the error is because the screen closed, then don't
            if len(inaccessible_df[inaccessible_df['ADRESSE']==a]) == 0 and "invalid session id" not in str(e):
                with open(f"{folderPath}Adresses Inaccessibles.csv", 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
            continue  # Skip to next address if any error occurs



driver.quit()


# In[ ]:




