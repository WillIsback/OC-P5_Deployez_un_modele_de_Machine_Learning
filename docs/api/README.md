# ⚡ API de prédiction (CatBoost — Seattle)

L'API prédit la consommation d'énergie (`SiteEnergyUse(kBtu)`) et les émissions de GES (`TotalGHGEmissions`) d'un bâtiment non résidentiel de Seattle avec deux `CatBoostRegressor`, selon le pipeline du projet de référence [OC-Ai-Engineer-P3](https://github.com/WillIsback/OC-Ai-Engineer-P3) (cible transformée `log1p`, prédiction ramenée en unités réelles avec `expm1`).

La documentation interactive (Swagger / OpenAPI) est servie sur http://localhost:8080/docs. Toutes les routes ci-dessous exigent un jeton : voir [Authentification](authentication.md).

## Routes

| Méthode | Route | Rôle |
|---------|-------|------|
| `POST` | `/token` | Jeton JWT (formulaire `username` / `password`) |
| `GET` | `/buildings` | Recherche parmi les bâtiments **jamais vus par l'entraînement** |
| `GET` | `/buildings/{id}` | Identité et features par année d'un bâtiment |
| `POST` | `/model/predict` | Prédiction par `building_id` (features lues en base) |
| `POST` | `/model/predict/features` | Prédiction sur saisie libre des 17 features |
| `POST` | `/model/predict/compare` | CatBoost et Kumo-Tabular (zero-shot) côte à côte |
| `GET` | `/model/list` | Modèles enregistrés |
| `GET` | `/model/metrics` | Table de scores du dernier entraînement |

## Retrouver un bâtiment — `GET /buildings`

Seuls les bâtiments ni `train` ni `test` sont consultables et prédictibles par `building_id` : `/model/predict` et `/model/predict/compare` répondent 403 pour un bâtiment vu. Filtres : `q` (nom ou adresse), `year`, `neighborhood`, `building_type`, `limit` (100 au plus), `offset`. Aucune valeur réelle (consommation, émissions) n'est exposée.

```bash
curl "http://localhost:8080/buildings?q=needle&year=2018" -H "Authorization: Bearer <TOKEN>"
curl http://localhost:8080/buildings/1 -H "Authorization: Bearer <TOKEN>"
```

## Prédire — `POST /model/predict`

`data_year` est optionnel (par défaut l'année la plus récente disponible) :

```bash
curl -X POST http://localhost:8080/model/predict \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{"building_id": 1}'
```

La réponse contient `energy_use_kbtu` (kBtu/an), `ghg_emissions_tco2e` (t CO2e/an), `prediction_id` et `request_id` (aussi en en-tête `X-Request-ID`) pour retrouver la trace en base.

`POST /model/predict/compare` prend la même entrée et renvoie `catboost_prediction` et `kumo_prediction`, chacune au format de `/model/predict`, avec les mêmes codes d'erreur.

## Saisie libre — `POST /model/predict/features`

Pour un bâtiment absent de la base (simulation, test), envoyer directement les 17 features :

```bash
curl -X POST http://localhost:8080/model/predict/features \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{"BuildingType":"NonResidential","PrimaryPropertyType":"Small- and Mid-Sized Office","Neighborhood":"BALLARD","Latitude":47.62,"Longitude":-122.35,"YearBuilt":1990,"NumberofBuildings":1,"NumberofFloors":4,"PropertyGFAParking":5000,"PropertyGFABuilding":15000,"LargestPropertyUseType":"Office","SecondLargestPropertyUseType":"Retail Store","SecondLargestPropertyUseTypeGFA":3000,"ThirdLargestPropertyUseType":"Parking","ThirdLargestPropertyUseTypeGFA":2000,"Has_NaturalGas":true,"Has_Steam":false}'
```

Les valeurs catégorielles suivent la taxonomie de 2016 sur laquelle le modèle est entraîné. Pour des données plus récentes (jeu [Building Energy Benchmarking 2015-Present](https://data.seattle.gov/Built-Environment/Building-Energy-Benchmarking-Data-2015-Present/teqw-tu6e)), appliquer les correspondances de `app/db/harmonize.py`, détaillées dans [`docs/db/README.md`](../db/README.md) (« Harmonisation vers le schéma 2016 ») — ou ingérer ces années et prédire par `building_id`.

## Codes d'erreur

- **400** sur `POST /token` : identifiants incorrects ou compte inactif ;
- **401** : jeton absent, invalide ou expiré, ou utilisateur supprimé/désactivé depuis l'émission ;
- **403** : bâtiment déjà vu par l'entraînement (`train` ou `test`) ;
- **404** : bâtiment ou année inconnus ; `GET /model/metrics` sans `models/scores.json` ;
- **422** : bâtiment hors périmètre (ex. résidentiel), ou corps de requête invalide (champ inconnu refusé, `extra="forbid"`, ou valeur hors bornes, voir `app/schemas/api.py`) ;
- **503** : modèle indisponible (aucun modèle actif ou `.cbm` absent), base de données ou traçabilité indisponible (aucune prédiction n'est servie sans trace).

## Modèles servis

`models/energy.cbm` et `models/emissions.cbm` (version `baseline`, scores dans `models/scores.json`) sont **livrés dans l'image Docker** ; depuis un clone, `docker-compose.override.yml` monte `./models` par-dessus. Chemins surchargeables par `MODEL_PATH_ENERGY` / `MODEL_PATH_EMISSIONS`. `GET /model/metrics` renvoie les scores par cible puis par modèle (`R2`, `MAE`, `MedAE`, `MedAPE_pct`). Réentraînement : [`docs/training/README.md`](../training/README.md).
