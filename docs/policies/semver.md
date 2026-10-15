# Politique de version sémantique

## 📏 Principe

Ce projet suit le [Semantic Versioning 2.0.0](https://semver.org) adapté aux commits conventionnels.

## 🔄 Cycle de version

La version est **dérivée des tags Git** (Q3). Aucun fichier de version n'est modifié par le workflow de release.  
La version source de vérité est le tag `vX.Y.Z`.

## 📊 Composition

```
v <majeur> . <mineur> . <patch>
```

| Incrément | Déclencheur |
|-----------|-------------|
| **Majeure (X)** | Breaking change marqué par `!` dans le sujet (`feat!:`, `fix(api)!:`, …) |
| **Mineure (Y)** | Nouvelle fonctionnalité (`feat:`) rétrocompatible |
| **Patch (Z)** | Correction (`fix:`) ou performance (`perf:`) rétrocompatible |

> ⚠️ Le job `detect` ne lit que le **sujet** des commits (`git log --format=%s`). Un pied de page `BREAKING CHANGE:` dans le corps du commit n'est **pas** détecté : seul `type!:` déclenche une majeure.

## 🚫 Types sans release

Les commits qui ne modifient pas le comportement publié **ne déclenchent aucune release** :

`docs:`, `chore:`, `ci:`, `build:`, `test:`, `refactor:`, `revert:`

> `style:` n'est pas un type accepté : la regex du titre de PR (`ci-code-quality`) et la liste de `ci-traceability` le refusent.

Si aucun commit éligible (`feat:`, `fix:`, `perf:` ou breaking change) n'est présent depuis le dernier tag,
le job `detect` renvoie `version=skipped` et l'ensemble des gates CD et de la publication sont ignorés.


## ⚠️ Comportement `v0.x`

Aucune règle spécifique n'est appliquée en `v0.x` : un breaking change (`type!:`) incrémente la majeure même quand elle vaut `0` (c'est ainsi que `v0.3.0` est passé à `v1.0.0`). La règle Q2 envisagée (« une mineure est cassante en `v0.x` ») n'est pas implémentée.

## 🏷️ Format de tag

Obligatoire : `v<major>.<minor>.<patch>` (préfixe `v` obligatoire).

Valide : `v1.2.3`, `v0.1.0`, `v10.0.0`  
Invalide : `1.2.3`, `v1.2`, `release-1.2.3`

## 🔀 Règle du max (Q7)

Lorsqu'une PR contient des commits de types multiples, le bump le plus élevé est retenu :

| Combinaison | Bump résultant |
|-------------|---------------|
| `fix:` + `feat:` | **mineure** |
| `feat:` + `feat!:` | **majeure** |
| `docs:` + `fix:` | **patch** |
| `docs:` + `chore:` | aucune release (`version=skipped`) |

Le check `ci-traceability` affiche un avertissement (non bloquant) si le bump coché dans la PR diffère du bump qu'il infère **du titre de la PR** : `major` si le titre contient `!` ou `BREAKING CHANGE`, `minor` s'il commence par `feat`, sinon `patch` — y compris pour `docs:`, `chore:`, etc., qui ne déclenchent pourtant aucune release. Ce bump inféré n'est qu'indicatif : seule l'analyse des commits par `detect` fait foi.

## 🔒 Protection

Les tags sont protégés par un Tag Ruleset : la **modification et la suppression sont bloquées**
(la création reste autorisée pour permettre au workflow de release de publier `vX.Y.Z`).  
Cela garantit :

- Traçabilité : chaque tag correspond à un run de release
- Immuabilité : pas de re-tag ou de modification d'un tag publié
- Pas d'atomicité : le tag est poussé (`git push`) **avant** la création de la GitHub Release, dans deux étapes distinctes du job `publish`. Si la création de la release ou de l'image échoue, le tag reste en place : un nouveau run ne voit plus de commit depuis ce tag et renvoie `version=skipped`. La reprise passe par « Re-run failed jobs » sur le run en échec (voir [runbook de release](../release/README.md))

## 📋 CHANGELOG

- Généré par le workflow `release.yml` depuis le dernier tag : simple liste `git log --format="* %s"` des sujets de commits, **non groupée** par type
- Utilisé uniquement comme notes de la GitHub Release : aucun fichier `CHANGELOG.md` n'est écrit ni commité
- Les numéros de PR/issues apparaissent seulement s'ils figurent dans le sujet des commits (ex. `(#27)` ajouté par le squash merge)