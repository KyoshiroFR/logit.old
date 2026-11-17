# LogIT

LogIT est un registre auto-hébergé des changements d’infrastructure et de sécurité. Il permet à l’équipe de retrouver qui a fait une intervention, de comparer l’état avant et après, et de consulter les services concernés et le plan de retour arrière.

## Installer LogIT

Depuis **Linux ou Windows via WSL**, avec Bash, `curl` et Docker Compose disponibles, lance cette commande dans le répertoire qui accueillera le dossier `logit`.

```bash
installateur=$(curl -fsSL https://logit.kyoshiro.ovh/install.sh) && bash -c "$installateur"
```

L’installation démarre avec une base vide. Le terminal affiche le mot de passe temporaire de `admin-logit`, à remplacer lors de la première connexion. Ouvre ensuite [https://localhost:6321](https://localhost:6321). Le proxy utilise un certificat local Caddy.

La procédure locale, la sauvegarde et la restauration sont décrites dans [la documentation](docs/README.md).

## Donner un retour

- [Signaler un bug ou un problème d’installation](https://github.com/KyoshiroFR/logit/issues/new?template=bug_report.md)
- [Proposer une amélioration ou partager un retour d’expérience](https://github.com/KyoshiroFR/logit/issues/new?template=feedback.md)

Les Issues sont publiques. Utilise des exemples fictifs ou des captures anonymisées.
