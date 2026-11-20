#!/usr/bin/env bash
# Installateur LogIT pour Debian 12 (Bookworm) et 13 (Trixie).
# Usage : installateur=$(curl -fsSL https://logit.kyoshiro.ovh/install.sh) && sudo bash -c "$installateur"
# shellcheck disable=SC1091,SC1112,SC2015,SC2016
set -euo pipefail
umask 077

# Renseignés depuis l'archive Git par deploy/package.sh.
release='@LOGIT_RELEASE@'
archive_sha256='@LOGIT_SHA256@'
origin='@LOGIT_ORIGIN@'

info() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mAttention :\033[0m %s\n' "$*" >&2; }
fail() {
    printf '\033[31mErreur :\033[0m %s\n' "$*" >&2
    exit 1
}

instance=${LOGIT_INSTALL_INSTANCE:-logit}
http_port=${LOGIT_INSTALL_HTTP_PORT:-6320}
https_port=${LOGIT_INSTALL_HTTPS_PORT:-6321}
destination=${LOGIT_INSTALL_DIR:-/opt/logit}

# --- Paramètres --------------------------------------------------------------

[[ $release =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && $archive_sha256 =~ ^[a-f0-9]{64}$ ]] ||
    fail 'Utilise le script publié avec une version de LogIT.'
[[ $instance =~ ^[a-z][a-z0-9-]{0,39}$ && $instance != logit-preprod ]] ||
    fail 'Choisis un nom d’instance différent de la préproduction.'
for port in "$http_port" "$https_port"; do
    [[ $port =~ ^[1-9][0-9]{3,4}$ ]] && (( port >= 1024 && port <= 65535 )) ||
        fail 'Les ports doivent être compris entre 1024 et 65535.'
done
[[ $http_port != "$https_port" ]] || fail 'Choisis deux ports différents.'
[[ $destination == /* ]] || fail 'LOGIT_INSTALL_DIR doit être un chemin absolu.'

for variable in DJANGO_SECRET_KEY LOGIT_INSTANCE LOGIT_IMAGE_TAG LOGIT_HOST LOGIT_BIND_IP LOGIT_HTTP_PORT LOGIT_HTTPS_PORT; do
    [[ ! -v $variable ]] || fail "Relance depuis un terminal sans la variable $variable."
done

# --- Système ------------------------------------------------------------------

(( EUID == 0 )) || fail 'Lance l’installation en root, par exemple : sudo bash -c "$installateur"'

[[ -r /etc/os-release ]] || fail 'Système non reconnu : /etc/os-release est absent.'
os_id=$(. /etc/os-release && printf '%s' "${ID:-}")
os_version=$(. /etc/os-release && printf '%s' "${VERSION_ID:-}")
os_codename=$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-}")
[[ $os_id == debian && ( $os_version == 12 || $os_version == 13 ) ]] ||
    fail "LogIT s’installe sur Debian 12 ou 13. Système détecté : ${os_id:-inconnu} ${os_version:-}."

architecture=$(dpkg --print-architecture)
[[ $architecture == amd64 || $architecture == arm64 ]] ||
    fail "Architecture $architecture non prise en charge (amd64 ou arm64 attendue)."

wsl=false
grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null && wsl=true

export DEBIAN_FRONTEND=noninteractive
apt_updated=false
apt_install() {
    if [[ $apt_updated == false ]]; then
        apt-get update -qq
        apt_updated=true
    fi
    apt-get install -y -qq --no-install-recommends "$@" >/dev/null
}
installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'ok installed'; }

missing=()
for package in ca-certificates curl tar; do
    installed "$package" || missing+=("$package")
done
if (( ${#missing[@]} )); then
    info "Installation des prérequis : ${missing[*]}"
    apt_install "${missing[@]}"
fi

# --- Docker -------------------------------------------------------------------

install_docker() {
    # Procédure officielle : https://docs.docker.com/engine/install/debian/
    conflicts=()
    for package in docker.io docker-compose docker-doc docker-buildx podman-docker containerd runc; do
        installed "$package" && conflicts+=("$package")
    done
    (( ${#conflicts[@]} == 0 )) ||
        fail "Paquets en conflit avec Docker Engine : ${conflicts[*]}. Désinstalle-les (apt-get remove ${conflicts[*]}) puis relance."

    info 'Installation de Docker Engine depuis le dépôt officiel Docker'
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL --proto '=https' https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $os_codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    chmod 0644 /etc/apt/sources.list.d/docker.sources
    apt_updated=false
    apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker >/dev/null
}

if ! command -v docker >/dev/null; then
    [[ $wsl == false ]] ||
        fail 'Docker est absent de WSL. Active l’intégration WSL de Docker Desktop pour cette distribution, puis relance.'
    install_docker
elif ! docker compose version >/dev/null 2>&1; then
    if [[ -f /etc/apt/sources.list.d/docker.sources || -f /etc/apt/sources.list.d/docker.list ]]; then
        info 'Installation du plugin Docker Compose'
        apt_install docker-compose-plugin
    else
        fail 'Docker est installé sans le plugin Compose. Installe Docker depuis le dépôt officiel Docker, puis relance.'
    fi
fi

if ! docker info >/dev/null 2>&1; then
    [[ $wsl == false ]] && systemctl start docker
    docker info >/dev/null 2>&1 || fail 'Le service Docker ne répond pas.'
fi
[[ $(docker info --format '{{.OSType}}') == linux ]] || fail 'Utilise le moteur de conteneurs Linux.'

# --- Heure système ------------------------------------------------------------
# La date d'enregistrement des fiches vient de l'horloge de cette machine.

if [[ $wsl == true ]]; then
    : # WSL reprend l'heure de Windows.
elif command -v timedatectl >/dev/null && timedatectl show >/dev/null 2>&1; then
    if [[ $(timedatectl show -p NTP --value) != yes ]]; then
        if ! installed systemd-timesyncd && ! installed chrony && ! installed ntpsec && ! installed ntp; then
            info 'Installation de la synchronisation horaire (systemd-timesyncd)'
            apt_install systemd-timesyncd
        fi
        timedatectl set-ntp true 2>/dev/null || true
    fi
    [[ $(timedatectl show -p NTP --value) == yes ]] ||
        warn 'La synchronisation NTP n’a pas pu être activée. Les dates d’enregistrement dépendent de l’horloge de cette machine.'
    [[ $(timedatectl show -p NTPSynchronized --value) == yes ]] ||
        warn 'L’horloge n’est pas encore synchronisée. Vérifie plus tard avec : timedatectl'
else
    warn 'Impossible de vérifier la synchronisation NTP (timedatectl indisponible). Vérifie l’horloge de cette machine.'
fi

# --- Adresse d'accès ----------------------------------------------------------

detected_ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1)
default_hosts=$(printf '%s\n' "$detected_ip" "$(hostname -s 2>/dev/null)" "$(hostname -f 2>/dev/null)" localhost |
    awk 'NF && !seen[$0]++' | paste -sd ' ')
hosts=${LOGIT_INSTALL_HOST:-}
if [[ -z $hosts && -f $destination/.logit-install ]]; then
    # Installation existante : on reprend ses adresses sans poser de question.
    hosts=$(sed -n 5p "$destination/.logit-install")
fi
if [[ -z $hosts && -t 0 ]]; then
    read -r -p "Adresses d’accès à LogIT, séparées par des espaces [$default_hosts] : " hosts
fi
hosts=${hosts:-$default_hosts}
hosts=$(tr ',' ' ' <<< "$hosts" | xargs)
for host in $hosts; do
    [[ $host =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || fail "Adresse invalide : $host"
done
caddy_hosts=${hosts// /, }

# --- Installation -------------------------------------------------------------

expected=$(printf '%s\n' "$release" "$instance" "$http_port" "$https_port" "$hosts")
compose=(docker compose --project-name "$instance" --env-file .env -f compose.yaml --profile proxy)

if [[ -e $destination || -L $destination ]]; then
    [[ ! -L $destination && -f $destination/.logit-install && -f $destination/.env ]] ||
        fail "Le dossier $destination existe déjà. Choisis un autre emplacement avec LOGIT_INSTALL_DIR."
    [[ $(cat "$destination/.logit-install") == "$expected" ]] ||
        fail "LogIT est déjà installé dans $destination avec une autre configuration. Aucune modification effectuée."
    cd -- "$destination"
    if [[ -n $("${compose[@]}" ps --status running -q app 2>/dev/null) ]]; then
        info "LogIT $release est déjà installé et démarré dans $destination. Aucune modification effectuée."
        exit 0
    fi
    info 'Reprise de l’installation interrompue'
else
    for port in "$http_port" "$https_port"; do
        [[ -z $(ss -Hltn "sport = :$port" 2>/dev/null) ]] || fail "Le port $port est déjà utilisé sur cette machine."
    done
    parent=$(dirname -- "$destination")
    mkdir -p -- "$parent"
    available_kb=$(df -Pk -- "$parent" | awk 'NR == 2 { print $4 }')
    (( available_kb >= 2 * 1024 * 1024 )) || fail "Au moins 2 Go libres sont nécessaires dans $parent."

    volumes=$(docker volume ls --format '{{.Name}}')
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$instance")
    networks=$(docker network ls --format '{{.Name}}')
    if [[ -n $containers ]] || grep -Fxq -e "$instance-sql" -e "$instance-tls" <<< "$volumes" ||
        grep -Fxq "$instance-net" <<< "$networks"; then
        fail 'Cette instance Docker existe déjà. Choisis un autre nom et des ports libres.'
    fi

    info "Téléchargement de LogIT $release"
    staging=$(mktemp -d "$parent/.logit-install.XXXXXXXX")
    trap 'rm -rf -- "$staging"' EXIT
    curl -fsSL --proto '=https' --proto-redir '=https' \
        "$origin/releases/$release/logit.tar.gz" -o "$staging/release.tar.gz"
    printf '%s  %s\n' "$archive_sha256" "$staging/release.tar.gz" | sha256sum --check --status ||
        fail 'L’empreinte du paquet LogIT ne correspond pas.'
    mkdir "$staging/source"
    tar -xzf "$staging/release.tar.gz" -C "$staging/source"
    secret=$(od -A n -N 48 -t x1 /dev/urandom | tr -d ' \n')
    {
        printf 'DJANGO_SECRET_KEY=%s\n' "$secret"
        printf 'LOGIT_INSTANCE=%s\nLOGIT_IMAGE_TAG=%s-%s\n' "$instance" "$instance" "$release"
        printf 'LOGIT_HTTP_PORT=%s\nLOGIT_HTTPS_PORT=%s\n' "$http_port" "$https_port"
        printf 'LOGIT_HOST="%s"\nLOGIT_BIND_IP=0.0.0.0\n' "$caddy_hosts"
    } > "$staging/source/.env"
    unset secret
    printf '%s\n' "$expected" > "$staging/source/.logit-install"
    mv -T --no-clobber -- "$staging/source" "$destination"
    [[ ! -e $staging/source ]] || fail 'Le dossier cible vient d’être créé par une autre installation.'
    cd -- "$destination"
fi

info 'Construction et démarrage des conteneurs (quelques minutes la première fois)'
"${compose[@]}" up -d --build --wait --wait-timeout 180

printf '\n\033[1mLogIT %s est installé.\033[0m\n\n' "$release"
for host in $hosts; do
    printf '  https://%s:%s/\n' "$host" "$https_port"
done
printf '\nDossier : %s\n\n' "$destination"
bootstrap=$("${compose[@]}" exec -T app python manage.py bootstrap_admin)
printf '%s\n' "$bootstrap"
if grep -q '^Mot de passe temporaire' <<< "$bootstrap"; then
    printf '\nCe mot de passe ne sera plus affiché. Il devra être changé à la première connexion.\n'
fi
