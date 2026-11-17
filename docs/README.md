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

Un compte créé depuis l’administration doit remplacer son mot de passe temporaire à la première connexion. La case « TOTP obligatoire » se règle à la création ou sur la fiche utilisateur. Si elle est cochée, l’utilisateur scanne un QR code et confirme un premier code, puis fournit un nouveau code à chaque connexion. Le registre et l’administration sont bloqués tant que cette vérification n’a pas abouti. Les comptes existants conservent leur accès actuel jusqu’à l’activation de la case.

En cas de perte de l’appareil, vérifier l’identité de la personne avant toute réinitialisation. Un opérateur autorisé peut supprimer l’appareil TOTP du compte concerné depuis le shell Django local, en conservant la case obligatoire. La connexion suivante impose un nouvel enrôlement. Les sauvegardes SQLite contiennent les secrets TOTP et doivent bénéficier des mêmes protections que la base active.

Dans les listes Équipements et Services, les actions Archiver et Réactiver modifient la disponibilité dans les nouvelles fiches. Les fiches existantes gardent leurs rattachements, et les éléments archivés restent disponibles dans les filtres de l’historique. Les superutilisateurs consultent le journal d’administration et le filtrent par auteur et par période. Il utilise les entrées Django, avec les créations, modifications, suppressions, archivages et réactivations enregistrés dans l’administration.

## Contrôles récurrents

« Créer à partir de cette fiche » préremplit le titre, le contexte, le retour arrière et les référentiels actifs. La date, les vérifications, la référence technique, les états avant/après et les captures restent propres à la nouvelle intervention.

Dans un formulaire d’intervention, coller une capture avec Ctrl+V ou sélectionner des fichiers. Les images PNG, JPEG et WebP font au plus 5 Mo chacune, avec un maximum de 10 par fiche. Elles sont consultables après connexion et stockées dans la base SQLite, donc incluses dans sa sauvegarde.
Les miniatures sont affichées avant enregistrement. Retirer une miniature écarte le fichier de l’envoi.

Dans Clair-obscur, les champs facultatifs « état avant » et « état après » alimentent la comparaison. L’onglet « Carte des impacts » relie le changement à son équipement, au service principal et aux services concernés sélectionnés dans la fiche. Le filtre Service couvre ces deux types de rattachement.

Le registre affiche les cinq dernières interventions. Les recherches et filtres ouvrent `/historique/`, paginé à 20 résultats. Depuis une fiche ouverte dans ces résultats, « Retour aux résultats » conserve la page et les filtres.
La recherche couvre le titre, la modification, la référence technique, le nom de l’équipement et les noms des services principal et concernés, y compris lorsque ces référentiels ont été archivés.

Depuis l’administration, désactiver les comptes et archiver les équipements et services pour les retirer de l’usage courant. Les écrans de gestion bloquent leur suppression et conservent les liens historiques et le journal. Seuls les superutilisateurs gèrent les comptes et groupes et consultent le journal complet. Un membre du personnel doit recevoir les droits explicites pour gérer les référentiels.

Ctrl+K (Cmd+K sur Mac) place le curseur dans la recherche. Les flèches gauche et droite permettent de changer d’onglet de fiche. « Vue agrandie » ouvre la carte dans une fenêtre qui se ferme avec Échap.

Pour les cas à rejouer en préproduction, consulter le [registre de régressions](regressions.md).

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

Pour la recette locale, monter `logit-preprod-sql` en lecture seule dans un conteneur sans réseau et utiliser un volume Docker temporaire pour la copie. Ajouter une fiche fictive, une correction, une capture et une entrée admin sur la copie de travail uniquement. Sauvegarder cette base, restaurer la sauvegarde dans un nouveau fichier et vérifier `PRAGMA integrity_check` et `PRAGMA foreign_key_check`. Avec l’image LogIT testée, vérifier l’ouverture de la fiche, l’accès protégé à la capture, la correction et le journal filtré sur la base restaurée. Supprimer le volume temporaire à la fin de la recette.

Le fichier Compose livré cible la préproduction locale. Pour raccorder un reverse proxy existant, préparer une configuration de production distincte avec un nom d’hôte, un secret, un réseau et un volume propres à cet environnement. Le proxy doit écraser `X-Forwarded-Proto` pour établir le schéma de la requête. Reprendre l’image d’application validée par son identifiant ou digest et tester le raccordement avant bascule.
