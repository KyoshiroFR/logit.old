# LogIT

LogIT est un registre auto-hébergé des changements d’infrastructure et de sécurité. Il permet à l’équipe de retrouver qui a fait une intervention, de comparer l’état avant et après, et de consulter les services concernés et le plan de retour arrière.

[Installer LogIT](#installer-logit) · [Essayer en cinq minutes](#essayer-logit-en-cinq-minutes) · [Donner un retour](#donner-un-retour)

![Registre LogIT en thème Clair-obscur avec le comparatif avant et après d’une règle pare-feu fictive](docs/images/logit-registre.png)

![Carte des impacts de la même intervention avec le pare-feu, le portail interne et les services concernés](docs/images/logit-carte-impacts.png)

## Installer LogIT

Sur **Debian 12 (Bookworm) ou 13 (Trixie)**, en amd64 ou arm64, lance cette commande avec un compte qui peut utiliser `sudo`.

```bash
installateur=$(curl -fsSL https://logit.kyoshiro.ovh/install.sh) && sudo bash -c "$installateur"
```

Sur une Debian fraîchement installée, `curl` et `sudo` peuvent manquer. Connecte-toi alors en root avec `su -` et utilise `wget`, présent par défaut.

```bash
installateur=$(wget -qO- https://logit.kyoshiro.ovh/install.sh) && bash -c "$installateur"
```

L’installateur s’occupe du reste.

1. Il vérifie le système, puis installe les prérequis manquants (`ca-certificates`, `curl`, `tar`).
2. Si Docker est absent, il installe Docker Engine et le plugin Compose depuis [le dépôt officiel Docker](https://docs.docker.com/engine/install/debian/). Si un paquet non officiel comme `docker.io` est présent, il s’arrête et indique quoi désinstaller.
3. Il active la synchronisation NTP, car la date d’enregistrement des fiches vient de l’horloge de la machine.
4. Il télécharge la version publiée, vérifie son empreinte SHA-256 et l’installe dans `/opt/logit` avec une base vide.
5. Il demande les adresses d’accès (IP et nom de la machine proposés par défaut), puis affiche les URL et le mot de passe temporaire de `admin-logit`, à remplacer lors de la première connexion.

Relancer la commande sur une machine où LogIT tourne déjà ne modifie rien. Une installation interrompue reprend là où elle s’était arrêtée.

- **Installation sans question**. Fixe les adresses d’accès avec `LOGIT_INSTALL_HOST`, séparées par des espaces.

  ```bash
  installateur=$(curl -fsSL https://logit.kyoshiro.ovh/install.sh) &&
    sudo LOGIT_INSTALL_HOST="192.168.1.10 logit.interne" bash -c "$installateur"
  ```

- **Autres réglages**. `LOGIT_INSTALL_DIR` change le dossier (`/opt/logit` par défaut). `LOGIT_INSTALL_INSTANCE`, `LOGIT_INSTALL_HTTP_PORT` et `LOGIT_INSTALL_HTTPS_PORT` permettent une instance distincte, par exemple `logit-test` sur les ports `16320` et `16321`.

- **WSL**. Sous Debian dans WSL, l’installateur utilise le Docker déjà disponible, par exemple via l’intégration WSL de Docker Desktop. Il n’installe pas Docker dans WSL.

- **Certificat local**. Caddy signe le certificat avec sa propre autorité. Si le navigateur signale un certificat inconnu, exporte l’autorité publique, puis importe-la dans le magasin de confiance des postes de l’équipe.

  ```bash
  sudo docker cp logit-proxy:/data/caddy/pki/authorities/local/root.crt logit-local-ca.crt
  ```

Retrouve [la release v1.0.0](https://github.com/KyoshiroFR/logit/releases/tag/v1.0.0), ou consulte [la documentation](docs/README.md) pour la sauvegarde et la restauration.

## Essayer LogIT en cinq minutes

1. Dans **Administration**, crée un équipement fictif nommé « Pare-feu de test » et un service « VPN de test ».
2. Dans **Nouvelle fiche**, consigne une modification fictive. Indique son impact, la vérification effectuée et la procédure de retour arrière. Ajoute les états avant et après et colle une capture anonymisée avec **Ctrl+V**.
3. Demande à un collègue de retrouver la fiche dans **Historique**, puis d’ouvrir **Carte des impacts** et **Retour arrière**. Sur une instance locale, tu peux rejouer ce parcours avec un second compte dans une fenêtre privée.
4. Partage le premier endroit où vous avez hésité ou l’information qu’il vous a fallu chercher ailleurs. Utilise le modèle de retour ci-dessous.

## Donner un retour

- [Signaler un bug ou un problème d’installation](https://github.com/KyoshiroFR/logit/issues/new?template=bug_report.md)
- [Proposer une amélioration ou partager un retour d’expérience](https://github.com/KyoshiroFR/logit/issues/new?template=feedback.md)

Les Issues sont publiques. Utilise des exemples fictifs ou des captures anonymisées.
