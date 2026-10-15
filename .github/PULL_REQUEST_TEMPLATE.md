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
- [ ] Maintenance / outillage (`chore:`)
- [ ] Performance (`perf:`)
- [ ] Tests (`test:`)
- [ ] CI (`ci:`)
- [ ] Build / dépendances (`build:`)
- [ ] Annulation d'un commit (`revert:`)
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
  En cas de divergence avec le titre de la PR, ci-traceability émet un simple
  avertissement (le check n'échoue pas) ; la release calcule le bump depuis
  les commits de main (release.yml).
  Seuls feat, fix, perf et les breaking changes produisent une release.
-->

- [ ] **Patch** — `fix:` ou `perf:` (x.y.Z)
- [ ] **Minor** — `feat:`, nouvelle fonctionnalité rétrocompatible (x.Y.z)
- [ ] **Major** — breaking change, `<type>!:` (X.y.z)
- [ ] **Aucune release** — `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `revert:`

## Preuves

<!--
  Fournissez les sorties locales pour démontrer que le code est fonctionnel.
  Exemples : logs de tests, lint, gate de performance, captures d'écran si UI.
-->

```shell
# Tests
$ uv run pytest --cov --cov-report=term
...

# Lint
$ uv run ruff check .
...

# Gate de performance du modèle (si réentraînement)
$ uv run python -m app.training.score_validation
...
```

## Checklist

- [ ] Le titre de la PR suit la convention **Conventional Commits** (cohérent avec le type déclaré ci-dessus)
- [ ] La documentation (`CONTRIBUTING.md`, `README.md`, `docs/`) a été mise à jour si nécessaire
- [ ] Si le modèle a été réentraîné : `models/scores.json` est commité et la gate `ci-model-performance` passe (`uv run python -m app.training.score_validation`)
- [ ] Aucun secret, token ou information sensible n'est commité
- [ ] Si breaking change : un feature flag est en place ou la migration est documentée
- [ ] La procédure de rollback est décrite (commit revert, re-build, re-publish)

## Notes pour le reviewer

<!--
  Indiquez le périmètre de revue prioritaire, les points de risque,
  les fonctionnalités adjacentes impactées, etc.
-->

- Périmètre de revue :
- Points de risque :
- Dépendances / PR liées :