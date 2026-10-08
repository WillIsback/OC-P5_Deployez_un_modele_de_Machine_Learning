<!--
  Template de Pull Request — Projet P5
  Règles R1/R3/R6/R7 appliquées.
-->

# Pull Request

## Type de changement

<!-- Cochez la ou les cases correspondantes -->

- [ ] Bug fix (`fix:`)
- [ ] Nouvelle fonctionnalité (`feat:`)
- [ ] Refactoring (`refactor:`)
- [ ] Documentation (`docs:`)
- [ ] Maintenance / CI / outillage (`chore:`)
- [ ] **BREAKING CHANGE** (`<type>!:`) — cocher si le changement casse la rétrocompatibilité

## Issues liées

<!--
  R1 / R3 : Au moins une référence d'issue est obligatoire.
  Utilisez "Closes #..." ou "Related to #..." (une par ligne).
-->

- Related to #
- Closes #

## Impact semver attendu

<!--
  Déclaration d'impact sur la version (sert de garde-fou croisé §9.2).
  En cas de divergence avec l'analyse des commits, le check CI échoue.
-->

- [ ] **Patch** — correction, refactoring, doc, chore (x.y.Z)
- [ ] **Minor** — nouvelle fonctionnalité rétrocompatible (x.Y.z)
- [ ] **Major** — breaking change (X.y.z)

## Preuves

<!--
  Fournissez les sorties locales pour démontrer que le code est fonctionnel.
  Exemples : logs de tests, lint, scan, dry-run release, captures d'écran si UI.
-->

```shell
# Tests
$ uv run pytest --cov --cov-report=term
...

# Lint
$ uv run ruff check .
...

# Dry-run release (si applicable)
$ uv run release --dry-run
...
```

## Checklist

- [ ] Le titre de la PR suit la convention **Conventional Commits** (cohérent avec le type déclaré ci-dessus)
- [ ] La documentation (`CONTRIBUTING.md`, `README.md`, `docs/`) a été mise à jour si nécessaire
- [ ] Le fichier `CHANGELOG.md` ou les release notes ont été préparés
- [ ] Aucun secret, token ou information sensible n'est commité
- [ ] Si breaking change : un feature flag est en place ou la migration est documentée
- [ ] La procédure de rollback est décrite (commet revert, re-build, re-publish)

## Notes pour le reviewer

<!--
  Indiquez le périmètre de revue prioritaire, les points de risque,
  les fonctionnalités adjacentes impactées, etc.
-->

- Périmètre de revue :
- Points de risque :
- Dépendances / PR liées :