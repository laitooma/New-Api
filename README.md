# devops-portfolio-api

Projet DevOps débutant : une petite API Python qu'on fait passer, étape par étape,
du code jusqu'au cloud.

[![CI](https://github.com/laitooma/New-Api/actions/workflows/ci.yml/badge.svg)](https://github.com/laitooma/New-Api/actions/workflows/ci.yml)

## Feuille de route

- [x] **1. API** : FastAPI avec un endpoint `/health` + tests pytest
- [x] **2. Docker** : image légère, utilisateur non-root, healthcheck
- [x] **3. CI GitHub Actions** : lint (ruff) → tests (pytest) → build Docker → smoke test
- [x] **3b. Registre** : publication de l'image sur GitHub Container Registry (`ghcr.io`)
- [ ] **4. Terraform** : décrire l'infrastructure AWS en code
- [ ] **5. AWS** : déployer l'image (ex. ECR + App Runner ou ECS)

## Lancer en local (sans Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt

ruff check . && ruff format --check .   # lint
pytest -v                               # tests
uvicorn app.main:app --reload           # http://localhost:8000/health
```

## Lancer avec Docker

```bash
docker build -t new-api .
docker run -d --name api -p 8000:8000 new-api
curl http://localhost:8000/health        # {"status":"ok"}
docker ps                                # colonne STATUS : (healthy) après ~30 s
docker rm -f api
```

## CI

Le fichier `.github/workflows/ci.yml` tourne à chaque push sur `main` et à chaque
pull request :

1. **lint-and-test** : installe les dépendances, lance `ruff` puis `pytest`.
2. **docker** (seulement si l'étape 1 passe) : construit l'image, démarre le
   conteneur et vérifie que `/health` répond.
3. **Publication** (seulement après un push sur `main`, jamais depuis une PR) :
   pousse l'image sur `ghcr.io/laitooma/new-api` avec deux tags,
   `latest` et `sha-<commit>` (pour savoir exactement quel code tourne).

## Récupérer l'image publiée

```bash
docker pull ghcr.io/laitooma/new-api:latest
docker run -d -p 8000:8000 ghcr.io/laitooma/new-api:latest
```

Par défaut le package est **privé** : il faut `docker login ghcr.io` avec un
token GitHub, ou le rendre public dans GitHub → ton profil → *Packages* →
`new-api` → *Package settings* → *Change visibility*.

## Exercices pour progresser

1. Ajoute un endpoint `GET /version` qui renvoie la version de l'app, avec son test.
2. Casse volontairement un test, pousse sur une branche, ouvre une PR : observe la CI échouer.
3. Ajoute un fichier `docker-compose.yml` pour lancer l'API avec une seule commande.
4. Fais échouer exprès le smoke test (change le port dans le `Dockerfile`) et lis les logs de la CI.
