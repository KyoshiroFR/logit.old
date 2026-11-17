# LogIT

Registre interne des changements d’infrastructure et de sécurité pour une petite équipe.

## Préproduction sur Docker Desktop

Depuis la racine, avec le moteur Linux de Docker Desktop actif et les ports 6320 et 6321 libres sur localhost, créer le fichier `.env` si nécessaire dans PowerShell.

```powershell
if (-not (Test-Path .env)) {
    $secret = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    Set-Content -Encoding ascii .env ("DJANGO_SECRET_KEY=" + $secret)
}
docker compose --profile proxy up -d --build
docker compose --profile proxy ps
docker compose exec app python manage.py createsuperuser
```

- Application à l’adresse https://localhost:6321 et administration à l’adresse https://localhost:6321/administration/
- `logit-preprod-proxy` publie les ports 6320 (HTTP) et 6321 (HTTPS) sur `127.0.0.1`. Caddy redirige HTTP vers HTTPS en conservant le chemin et les paramètres.
- `logit-preprod-app` exécute Django et Gunicorn sur le réseau `logit-preprod-net`.
- `logit-preprod-sql` conserve la base SQLite, dont les comptes et les corrections.
- `logit-preprod-tls` conserve les données de l’autorité de certification privée de Caddy.

Pour valider le certificat sans modifier la confiance Windows, exporter uniquement le certificat public de l’autorité.

```powershell
docker cp logit-preprod-proxy:/data/caddy/pki/authorities/local/root.crt logit-local-ca.crt
curl.exe --cacert logit-local-ca.crt --ssl-revoke-best-effort https://localhost:6321/connexion/
```

Pour une utilisation dans le navigateur, faire approuver ce certificat d’autorité dans le magasin de confiance utilisé par le navigateur. La clé privée reste dans le volume Caddy.

Dans l’administration, créer les comptes nominatifs et les équipements avant la première saisie. Les comptes ordinaires ont accès au registre et à la correction des fiches. L’administration gère les comptes et les référentiels. Les corrections sont horodatées et conservent les valeurs avant et après.

## Contrôles récurrents

Dans un formulaire d’intervention, coller une capture avec Ctrl+V ou sélectionner des fichiers. Les images PNG, JPEG et WebP font au plus 5 Mo chacune, avec un maximum de 10 par fiche. Elles sont consultables après connexion et stockées dans la base SQLite, donc incluses dans sa sauvegarde.

Dans Clair-obscur, les champs facultatifs « état avant » et « état après » alimentent la comparaison. L’onglet « Carte des impacts » relie le changement à son équipement, au service principal et aux services concernés sélectionnés dans la fiche. Le filtre Service couvre ces deux types de rattachement.

Le registre affiche les cinq dernières interventions. Les recherches et filtres ouvrent `/historique/`, paginé à 20 résultats. Depuis une fiche ouverte dans ces résultats, « Retour aux résultats » conserve la page et les filtres.

```powershell
docker compose exec app python manage.py check
docker compose exec app python manage.py makemigrations --check --dry-run
docker compose exec app python manage.py test
```

## Sauvegarde et préparation d’une future production

Utiliser l’API de sauvegarde SQLite pour un instantané cohérent, par exemple depuis le conteneur.

```powershell
docker compose exec app python -c "import sqlite3; src = sqlite3.connect('/data/logit.sqlite3'); dst = sqlite3.connect('/tmp/logit-backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
docker cp logit-preprod-app:/tmp/logit-backup.sqlite3 logit-backup.sqlite3
docker compose exec app rm /tmp/logit-backup.sqlite3
```

Placer la copie dans le système de sauvegarde interne hors de l’hôte. Tester la restauration dans un environnement isolé en substituant la copie sur le volume d’essai, application arrêtée, puis en vérifiant l’intégrité SQLite, les fiches et leurs corrections après redémarrage. Les sauvegardes contiennent des données internes et des comptes.

Le fichier Compose livré cible la préproduction locale. Pour raccorder un reverse proxy existant, préparer une configuration de production distincte avec un nom d’hôte, un secret, un réseau et un volume propres à cet environnement. Le proxy doit écraser `X-Forwarded-Proto` pour établir le schéma de la requête. Reprendre l’image d’application validée par son identifiant ou digest et tester le raccordement avant bascule.
