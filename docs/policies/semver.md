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
| **Patch (Z)** | Correction, refactoring, documentation, maintenance |

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

Les tags sont protégés par un Tag Ruleset (création/modification/suppression bloquées pour les humains).  
Seul le bot de release (GitHub App) peut pousser des tags, garantissant :

- Traçabilité : chaque tag correspond à un run de release
- Immuabilité : pas de re-tag ou de modification d'un tag publié
- Atomicité : création de la release + tag dans la même transaction

## 📋 CHANGELOG

- Généré automatiquement par le workflow `release.yml` depuis le dernier tag
- Groupé par type de commit
- Les issues fermées sont référencées dans les notes de release