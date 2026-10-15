#!/usr/bin/env bash
# Rejoue la section « Quickstart » du README dans un dossier vide.
#
# Convention : le README contient une section `## … Quickstart` avec un seul
# bloc ```bash qui, exécuté tel quel depuis un dossier vide d'une machine
# vierge, clone, installe, lance ET vérifie le projet. Ce script n'ajoute
# aucune commande : il extrait ce bloc et l'exécute en mode strict
# (`set -euo pipefail`) ; la moindre commande en échec fait échouer le test.
#
# Usage : scripts/quickstart_test.sh [README] [dossier de travail]
#   README             défaut : README.md à côté de ce script (../README.md)
#   dossier de travail défaut : dossier temporaire neuf
# Variables :
#   QUICKSTART_CLONE_FROM  dépôt local à cloner à la place de l'URL du README
#                          (CI : tester le code de la PR, pas celui de main)
#   QUICKSTART_KEEP=1      ne pas arrêter les conteneurs Docker Compose à la fin
set -euo pipefail

README="$(realpath "${1:-$(dirname "$0")/../README.md}")"
WORKDIR="${2:-$(mktemp -d)}"
mkdir -p "$WORKDIR"
WORKDIR="$(realpath "$WORKDIR")"

fail() { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# Premier bloc ```bash de la section dont le titre contient « Quickstart ».
# Les commentaires `# …` du bloc ne sont pas des titres : on ne cherche la fin
# de section qu'en dehors du bloc. Sortie 3 si le bloc n'est jamais refermé.
BLOCK="$(awk '
  inblock && /^```/   { closed = 1; exit }
  inblock             { print; next }
  /^#+ .*Quickstart/  { found = 1; next }
  found && /^#+ /     { exit }
  found && /^```bash/ { inblock = 1 }
  END { if (inblock && !closed) exit 3 }
' "$README")" || fail "bloc \`\`\`bash du Quickstart non refermé dans $README"
[ -n "$BLOCK" ] || fail "aucun bloc \`\`\`bash dans une section « Quickstart » de $README"

CLONE_URL="$(awk '$1 == "git" && $2 == "clone" { print $3; exit }' <<<"$BLOCK")"
[ -n "$CLONE_URL" ] || fail "le Quickstart doit commencer par « git clone <url> »"

# L'URL du README doit être publique et joignable, même si on clone une copie locale.
git ls-remote --exit-code "$CLONE_URL" HEAD >/dev/null 2>&1 \
  || fail "URL de clone injoignable (placeholder ou dépôt privé ?) : $CLONE_URL"

if [ -n "${QUICKSTART_CLONE_FROM:-}" ]; then
  # Redirige uniquement ce `git clone` vers la copie locale (config git isolée).
  export GIT_CONFIG_GLOBAL="$WORKDIR/.gitconfig-quickstart"
  git config --file "$GIT_CONFIG_GLOBAL" \
    "url.$(realpath "$QUICKSTART_CLONE_FROM").insteadOf" "$CLONE_URL"
fi

PROJECT_DIR="$WORKDIR/$(basename "$CLONE_URL" .git)"
cleanup() {
  if [ "${QUICKSTART_KEEP:-0}" != "1" ] && [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
    (cd "$PROJECT_DIR" && docker compose --profile '*' down -v --remove-orphans >/dev/null 2>&1) || true
  fi
}
trap cleanup EXIT

printf '\033[1;34m==> Quickstart de %s, exécuté dans %s\033[0m\n' "$README" "$WORKDIR"
cd "$WORKDIR"
bash -euxo pipefail -c "$BLOCK"
printf '\n\033[1;32m✅ Quickstart OK : le projet s'"'"'installe et fonctionne depuis un clone vierge.\033[0m\n'
