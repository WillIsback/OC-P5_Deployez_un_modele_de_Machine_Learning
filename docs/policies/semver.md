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
| **Majeure (X)** | Breaking change (`!`, `BREAKING CHANGE:`) |
| **Mineure (Y)** | Nouvelle fonctionnalité (`feat:`) rétrocompatible |
| **Patch (Z)** | Correction (`fix:`) ou performance (`perf:`) rétrocompatible |

## 🚫 Types sans release

Les commits qui ne modifient pas le comportement publié **ne déclenchent aucune release** :

`docs:`, `chore:`, `ci:`, `build:`, `test:`, `style:`, `refactor:`

Si aucun commit éligible (`feat:`, `fix:`, `perf:` ou breaking change) n'est présent depuis le dernier tag,
le job `detect` renvoie `version=skipped` et l'ensemble des gates CD et de la publication sont ignorés.


## ⚠️ Comportement `v0.x`

Tant que la version majeure est `0`, une **mineure** est considérée comme un breaking change (Q2).  
Cela permet d'itérer rapidement sans accumuler de dette semver.

## 🏷️ Format de tag

Obligatoire : `v<major>.<minor>.<patch>` (préfixe `v` obligatoire).

Valide : `v1.2.3`, `v0.1.0`, `v10.0.0`  
Invalide : `1.2.3`, `v1.2`, `release-1.2.3`

## 🔀 Règle du max (Q7)

Lorsqu'une PR contient des commits de types multiples, le bump le plus élevé est retenu :

| Combinaison | Bump résultant |
|-------------|---------------|
| `fix:` + `feat:` | **mineure** |
| `feat:` + `BREAKING CHANGE` | **majeure** |
| `docs:` + `fix:` | **patch** |

Une alerte est émise dans le check `ci-traceability` si la PR déclare un bump différent de celui inféré.

## 🔒 Protection

Les tags sont protégés par un Tag Ruleset : la **modification et la suppression sont bloquées**
(la création reste autorisée pour permettre au workflow de release de publier `vX.Y.Z`).  
Cela garantit :

- Traçabilité : chaque tag correspond à un run de release
- Immuabilité : pas de re-tag ou de modification d'un tag publié
- Atomicité : création de la release + tag dans la même transaction

## 📋 CHANGELOG

- Généré automatiquement par le workflow `release.yml` depuis le dernier tag
- Groupé par type de commit
- Les issues fermées sont référencées dans les notes de release