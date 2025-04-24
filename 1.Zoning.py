#!/usr/bin/env python
# coding: utf-8

# In[6]:


import geopandas as gpd
from urllib.parse import quote_plus

def generate_google_maps_url(address, city):
    base_url = "https://www.google.com/maps/search/?api=1&query="
    return base_url + quote_plus(f"{address} {city}")


# In[7]:


# Load GeoJSON datasets
adresses = gpd.read_file("Adresses.geojson")
zonage = gpd.read_file("Zonage.geojson")
arrondissements = gpd.read_file("Arrondissements.geojson")

# Ensure all datasets use the same CRS
adresses = adresses.to_crs(epsg=4326)
zonage = zonage.to_crs(epsg=4326)
arrondissements = arrondissements.to_crs(epsg=4326)

zonage_habitation = zonage.loc[
    (zonage['NO_ZONE'].str[:1] == 'H') | (zonage['NO_ZONE'].str[:2] == 'HZ')
]

# Perform spatial join to match addresses within zoning polygons
joined_zonage = gpd.sjoin(adresses, zonage_habitation, predicate="within", how="inner")
joined_zonage = joined_zonage.drop(columns=["index_right"], errors="ignore")

# Perform spatial join to match addresses within boroughs
joined = gpd.sjoin(joined_zonage, arrondissements, predicate="within", how="left")
joined["RUE"] = joined["TYPE_VOIE"]+" "+joined["NOM_VOIE"]

# Select relevant columns to export
joined_df = joined[[
    "ADRESSE",
    "RUE",
    "NO_ZONE",
    "GRILLEUSAGE",
    "NOM"]].rename(columns={"NOM": "ARRONDISSEMENT"})

joined_df["GMAPS_URL"] = joined_df.apply(
    lambda row: generate_google_maps_url(row["ADRESSE"], row["ARRONDISSEMENT"]), axis=1
)

joined_df.to_csv('Zonage.csv', index=False, encoding='utf-8-sig')

