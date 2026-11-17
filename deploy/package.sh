#!/usr/bin/env bash
set -euo pipefail

release=${1:?Version attendue, par exemple v1.0.0}
revision=${2:?Révision Git à empaqueter}
output=${3:?Répertoire de sortie à créer}
origin=${4:-https://logit.kyoshiro.ovh}

[[ $release =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && $origin =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || exit 2
commit=$(git rev-parse --verify "$revision^{commit}")
mkdir -- "$output"
release_dir="$output/releases/$release"
mkdir -p -- "$release_dir"
archive="$release_dir/logit.tar.gz"
git archive --format=tar.gz --output="$archive" "$commit"
digest=$(sha256sum "$archive")
digest=${digest%% *}
git show "$commit:deploy/install.sh" |
    sed -e "s|@LOGIT_RELEASE@|$release|" -e "s|@LOGIT_SHA256@|$digest|" -e "s|@LOGIT_ORIGIN@|$origin|" > "$output/install.sh"
cp -- "$output/install.sh" "$release_dir/install.sh"
printf 'Version %s · Git %s · SHA-256 %s\n' "$release" "$commit" "$digest"
