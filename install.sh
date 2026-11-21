#!/usr/bin/env bash
# Installateur LogIT : une commande sur Debian 12 ou 13, installation complète sur base vierge.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/KyoshiroFR/logit/main/install.sh)"
#
# Il analyse le serveur et s'adapte : Docker présent ou non, reverse proxy existant
# (nginx, Apache, Caddy) ou non, ports occupés, pare-feu, installation déjà présente.
#
# Variables facultatives :
#   LOGIT_INSTALL_HOSTS   adresses d'accès, séparées par des espaces (sinon détectées puis demandées)
#   LOGIT_INSTALL_PROXY   auto (défaut) | caddy | nginx | apache | host-caddy | manual
#   LOGIT_INSTALL_DIR     dossier d'installation (défaut /opt/logit)
#   LOGIT_INSTALL_REF     version à installer (défaut : celle de ce script)
#   LOGIT_INSTALL_YES=1   aucune question, valeurs détectées
# shellcheck disable=SC1091,SC1112,SC2015,SC2016
set -Eeuo pipefail
umask 027

LOGIT_REPO="https://github.com/KyoshiroFR/logit.git"
LOGIT_DEFAULT_REF="v2.3-bugs"  # branche de test ; passera au tag lors de la publication
# Empreinte Git du commit de la version : renseignée lors de la publication d'une version.
LOGIT_DEFAULT_COMMIT=""

REF=${LOGIT_INSTALL_REF:-$LOGIT_DEFAULT_REF}
DIR=${LOGIT_INSTALL_DIR:-/opt/logit}
PROXY_CHOICE=${LOGIT_INSTALL_PROXY:-auto}
ASSUME_YES=${LOGIT_INSTALL_YES:-0}
LOG=/var/log/logit-install.log

# --- Affichage ----------------------------------------------------------------------------
if [[ -t 1 ]]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; D=$'\e[2m'; N=$'\e[0m'; else B='' G='' Y='' R='' D='' N=''; fi
step()  { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    %s✔%s %s\n' "$G" "$N" "$*"; }
warn()  { printf '    %s!%s %s\n' "$Y" "$N" "$*"; WARNINGS+=("$*"); }
fail()  { printf '\n%sErreur :%s %s\n' "$R" "$N" "$*" >&2; printf '%sJournal détaillé : %s%s\n' "$D" "$LOG" "$N" >&2; exit 1; }
WARNINGS=()
trap 'fail "échec inattendu à la ligne $LINENO (commande : $BASH_COMMAND)."' ERR

ask() {  # ask "question" "défaut" -> REPLY
    REPLY=$2
    if [[ $ASSUME_YES != 1 && -t 0 ]]; then
        read -r -p "    $1 [$2] : " REPLY || true
        REPLY=${REPLY:-$2}
    fi
}

random_secret() {  # longueur ; alphabet sans caractère ambigu pour .env et KeePass
    local length=$1 value=""
    while (( ${#value} < length )); do
        value+=$(openssl rand -base64 96 | tr -dc 'A-Za-z0-9')
    done
    printf '%s' "${value:0:length}"
}

installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'ok installed'; }
port_used() { [[ -n $(ss -Hltn "sport = :$1" 2>/dev/null) ]]; }
listener_of() { ss -Hltnp "sport = :$1" 2>/dev/null | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | head -n 1; }

APT_UPDATED=0
apt_install() {
    export DEBIAN_FRONTEND=noninteractive
    if (( APT_UPDATED == 0 )); then apt-get update -qq >>"$LOG" 2>&1; APT_UPDATED=1; fi
    apt-get install -y -qq --no-install-recommends "$@" >>"$LOG" 2>&1
}

compose() {
    local files=() f
    IFS=: read -ra list <<<"$(sed -n 's/^COMPOSE_FILE=//p' "$DIR/.env")"
    for f in "${list[@]}"; do files+=(-f "$f"); done
    docker compose --project-name logit --project-directory "$DIR/deploy" --env-file "$DIR/.env" "${files[@]}" "$@"
}

wait_healthy() {  # attend que le conteneur de l'application soit « healthy »
    local id state
    for _ in $(seq 1 "${1:-120}"); do
        id=$(compose ps -q app 2>/dev/null || true)
        state=$( [[ -n $id ]] && docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)
        [[ $state == healthy ]] && return 0
        sleep 2
    done
    return 1
}

# --- 1. Système ---------------------------------------------------------------------------
printf '%sLogIT — installation%s %s(%s)%s\n' "$B" "$N" "$D" "$REF" "$N"
(( EUID == 0 )) || { printf 'Lance l’installation en root : sudo bash -c "$(curl -fsSL …/install.sh)", ou depuis « su - ».\n' >&2; exit 1; }
: >"$LOG"; chmod 600 "$LOG"

step "Analyse du serveur"
[[ -r /etc/os-release ]] || fail "système non reconnu (/etc/os-release absent)."
OS_ID=$(. /etc/os-release; echo "${ID:-}"); OS_VER=$(. /etc/os-release; echo "${VERSION_ID:-}"); OS_CODE=$(. /etc/os-release; echo "${VERSION_CODENAME:-}")
[[ $OS_ID == debian && ( $OS_VER == 12 || $OS_VER == 13 ) ]] || fail "LogIT s’installe sur Debian 12 ou 13 (détecté : ${OS_ID:-?} ${OS_VER:-?})."
ARCH=$(dpkg --print-architecture)
[[ $ARCH == amd64 || $ARCH == arm64 ]] || fail "architecture $ARCH non prise en charge (amd64 ou arm64)."
ok "Debian $OS_VER ($OS_CODE), $ARCH"
WSL=0; grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null && WSL=1
(( WSL )) && info "WSL détecté"

PARENT=$(dirname "$DIR"); mkdir -p "$PARENT"
FREE_MB=$(df -Pm "$PARENT" | awk 'NR==2 {print $4}')
(( FREE_MB >= 3072 )) || fail "3 Go libres nécessaires dans $PARENT (disponible : ${FREE_MB} Mo)."
ok "Espace disque : $((FREE_MB / 1024)) Go libres"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
(( MEM_MB >= 900 )) || warn "Mémoire faible (${MEM_MB} Mo). 1 Go minimum est conseillé."

# --- 2. Installation existante ------------------------------------------------------------
remove_incomplete() {
    # Une installation sans le marqueur .installed n'a jamais créé de compte : elle ne contient aucune donnée.
    command -v docker >/dev/null && compose down --volumes --remove-orphans >>"$LOG" 2>&1 || true
    local f
    for f in /etc/nginx/sites-enabled/logit.conf /etc/nginx/sites-available/logit.conf /etc/nginx/conf.d/logit.conf \
             /etc/apache2/sites-enabled/logit.conf /etc/apache2/sites-available/logit.conf /etc/caddy/logit.caddy; do
        [[ -e $f ]] && grep -q "ajouté par l'installateur" "$f" 2>/dev/null && rm -f "$f"
    done
    [[ -L /etc/nginx/sites-enabled/logit.conf ]] && rm -f /etc/nginx/sites-enabled/logit.conf
    if [[ -f /etc/caddy/Caddyfile ]]; then sed -i '\|^import /etc/caddy/logit.caddy$|d' /etc/caddy/Caddyfile; fi
    command -v nginx >/dev/null && nginx -t >>"$LOG" 2>&1 && systemctl reload nginx >>"$LOG" 2>&1 || true
    command -v apache2ctl >/dev/null && apache2ctl configtest >>"$LOG" 2>&1 && systemctl reload apache2 >>"$LOG" 2>&1 || true
    rm -rf "$DIR" /etc/logit
}

if [[ -f $DIR/.env ]]; then
    step "Installation existante détectée dans $DIR"
    if [[ ! -f $DIR/.installed ]]; then
        warn "Installation précédente interrompue avant la création du compte administrateur : elle est vide."
        ask "La supprimer et tout réinstaller ? (oui/non)" "oui"
        [[ $REPLY == oui ]] || fail "installation interrompue conservée dans $DIR. Rien n’a été modifié."
        remove_incomplete
        ok "Installation interrompue supprimée"
    elif command -v docker >/dev/null && [[ -n $(compose ps --status running -q app 2>/dev/null) ]]; then
        # Installation en service : la même commande la met à jour, avec la procédure de « logit update »
        # (sauvegarde, construction, migrations, intégrité, retour automatique en cas d'échec).
        # La procédure est prise dans la version cible, pas dans la commande « logit » déjà installée.
        ok "LogIT est déjà installé : mise à jour vers $REF"
        (umask 022 && git -C "$DIR" fetch --quiet --depth 1 origin "$REF") >>"$LOG" 2>&1 || fail "impossible de récupérer $REF depuis $LOGIT_REPO."
        NEW_COMMIT=$(git -C "$DIR" rev-parse FETCH_HEAD)
        if [[ $REF == "$LOGIT_DEFAULT_REF" && -n $LOGIT_DEFAULT_COMMIT && $NEW_COMMIT != "$LOGIT_DEFAULT_COMMIT" ]]; then
            fail "le commit de $REF ($NEW_COMMIT) ne correspond pas à l’empreinte attendue. Rien n’a été modifié."
        fi
        UPDATER=$(mktemp)
        git -C "$DIR" show "$NEW_COMMIT:deploy/logit" >"$UPDATER" || { rm -f "$UPDATER"; fail "procédure de mise à jour introuvable dans $REF."; }
        sed -i "s|^LOGIT_DIR=.*|LOGIT_DIR=$DIR|" "$UPDATER"
        UPDATE_ARGS=(update "$REF"); [[ $ASSUME_YES == 1 ]] && UPDATE_ARGS+=(--yes)
        trap - ERR
        RC=0; bash "$UPDATER" "${UPDATE_ARGS[@]}" || RC=$?
        rm -f "$UPDATER"
        exit "$RC"
    else
        fail "LogIT est installé dans $DIR mais n’est pas démarré. Lance « logit start », ou consulte « logit logs »."
    fi
fi
[[ ! -e $DIR ]] || fail "$DIR existe déjà sans installation LogIT. Choisis un autre dossier avec LOGIT_INSTALL_DIR."

# --- 3. Prérequis -------------------------------------------------------------------------
step "Prérequis"
missing=()
for p in ca-certificates curl git openssl iproute2; do installed "$p" || missing+=("$p"); done
if (( ${#missing[@]} )); then info "Installation : ${missing[*]}"; apt_install "${missing[@]}"; fi
ok "Outils système présents"

# Docker
if command -v docker >/dev/null; then
    ok "Docker présent ($(docker --version | sed 's/Docker version //; s/,.*//'))"
    if ! docker compose version >/dev/null 2>&1; then
        if [[ -f /etc/apt/sources.list.d/docker.sources || -f /etc/apt/sources.list.d/docker.list ]]; then
            info "Ajout du plugin Docker Compose"; apt_install docker-compose-plugin
        elif installed docker.io; then
            info "Ajout de Docker Compose (paquet Debian)"; apt_install docker-compose || apt_install docker-compose-plugin
            docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 introuvable. Installe le plugin docker-compose-plugin."
        else
            fail "Docker est installé sans Docker Compose v2. Installe le plugin Compose puis relance."
        fi
    fi
else
    (( WSL == 0 )) || fail "Docker est absent de WSL. Active l’intégration WSL de Docker Desktop pour cette distribution, puis relance."
    conflicts=()
    for p in docker.io docker-compose docker-doc docker-buildx podman-docker containerd runc; do installed "$p" && conflicts+=("$p"); done
    (( ${#conflicts[@]} == 0 )) || fail "paquets en conflit avec Docker Engine : ${conflicts[*]}. Retire-les (apt-get remove ${conflicts[*]}) puis relance."
    info "Installation de Docker Engine depuis le dépôt officiel Docker"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL --proto '=https' https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc >>"$LOG" 2>&1
    chmod a+r /etc/apt/keyrings/docker.asc
    cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $OS_CODE
Components: stable
Architectures: $ARCH
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    chmod 644 /etc/apt/sources.list.d/docker.sources
    APT_UPDATED=0
    apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker >>"$LOG" 2>&1
    ok "Docker installé"
fi
docker info >/dev/null 2>&1 || { (( WSL )) || systemctl start docker >>"$LOG" 2>&1; docker info >/dev/null 2>&1; } || fail "le service Docker ne répond pas."

# Heure : la date d'enregistrement des fiches vient de l'horloge de ce serveur.
if (( WSL )); then
    info "Heure : fournie par Windows (WSL)"
elif command -v timedatectl >/dev/null && timedatectl show >/dev/null 2>&1; then
    if [[ $(timedatectl show -p NTP --value) != yes ]]; then
        if ! installed systemd-timesyncd && ! installed chrony && ! installed ntpsec && ! installed ntp; then
            info "Installation de la synchronisation horaire"; apt_install systemd-timesyncd
        fi
        timedatectl set-ntp true >>"$LOG" 2>&1 || true
    fi
    if [[ $(timedatectl show -p NTP --value) == yes ]]; then ok "Synchronisation NTP active"
    else warn "Synchronisation NTP non activée : les horodatages dépendent de l’horloge locale. Vérifie avec « timedatectl »."; fi
else
    warn "Impossible de vérifier la synchronisation NTP (conteneur ?). Vérifie l’horloge de l’hôte."
fi

# --- 4. Adresses d'accès ------------------------------------------------------------------
step "Adresses d’accès"
IP=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)
FQDN=$(hostname -f 2>/dev/null || true); SHORT=$(hostname -s 2>/dev/null || true)
DEFAULT_HOSTS=$(printf '%s\n' "$IP" "$FQDN" "$SHORT" | awk 'NF && $0 != "localhost" && !seen[$0]++' | paste -sd ' ')
HOSTS=${LOGIT_INSTALL_HOSTS:-}
if [[ -z $HOSTS ]]; then
    info "Détectées : ${DEFAULT_HOSTS:-aucune}"
    ask "Adresses par lesquelles l’équipe joindra LogIT (espaces)" "${DEFAULT_HOSTS:-localhost}"
    HOSTS=$REPLY
fi
HOSTS=$(tr ', ' '  ' <<<"$HOSTS" | xargs)
[[ -n $HOSTS ]] || fail "aucune adresse d’accès."
for h in $HOSTS; do [[ $h =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || fail "adresse invalide : $h"; done
FIRST_HOST=${HOSTS%% *}
ok "$HOSTS"

# --- 5. Reverse proxy ---------------------------------------------------------------------
step "Reverse proxy"
L443=$(listener_of 443 || true); L80=$(listener_of 80 || true)
detected=none
case "${L443:-$L80}" in
    nginx*) detected=nginx ;;
    apache2*|httpd*) detected=apache ;;
    caddy*) detected=host-caddy ;;
    "") detected=none ;;
    *) detected=other ;;
esac
if [[ $PROXY_CHOICE == auto ]]; then
    case $detected in
        nginx)  [[ -d /etc/nginx ]] && command -v nginx >/dev/null && MODE=nginx || MODE=manual ;;
        apache) command -v a2ensite >/dev/null && MODE=apache || MODE=manual ;;
        host-caddy) [[ -f /etc/caddy/Caddyfile ]] && command -v caddy >/dev/null && MODE=host-caddy || MODE=manual ;;
        none) MODE=caddy ;;
        *) MODE=manual ;;
    esac
else
    MODE=$PROXY_CHOICE
fi
case $MODE in
    caddy|nginx|apache|host-caddy|manual) ;;
    *) fail "LOGIT_INSTALL_PROXY inconnu : $MODE (caddy, nginx, apache, host-caddy, manual)." ;;
esac

PUBLIC_PORT=443; HTTP_PORT=80; APP_PORT=""
case $MODE in
    caddy)
        if port_used 443 || port_used 80; then
            PUBLIC_PORT=8443; HTTP_PORT=8080
            while port_used "$PUBLIC_PORT" || port_used "$HTTP_PORT"; do PUBLIC_PORT=$((PUBLIC_PORT + 1)); HTTP_PORT=$((HTTP_PORT + 1)); done
            warn "Ports 80/443 occupés : Caddy intégré sur $HTTP_PORT/$PUBLIC_PORT."
        fi
        ok "Aucun reverse proxy détecté : Caddy intégré, HTTPS sur le port $PUBLIC_PORT" ;;
    nginx)      ok "nginx détecté : LogIT y sera ajouté comme site, sans toucher aux sites existants" ;;
    apache)     ok "Apache détecté : LogIT y sera ajouté comme site, sans toucher aux sites existants" ;;
    host-caddy) ok "Caddy (système) détecté : LogIT y sera ajouté par un fichier importé" ;;
    manual)     warn "Service inconnu sur 80/443 (${L443:-$L80}) : LogIT écoutera en local, la route sera à ajouter dans ton proxy." ;;
esac
if [[ $MODE != caddy ]]; then
    APP_PORT=8040; while port_used "$APP_PORT"; do APP_PORT=$((APP_PORT + 1)); done
    info "Application sur 127.0.0.1:$APP_PORT"
fi

# Pare-feu : information seulement, LogIT ne modifie pas tes règles.
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
    ufw status 2>/dev/null | grep -qE "^$PUBLIC_PORT(/tcp)?\s+ALLOW" || warn "Pare-feu ufw actif sans règle pour le port $PUBLIC_PORT : ufw allow $PUBLIC_PORT/tcp"
fi

# --- 6. Code source -----------------------------------------------------------------------
step "Récupération de LogIT ($REF)"
# Le code doit rester lisible par le compte non privilégié du conteneur : umask standard ici,
# seuls les secrets (.env, clé TLS, sauvegardes) sont restreints à root.
(umask 022 && git clone --quiet --depth 1 --branch "$REF" "$LOGIT_REPO" "$DIR") >>"$LOG" 2>&1 || fail "impossible de récupérer $REF depuis $LOGIT_REPO."
COMMIT=$(git -C "$DIR" rev-parse HEAD)
if [[ $REF == "$LOGIT_DEFAULT_REF" && -n $LOGIT_DEFAULT_COMMIT ]]; then
    [[ $COMMIT == "$LOGIT_DEFAULT_COMMIT" ]] || { rm -rf "$DIR"; fail "le commit de $REF ($COMMIT) ne correspond pas à l’empreinte attendue. Installation arrêtée."; }
    ok "Code vérifié : commit $COMMIT"
else
    warn "Version $REF installée sans empreinte de référence (commit $COMMIT)."
fi
chmod 755 "$DIR"

# --- 7. Secrets ---------------------------------------------------------------------------
step "Génération des secrets"
SECRET_KEY=$(random_secret 64)
DB_OWNER_PASSWORD=$(random_secret 40)
DB_APP_PASSWORD=$(random_secret 40)
PORT_SUFFIX=""; [[ $PUBLIC_PORT == 443 ]] || PORT_SUFFIX=":$PUBLIC_PORT"
COMPOSE_FILES="$DIR/deploy/compose.yaml:$DIR/deploy/compose.caddy.yaml"
[[ $MODE == caddy ]] || COMPOSE_FILES="$DIR/deploy/compose.yaml:$DIR/deploy/compose.port.yaml"
{
    echo "# LogIT — généré le $(date -Iseconds). Contient des secrets : lisible par root uniquement."
    echo "COMPOSE_FILE=$COMPOSE_FILES"
    echo "LOGIT_VERSION=$REF"
    echo "LOGIT_COMMIT=$COMMIT"
    echo "LOGIT_MODE=$MODE"
    echo "LOGIT_HOSTS=\"$HOSTS\""
    echo "LOGIT_CADDY_SITES=\"${HOSTS// /, }\""
    echo "LOGIT_DEFAULT_SNI=$FIRST_HOST"
    echo "LOGIT_PUBLIC_PORT=$PUBLIC_PORT"
    echo "LOGIT_HTTP_PORT=$HTTP_PORT"
    echo "LOGIT_PORT_SUFFIX=$PORT_SUFFIX"
    echo "LOGIT_APP_PORT=$APP_PORT"
    echo "LOGIT_TIME_ZONE=$(timedatectl show -p Timezone --value 2>/dev/null || echo Europe/Paris)"
    echo "LOGIT_SECRET_KEY=$SECRET_KEY"
    echo "LOGIT_DB_OWNER_PASSWORD=$DB_OWNER_PASSWORD"
    echo "LOGIT_DB_APP_PASSWORD=$DB_APP_PASSWORD"
} >"$DIR/.env"
chmod 600 "$DIR/.env"
ok "Secrets aléatoires écrits dans $DIR/.env (root uniquement)"

# --- 8. Construction et démarrage ---------------------------------------------------------
step "Construction et démarrage (quelques minutes la première fois)"
compose build >>"$LOG" 2>&1 || fail "la construction de l’image a échoué."
show_logs() {  # affiche la cause d'un échec de démarrage, sans secret (les journaux n'en contiennent pas)
    printf '\n%sDerniers messages des services :%s\n' "$D" "$N" >&2
    compose logs --no-color --tail 20 migrate app 2>&1 | sed 's/^/    /' >&2 || true
}
compose up -d >>"$LOG" 2>&1 || { show_logs; fail "le démarrage a échoué. Après correction, relance l’installateur."; }
wait_healthy 120 || { show_logs; fail "l’application ne démarre pas."; }
ok "Base, migrations et application démarrées"

# --- 9. Branchement sur le reverse proxy du serveur ----------------------------------------
TLS_DIR=/etc/logit/tls
make_certificate() {
    install -d -m 750 "$TLS_DIR"
    local san="" h
    for h in $HOSTS; do
        if [[ $h =~ ^[0-9.]+$ ]]; then san+="IP:$h,"; else san+="DNS:$h,"; fi
    done
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 -subj "/CN=$FIRST_HOST/O=LogIT" \
        -addext "subjectAltName=${san%,}" -keyout "$TLS_DIR/logit.key" -out "$TLS_DIR/logit.crt" >>"$LOG" 2>&1
    chmod 600 "$TLS_DIR/logit.key"
    info "Certificat auto-signé créé : $TLS_DIR/logit.crt (remplaçable par le tien)"
}

PROXY_NOTE=""
configure_nginx() {
    local conf=/etc/nginx/sites-available/logit.conf link=/etc/nginx/sites-enabled/logit.conf
    [[ -d /etc/nginx/sites-available ]] || { conf=/etc/nginx/conf.d/logit.conf; link=""; }
    [[ ! -e $conf ]] || { warn "$conf existe déjà : non modifié."; return 1; }
    make_certificate
    local v6_80="" v6_443=""
    if [[ -s /proc/net/if_inet6 ]]; then v6_80="listen [::]:80;"; v6_443="listen [::]:443 ssl;"; fi
    cat >"$conf" <<EOF
# LogIT — ajouté par l'installateur. Supprimer ce fichier retire LogIT de nginx.
server {
    listen 80;
    $v6_80
    server_name $HOSTS;
    return 308 https://\$host\$request_uri;
}
server {
    listen 443 ssl;
    $v6_443
    server_name $HOSTS;
    ssl_certificate     $TLS_DIR/logit.crt;
    ssl_certificate_key $TLS_DIR/logit.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 60m;  # 10 captures de 5 Mo
    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOF
    [[ -z $link ]] || ln -s "$conf" "$link"
    if nginx -t >>"$LOG" 2>&1; then
        systemctl reload nginx >>"$LOG" 2>&1 && return 0
    fi
    rm -f "$conf" ${link:+"$link"}; nginx -t >>"$LOG" 2>&1 && systemctl reload nginx >>"$LOG" 2>&1 || true
    warn "nginx a refusé la configuration LogIT : retirée, nginx est resté dans son état d’origine."
    return 1
}

configure_apache() {
    local conf=/etc/apache2/sites-available/logit.conf
    [[ ! -e $conf ]] || { warn "$conf existe déjà : non modifié."; return 1; }
    make_certificate
    local enabled_mods
    enabled_mods=$(apache2ctl -M 2>/dev/null || true)
    local mods=()
    for m in proxy proxy_http ssl headers rewrite; do grep -q " ${m}_module" <<<"$enabled_mods" || mods+=("$m"); done
    local first=$FIRST_HOST aliases=${HOSTS#"$FIRST_HOST"}
    cat >"$conf" <<EOF
# LogIT — ajouté par l'installateur. « a2dissite logit » retire LogIT d'Apache.
<VirtualHost *:80>
    ServerName $first
    ${aliases:+ServerAlias$aliases}
    RewriteEngine On
    RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=308,L]
</VirtualHost>
<VirtualHost *:443>
    ServerName $first
    ${aliases:+ServerAlias$aliases}
    SSLEngine on
    SSLCertificateFile    $TLS_DIR/logit.crt
    SSLCertificateKeyFile $TLS_DIR/logit.key
    ProxyPreserveHost On
    ProxyPass        / http://127.0.0.1:$APP_PORT/
    ProxyPassReverse / http://127.0.0.1:$APP_PORT/
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Real-IP "%{REMOTE_ADDR}s"
    LimitRequestBody 62914560
</VirtualHost>
EOF
    (( ${#mods[@]} == 0 )) || a2enmod -q "${mods[@]}" >>"$LOG" 2>&1
    a2ensite -q logit >>"$LOG" 2>&1
    if apache2ctl configtest >>"$LOG" 2>&1; then
        systemctl reload apache2 >>"$LOG" 2>&1 && { (( ${#mods[@]} == 0 )) || info "Modules Apache activés : ${mods[*]}"; return 0; }
    fi
    a2dissite -q logit >>"$LOG" 2>&1 || true; rm -f "$conf"
    (( ${#mods[@]} == 0 )) || a2dismod -q "${mods[@]}" >>"$LOG" 2>&1 || true
    apache2ctl configtest >>"$LOG" 2>&1 && systemctl reload apache2 >>"$LOG" 2>&1 || true
    warn "Apache a refusé la configuration LogIT : retirée, Apache est resté dans son état d’origine."
    return 1
}

configure_host_caddy() {
    local main=/etc/caddy/Caddyfile site=/etc/caddy/logit.caddy backup
    [[ ! -e $site ]] || { warn "$site existe déjà : non modifié."; return 1; }
    cat >"$site" <<EOF
# LogIT — ajouté par l'installateur.
${HOSTS// /, } {
    tls internal
    reverse_proxy 127.0.0.1:$APP_PORT {
        header_up X-Real-IP {remote_host}
    }
}
EOF
    backup="$main.avant-logit.$(date +%Y%m%d%H%M%S)"
    cp -p "$main" "$backup"
    grep -qF "import $site" "$main" || printf '\nimport %s\n' "$site" >>"$main"
    if caddy validate --config "$main" --adapter caddyfile >>"$LOG" 2>&1 && systemctl reload caddy >>"$LOG" 2>&1; then
        info "Caddyfile d’origine sauvegardé : $backup"; return 0
    fi
    cp -p "$backup" "$main"; rm -f "$site"; systemctl reload caddy >>"$LOG" 2>&1 || true
    warn "Caddy a refusé la configuration LogIT : Caddyfile restauré à l’identique."
    return 1
}

if [[ $MODE != caddy ]]; then
    step "Branchement sur le reverse proxy ($MODE)"
    case $MODE in
        nginx) configure_nginx && ok "Site LogIT ajouté à nginx" || MODE=manual ;;
        apache) configure_apache && ok "Site LogIT ajouté à Apache" || MODE=manual ;;
        host-caddy) configure_host_caddy && ok "Site LogIT ajouté à Caddy" || MODE=manual ;;
    esac
    sed -i "s/^LOGIT_MODE=.*/LOGIT_MODE=$MODE/" "$DIR/.env"
    if [[ $MODE == manual ]]; then
        PROXY_NOTE="Ajoute dans ton reverse proxy une route HTTPS vers http://127.0.0.1:$APP_PORT avec les en-têtes Host (d’origine), X-Forwarded-Proto: https et X-Real-IP (IP du client)."
    fi
fi

# Vérification de bout en bout, à travers le proxy.
if [[ $MODE != manual ]]; then
    if curl -fsk --max-time 10 --resolve "$FIRST_HOST:$PUBLIC_PORT:127.0.0.1" "https://$FIRST_HOST:$PUBLIC_PORT/sante/" >/dev/null 2>&1; then
        ok "LogIT répond en HTTPS sur https://$FIRST_HOST$PORT_SUFFIX/"
    else
        warn "LogIT ne répond pas encore en HTTPS via le proxy. Diagnostic : logit status"
    fi
fi

# --- 10. Compte administrateur, outil d'exploitation, sauvegardes ------------------------
step "Compte administrateur et exploitation"
ADMIN_OUT=$(compose exec -T app logit-entrypoint bootstrap_admin)
ADMIN_USER=$(sed -n 's/^IDENTIFIANT=//p' <<<"$ADMIN_OUT")
ADMIN_PASSWORD=$(sed -n 's/^MOT_DE_PASSE=//p' <<<"$ADMIN_OUT")
[[ -n $ADMIN_PASSWORD ]] || fail "création du compte administrateur impossible : $ADMIN_OUT"
ok "Compte $ADMIN_USER créé (mot de passe à changer, TOTP obligatoire)"

install -m 0755 "$DIR/deploy/logit" /usr/local/bin/logit
sed -i "s|^LOGIT_DIR=.*|LOGIT_DIR=$DIR|" /usr/local/bin/logit
install -d -m 700 /var/backups/logit
cat >/etc/cron.d/logit <<EOF
# LogIT : sauvegarde quotidienne, 30 jours conservés.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 2 * * * root /usr/local/bin/logit backup --quiet
EOF
chmod 644 /etc/cron.d/logit
if logit backup --quiet; then ok "Commande « logit » installée, première sauvegarde faite, sauvegarde chaque nuit à 2 h 17"
else warn "Première sauvegarde impossible : vérifie « logit backup »."; fi

date -Iseconds >"$DIR/.installed"

# --- 11. Récapitulatif --------------------------------------------------------------------
trap - ERR
URLS=""; for h in $HOSTS; do URLS+="https://$h$PORT_SUFFIX/  "; done
cat <<EOF

${G}${B}LogIT est installé.${N}

  Accès         : $URLS
  Dossier       : $DIR
  Mode proxy    : $MODE
  Exploitation  : logit status | logs | backup | restore | verify

${B}┌─ À enregistrer maintenant dans KeePass ─────────────────────────────────${N}
${B}│${N} Entrée « LogIT — administrateur »
${B}│${N}   URL          https://$FIRST_HOST$PORT_SUFFIX/
${B}│${N}   Identifiant  $ADMIN_USER
${B}│${N}   Mot de passe $ADMIN_PASSWORD
${B}│${N}   (temporaire : à changer à la première connexion, puis TOTP à activer)
${B}│${N}
${B}│${N} Entrée « LogIT — base de données (secours) »
${B}│${N}   Propriétaire  logit_owner / $DB_OWNER_PASSWORD
${B}│${N}   Application   logit_app / $DB_APP_PASSWORD
${B}│${N}
${B}│${N} Entrée « LogIT — clé de l’application »
${B}│${N}   LOGIT_SECRET_KEY  $SECRET_KEY
${B}└──────────────────────────────────────────────────────────────────────────${N}
  Le mot de passe administrateur ne sera plus jamais affiché : il n’est stocké nulle part en clair.
  Les autres secrets restent dans $DIR/.env (root uniquement), nécessaire pour restaurer une sauvegarde.
EOF
if [[ $MODE == caddy || -f $TLS_DIR/logit.crt ]]; then
    printf '\n  Certificat : auto-signé. Pour éviter l’alerte du navigateur, importe sur les postes : '
    [[ $MODE == caddy ]] && printf 'logit ca > logit-ca.crt\n' || printf '%s\n' "$TLS_DIR/logit.crt"
fi
[[ -z $PROXY_NOTE ]] || printf '\n  %sÀ faire :%s %s\n' "$Y" "$N" "$PROXY_NOTE"
if (( ${#WARNINGS[@]} )); then
    printf '\n  %sPoints d’attention :%s\n' "$Y" "$N"
    for w in "${WARNINGS[@]}"; do printf '   - %s\n' "$w"; done
fi
printf '\n'
