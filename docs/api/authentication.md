# 🔐 Authentification Bearer JWT

Toutes les routes `/model/*` et `/buildings*` sont protégées par un **Bearer token** (schéma `HTTPBearer`). Les exemples visent le port **8080** de Docker Compose ; avec `uv run fastapi dev`, remplacer par `8000`.

## Obtenir un jeton

```bash
curl -X POST http://localhost:8080/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=johndoe&password=secret"
```

Puis l'utiliser sur les routes protégées :

```bash
curl http://localhost:8080/model/list -H "Authorization: Bearer <TOKEN>"
```

Dans un script, sans `jq` :

```bash
TOKEN=$(curl -fsS -X POST http://localhost:8080/token -d "username=johndoe&password=secret" \
  | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
```

## Réponses d'erreur

- **400** sur `POST /token` : identifiants incorrects ou compte inactif ;
- **401** sur les routes protégées : jeton absent, invalide ou expiré, ou utilisateur supprimé/désactivé depuis l'émission.

## Comptes

Les utilisateurs sont stockés dans la table `users` (mot de passe haché). Les comptes de démonstration `johndoe` / `alice` (mot de passe `secret`) ne sont créés par `create_db` que si `P5_SEED_DEMO_USERS=1` (valeur de `.example.env`, transmise au service `tools`) ou avec `python -m app.db.create_db --demo-users`. Seul `johndoe` est actif : `alice` est créée **inactive** et `POST /token` lui répond 400 (elle sert à tester le refus d'un compte désactivé).

**En production, laisser `P5_SEED_DEMO_USERS` à 0 (ou absent)** et créer les utilisateurs réels directement dans la table `users` : un compte au mot de passe public donnerait accès à toute l'API.

## Clé de signature

La clé `SECRET_KEY` est chargée depuis le fichier `.env` (ignoré par git). Génération : `openssl rand -hex 32` (le script [`scripts/quickstart.sh`](../../scripts/quickstart.sh) en génère une aléatoire en mode image). Elle est **obligatoire** : le code ne contient aucune clé par défaut, et créer ou vérifier un jeton sans `SECRET_KEY` lève une erreur explicite.
