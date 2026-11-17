#!/usr/bin/env bash
set -euo pipefail
umask 077

# Refilled from the Git archive by the release publisher.
release='@LOGIT_RELEASE@'
archive_sha256='@LOGIT_SHA256@'
origin='@LOGIT_ORIGIN@'

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

instance=${LOGIT_INSTALL_INSTANCE:-logit}
http_port=${LOGIT_INSTALL_HTTP_PORT:-6320}
https_port=${LOGIT_INSTALL_HTTPS_PORT:-6321}
destination=${LOGIT_INSTALL_DIR:-"$PWD/logit"}

[[ $release =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && $archive_sha256 =~ ^[a-f0-9]{64}$ ]] ||
    fail 'Utilise le script publié avec une version de LogIT.'
[[ $instance =~ ^[a-z][a-z0-9-]{0,39}$ && $instance != logit-preprod ]] ||
    fail 'Choisis un nom d’instance différent de la préproduction.'
for port in "$http_port" "$https_port"; do
    [[ $port =~ ^[1-9][0-9]{3,4}$ ]] && (( port >= 1024 && port <= 65535 )) ||
        fail 'Les ports doivent être compris entre 1024 et 65535.'
done
[[ $http_port != "$https_port" ]] || fail 'Choisis deux ports différents.'

for variable in DJANGO_SECRET_KEY LOGIT_INSTANCE LOGIT_IMAGE_TAG LOGIT_HOST LOGIT_BIND_IP LOGIT_HTTP_PORT LOGIT_HTTPS_PORT; do
    [[ ! -v $variable ]] || fail "Relance depuis un terminal sans la variable $variable."
done
docker compose version >/dev/null
[[ $(docker info --format '{{.OSType}}') == linux ]] || fail 'Utilise le moteur de conteneurs Linux.'

if [[ -e $destination || -L $destination ]]; then
    [[ ! -L $destination && -f $destination/.logit-install && -f $destination/.env ]] ||
        fail 'Le dossier cible existe déjà. Choisis un répertoire vide.'
    expected=$(printf '%s\n' "$release" "$instance" "$http_port" "$https_port")
    [[ $(cat "$destination/.logit-install") == "$expected" ]] ||
        fail 'Ce dossier correspond à une autre configuration. Relance avec les paramètres d’origine.'
else
    volumes=$(docker volume ls --format '{{.Name}}')
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$instance")
    networks=$(docker network ls --format '{{.Name}}')
    if [[ -n $containers ]] || grep -Fxq -e "$instance-sql" -e "$instance-tls" <<< "$volumes" ||
        grep -Fxq "$instance-net" <<< "$networks"; then
        fail 'Cette instance Docker existe déjà. Choisis un autre nom et des ports libres.'
    fi
    staging=$(mktemp -d "$(dirname -- "$destination")/.logit-install.XXXXXXXX")
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
    } > "$staging/source/.env"
    unset secret
    printf '%s\n' "$release" "$instance" "$http_port" "$https_port" > "$staging/source/.logit-install"
    mv -T --no-clobber -- "$staging/source" "$destination"
    [[ ! -e $staging/source ]] || fail 'Le dossier cible vient d’être créé par une autre installation.'
fi

cd -- "$destination"
compose=(docker compose --project-name "$instance" --env-file .env -f compose.yaml --profile proxy)
"${compose[@]}" up -d --build --wait --wait-timeout 90
printf 'LogIT https://localhost:%s/\nAdministration https://localhost:%s/administration/\n' \
    "$https_port" "$https_port"
"${compose[@]}" exec -T app python manage.py bootstrap_admin
