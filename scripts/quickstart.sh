#!/usr/bin/env bash
# Installe, lance et vérifie l'API de prédiction en une commande.
#
# Utilisateurs (image Docker publiée sur GHCR, aucun clone) :
#   curl -fsSL https://raw.githubusercontent.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning/main/scripts/quickstart.sh | bash
#   → crée ./p5-energy (docker-compose.yml + .env aux secrets aléatoires)
#
# Développeurs (depuis un clone, image construite depuis les sources) :
#   scripts/quickstart.sh --source
#
# Étapes : configuration → image (pull ou build) → base PostgreSQL (create_db)
# → ingestion des jeux 2016 et 2019 (téléchargés) → API → vérification (jeton,
# recherche de 3 bâtiments, prédiction). Relançable : .env et la base sont conservés.
#
# Variables :
#   P5_DIR       dossier d'installation (mode image)      défaut : p5-energy
#   P5_IMAGE     image de l'API                            défaut : …:latest (GHCR)
#   P5_REF       branche/tag des fichiers téléchargés      défaut : main
#   P5_RAW_BASE  source des fichiers (CI : file://…)       défaut : raw.githubusercontent.com
#   P5_PULL=0    ne pas tirer l'image (image locale, CI)
#   API_PORT / DB_PORT  ports hôte                         défaut : 8080 / 5432

# Tout est dans main() : avec `curl | bash`, bash lit le script sur stdin ; le
# corps est ainsi entièrement lu avant qu'une commande ne puisse consommer stdin.
main() {
  set -euo pipefail
  export LC_NUMERIC=C # printf %f : point décimal quelle que soit la locale

  local repo="WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning"
  local raw="${P5_RAW_BASE:-https://raw.githubusercontent.com/$repo/${P5_REF:-main}}"
  local api="http://localhost:${API_PORT:-8080}"
  local mode=image

  case "${1:-}" in
    --source) mode=source ;;
    "") ;;
    -h | --help) sed -n '2,21p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null | sed 's/^# \{0,1\}//'; return 0 ;;
    *) die "option inconnue : $1 (seule --source est acceptée)" ;;
  esac

  need docker
  need curl
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 requis (« docker compose »)"
  docker info >/dev/null 2>&1 || die "le démon Docker ne répond pas (démarré ? droits sur le socket ?)"

  step "Configuration ($mode)"
  if [ "$mode" = source ]; then
    [ -f docker-compose.override.yml ] || die "--source se lance depuis la racine d'un clone du dépôt"
    [ -f .env ] || cp .example.env .env
  else
    mkdir -p "${P5_DIR:-p5-energy}" && cd "${P5_DIR:-p5-energy}"
    curl -fsSL "$raw/docker-compose.yml" -o docker-compose.yml
    if [ ! -f .env ]; then
      curl -fsSL "$raw/.example.env" -o .env.example
      generate_env <.env.example >.env
      rm -f .env.example
    fi
  fi
  # Uid/gid de l'hôte pour le service tools (écriture dans ./data), si absents.
  grep -q '^UID=' .env || printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" >>.env
  # Créés par l'utilisateur, sinon Docker les crée au nom de root.
  mkdir -p data mlruns
  info "dossier : $PWD"

  step "Image de l'API"
  if [ "$mode" = source ]; then
    docker compose --profile tools build --pull
  elif [ "${P5_PULL:-1}" != 0 ]; then
    docker compose --profile tools pull --quiet
  fi

  step "Base de données"
  docker compose up -d --wait db
  docker compose run --rm -T tools python -m app.db.create_db

  # 2016 : jeu d'entraînement (features, split train/test). 2019 : open data de
  # Seattle ramenée au schéma 2016 ; ses nouveaux bâtiments n'ont jamais été vus
  # par l'entraînement, ce sont les seuls prédictibles par identifiant.
  local year
  for year in 2016 2019; do
    step "Ingestion du jeu $year (téléchargement, harmonisation, features)"
    docker compose run --rm -T tools python -m app.db.ingest --year "$year" \
      --csv "data/${year}_Building_Energy_Benchmarking.csv" --download
  done

  step "API"
  docker compose up -d --wait api

  step "Vérification"
  local token ids id res
  token=$(curl -fsS -X POST "$api/token" -d "username=johndoe&password=secret" \
    | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
  [ -n "$token" ] || die "jeton non obtenu"
  # 3 bâtiments jamais vus par l'entraînement, puis prédiction sur leur identifiant.
  ids=$(curl -fsS "$api/buildings?limit=3" -H "Authorization: Bearer $token" \
    | { grep -oE '"building_id":[0-9]+' || true; } | cut -d: -f2)
  [ -n "$ids" ] || die "aucun bâtiment consultable via /buildings"
  for id in $ids; do
    res=$(curl -fsS -X POST "$api/model/predict" -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" -d "{\"building_id\": $id}")
    printf '    bâtiment %-6s %14.0f kBtu/an  %8.1f t CO2e/an\n' "$id" \
      "$(field energy_use_kbtu "$res")" "$(field ghg_emissions_tco2e "$res")"
  done

  cat <<EOF

$(printf '\033[1;32m')✅ API prête sur $api$(printf '\033[0m')
   Documentation interactive : $api/docs
   Compte de démonstration   : johndoe / secret
   Arrêt                     : cd $PWD && docker compose down   (-v efface la base)
EOF
}

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 est requis"; }
field() { sed -E "s/.*\"$1\":([0-9.eE+-]+).*/\1/" <<<"$2"; } # nombre JSON, sans jq
rand() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }

# .example.env → .env : chaque secret de démonstration remplacé par une valeur
# aléatoire (les URL qui les réutilisent restent cohérentes).
generate_env() {
  local secret pg owner apipw mlflow
  secret=$(rand) pg=$(rand) owner=$(rand) apipw=$(rand) mlflow=$(rand)
  sed -e "s/ta_super_clef/$secret/" \
    -e "s/change-me-owner/$owner/g" \
    -e "s/change-me-api/$apipw/g" \
    -e "s/change-me-mlflow/$mlflow/g" \
    -e "s/change-me/$pg/g"
}

main "$@"
