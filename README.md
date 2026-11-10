# devops-portfolio-api

Projet DevOps débutant : une petite API Python qu'on fait passer, étape par étape,
du code jusqu'au cloud.

[![CI](https://github.com/laitooma/New-Api/actions/workflows/ci.yml/badge.svg)](https://github.com/laitooma/New-Api/actions/workflows/ci.yml)

## Feuille de route

- [x] **1. API** : FastAPI avec un endpoint `/health` + tests pytest
- [x] **2. Docker** : image légère, utilisateur non-root, healthcheck
- [x] **3. CI GitHub Actions** : lint (ruff) → tests (pytest) → build Docker → smoke test
- [x] **3b. Registre** : publication de l'image sur GitHub Container Registry (`ghcr.io`)
- [x] **4. Terraform** : l'infrastructure AWS décrite en code (`infra/`), vérifiée par la CI
- [ ] **5. AWS** : `terraform apply` depuis ton poste (voir [Déployer sur AWS](#déployer-sur-aws))

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
3. **terraform** (en parallèle) : `terraform fmt -check` puis `terraform validate`
   sur `infra/`, sans compte AWS.
4. **Publication** (seulement après un push sur `main`, jamais depuis une PR) :
   pousse l'image sur `ghcr.io/laitooma/new-api` avec deux tags,
   `latest` et `sha-<commit>` (pour savoir exactement quel code tourne).

## Récupérer l'image publiée

```bash
docker pull ghcr.io/laitooma/new-api:latest
docker run -d -p 8000:8000 ghcr.io/laitooma/new-api:latest
```

Le package est **public** : pas besoin de `docker login` pour le récupérer.
C'est aussi ce qui permet à AWS de le télécharger sans identifiants.

## Déployer sur AWS

L'infrastructure est dans `infra/` : un service **AWS Lightsail Containers**
(prix fixe, URL HTTPS fournie, pas de réseau ni de load balancer à configurer)
qui fait tourner l'image publiée sur `ghcr.io`.

> ⚠️ **Ça coûte de l'argent** tant que le service existe : environ 7 $/mois en
> taille `nano` (vérifie le prix actuel sur la page tarifs Lightsail). Crée une
> alerte de budget dans AWS Billing avant de commencer, et lance
> `terraform destroy` quand tu as fini.

Prérequis : un compte AWS, un utilisateur IAM (pas le compte root) avec des
clés d'accès, l'[AWS CLI](https://aws.amazon.com/cli/) et
[Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.6.

```bash
aws configure                    # colle tes clés d'accès, région : eu-west-3
cd infra
terraform init                   # télécharge le provider AWS
terraform plan                   # montre ce qui va être créé (2 ressources)
terraform apply                  # crée vraiment, tape "yes" pour confirmer
```

Le premier déploiement prend environ 5 minutes. Ensuite :

```bash
terraform output health_url      # l'adresse à tester
curl "$(terraform output -raw health_url)"   # {"status":"ok"}
```

Déployer une version précise (recommandé, plutôt que `latest`) :

```bash
terraform apply -var image=ghcr.io/laitooma/new-api:sha-<commit>
```

Tout supprimer et arrêter de payer :

```bash
terraform destroy
```

L'état Terraform (`terraform.tfstate`) reste sur ton poste et n'est pas
versionné. C'est suffisant seul ; en équipe on le stocke dans un bucket S3.

## Exercices pour progresser

1. Ajoute un endpoint `GET /version` qui renvoie la version de l'app, avec son test.
2. Casse volontairement un test, pousse sur une branche, ouvre une PR : observe la CI échouer.
3. Ajoute un fichier `docker-compose.yml` pour lancer l'API avec une seule commande.
4. Fais échouer exprès le smoke test (change le port dans le `Dockerfile`) et lis les logs de la CI.
5. Passe `scale` à 2 dans `infra/variables.tf`, lance `terraform plan` et lis ce qui change (et le prix).
6. Déplace l'état Terraform dans un bucket S3 (`backend "s3"`).
