#!/usr/bin/env bash
# Rejoue un parcours « Quickstart » du README dans un dossier vide.
#
# Convention : la section `## … Quickstart` du README contient deux sous-sections,
# `### … Utilisateurs` (image Docker) et `### … Développeurs` (code source),
# chacune avec un seul bloc ```bash qui, exécuté tel quel depuis un dossier vide
# d'une machine vierge, installe, lance ET vérifie le projet. Ce script n'ajoute
# aucune commande : il extrait le bloc et l'exécute en mode strict
# (`set -euo pipefail`) ; la moindre commande en échec fait échouer le test.
#
# Usage : scripts/quickstart_test.sh <user|dev> [README] [dossier de travail]
#   user               bloc « Utilisateurs » : `curl … | bash` (doit référencer raw.githubusercontent.com)
#   dev                bloc « Développeurs » : `git clone <url>` puis le script --source
#   README             défaut : README.md à côté de ce script (../README.md)
#   dossier de travail défaut : dossier temporaire neuf
# Variables :
#   QUICKSTART_CLONE_FROM  dépôt local utilisé à la place du dépôt GitHub
#                          (CI : tester le code de la PR, pas celui de main) :
#                          redirige le `git clone` (dev) ou les fichiers bruts (user)
#   QUICKSTART_KEEP=1      ne pas arrêter les conteneurs Docker Compose à la fin
#   P5_IMAGE / P5_PULL     transmis au script (user : image construite localement)
set -euo pipefail

MODE="${1:-}"
case "$MODE" in
  user) SECTION="Utilisateurs" ;;
  dev) SECTION="Développeurs" ;;
  *) echo "Usage : $0 <user|dev> [README] [dossier de travail]" >&2; exit 2 ;;
esac
README="$(realpath "${2:-$(dirname "$0")/../README.md}")"
WORKDIR="${3:-$(mktemp -d)}"
mkdir -p "$WORKDIR"
WORKDIR="$(realpath "$WORKDIR")"

fail() { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# Premier bloc ```bash de la sous-section dont le titre contient $SECTION, dans
# la section « Quickstart ». Les commentaires `# …` du bloc ne sont pas des
# titres : on ne cherche la fin de section qu'en dehors du bloc. Sortie 3 si le
# bloc n'est jamais refermé.
BLOCK="$(awk -v section="$SECTION" '
  inblock && /^```/                 { closed = 1; exit }
  inblock                           { print; next }
  /^## .*Quickstart/                { quick = 1; next }
  quick && /^## /                   { exit }
  quick && /^### / && index($0, section) { found = 1; next }
  found && /^#+ /                   { exit }
  found && /^```bash/               { inblock = 1 }
  END { if (inblock && !closed) exit 3 }
' "$README")" || fail "bloc \`\`\`bash « $SECTION » non refermé dans $README"
[ -n "$BLOCK" ] || fail "aucun bloc \`\`\`bash dans la sous-section « $SECTION » du Quickstart de $README"

if [ "$MODE" = dev ]; then
  CLONE_URL="$(grep -oE 'git clone [^ ]+' <<<"$BLOCK" | head -1 | cut -d' ' -f3)"
  [ -n "$CLONE_URL" ] || fail "le parcours développeur doit commencer par « git clone <url> »"
  # L'URL du README doit être publique et joignable, même si on clone une copie locale.
  git ls-remote --exit-code "$CLONE_URL" HEAD >/dev/null 2>&1 \
    || fail "URL de clone injoignable (placeholder ou dépôt privé ?) : $CLONE_URL"
  if [ -n "${QUICKSTART_CLONE_FROM:-}" ]; then
    # Redirige uniquement ce `git clone` vers la copie locale (config git isolée).
    export GIT_CONFIG_GLOBAL="$WORKDIR/.gitconfig-quickstart"
    git config --file "$GIT_CONFIG_GLOBAL" \
      "url.$(realpath "$QUICKSTART_CLONE_FROM").insteadOf" "$CLONE_URL"
  fi
else
  SCRIPT_URL="$(grep -oE 'https://raw\.githubusercontent\.com/[^ ]+' <<<"$BLOCK" | head -1)"
  [ -n "$SCRIPT_URL" ] || fail "le parcours utilisateur doit télécharger le script depuis raw.githubusercontent.com"
  RAW_BASE="$(sed -E 's#(https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+)/.*#\1#' <<<"$SCRIPT_URL")"
  if [ -z "${QUICKSTART_CLONE_FROM:-}" ]; then
    curl -fsSI "$SCRIPT_URL" >/dev/null || fail "script injoignable : $SCRIPT_URL"
  else
    # Copie locale (CI d'une PR : le script peut ne pas encore exister sur main) :
    # on vérifie seulement que le dépôt et la branche de l'URL sont publics.
    curl -fsSI "$RAW_BASE/README.md" >/dev/null || fail "dépôt/branche injoignable : $RAW_BASE"
    # https://raw.githubusercontent.com/<owner>/<repo>/<ref> → file://<copie locale>,
    # pour le script comme pour les fichiers qu'il télécharge (P5_RAW_BASE).
    P5_RAW_BASE="file://$(realpath "$QUICKSTART_CLONE_FROM")"
    export P5_RAW_BASE
    BLOCK="${BLOCK//"$RAW_BASE"/"$P5_RAW_BASE"}"
  fi
fi

cleanup() {
  [ "${QUICKSTART_KEEP:-0}" = "1" ] && return
  local compose
  compose="$(find "$WORKDIR" -maxdepth 2 -name docker-compose.yml -print -quit)"
  [ -n "$compose" ] || return 0
  (cd "$(dirname "$compose")" && docker compose --profile '*' down -v --remove-orphans >/dev/null 2>&1) || true
}
trap cleanup EXIT

printf '\033[1;34m==> Quickstart « %s » de %s, exécuté dans %s\033[0m\n' "$SECTION" "$README" "$WORKDIR"
cd "$WORKDIR"
bash -euxo pipefail -c "$BLOCK"
printf '\n\033[1;32m✅ Quickstart « %s » OK : le projet s'"'"'installe et fonctionne depuis un dossier vierge.\033[0m\n' "$SECTION"
