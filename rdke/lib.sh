# Shared by check-parse.sh and build.sh: where things are, RDK-E's common
# layers at the versions its vendor manifest names, and the container that
# bitbake runs in (bitbake runs on Linux only).
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work="$here/../build/rdke-check"
layers="$work/layers"
runtime=${EMU_CONTAINER_RUNTIME:-$(command -v docker >/dev/null 2>&1 && echo docker || echo podman)}
mkdir -p "$layers"

# Repository, tag, directory: as in rdke-common-layers.xml and
# rdke-configs-layers.xml of rdke-generic-manifest 1.1.1, and
# vendor-manifest-raspberrypi (develop, 2026-11-20).
fetch() {
  [ -d "$layers/$3" ] || git -c advice.detachedHead=false clone -q --depth 1 -b "$2" \
    "https://github.com/rdkcentral/$1.git" "$layers/$3"
}
fetch poky rdk-4.7.0 poky
fetch meta-openembedded rdk-4.0.0 meta-openembedded
fetch meta-stack-layering-support 5.0.4 meta-stack-layering-support
fetch meta-rdk-auxiliary 1.10.1 meta-rdk-auxiliary
fetch rdke-common-config 1.0.26 common
fetch rdke-stb-config 1.0.0 profile
fetch meta-rdk-oss-reference 4.14.1 meta-rdk-oss-reference
fetch meta-rdk-halif-headers 5.0.0_hotfix meta-rdk-halif-headers
fetch meta-image-support-rdke 1.0.0 meta-image-support-rdke
# For its local.conf template only; the Pi's recipes are not in the build.
fetch meta-vendor-raspberrypi-dev develop meta-vendor-raspberrypi-dev

# Local changes to what was fetched. Each is needed for a build, not for the
# parse, and is said in README.md.
#
# 1. pseudo, Yocto's fake-root tool: RDK's poky has 1.9.0, which loses track
#    of a directory in the first packaging step of a build in this container
#    ("got *at() syscall for unknown directory"). openembedded-core's own
#    kirkstone branch has 1.9.3, which does not.
if ! grep -q 43cbd8fb4914328094ccdb4bb827d74b1bac2046 "$layers/poky/meta/recipes-devtools/pseudo/pseudo_git.bb"; then
  [ -d "$work/oe-core" ] || git -c advice.detachedHead=false clone -q --depth 1 -b kirkstone --filter=blob:none \
    --sparse https://github.com/openembedded/openembedded-core.git "$work/oe-core"
  git -C "$work/oe-core" sparse-checkout set meta/recipes-devtools/pseudo >/dev/null
  rm -rf "$layers/poky/meta/recipes-devtools/pseudo"
  cp -R "$work/oe-core/meta/recipes-devtools/pseudo" "$layers/poky/meta/recipes-devtools/pseudo"
fi

# RDK-E's middleware layers, for the scripts that ask for them. Repository,
# revision, directory: rdke-middleware.xml of middleware-manifest-rdke
# (develop, 2026-11-20) and, through rdke-middleware-generic-manifest
# 4c83776, middleware-generic.xml.
# The reference stream that the browser image plays (tvemu-media): the H.264
# and AAC stream of the emulator's media checks, made here as the Debian
# target's build makes it (target/media/build-media.sh, in target/Dockerfile's
# base image with its FFmpeg). It is data that a build makes, and is not kept
# in the repository.
MEDIA_SHA256=0f236ef37b7a6ab1960b0aff0696fd29c4dd1b27b71c59a26a4fd6021b00c125
fetch_media() {
  media="$here/meta-tvemu-rdke/recipes-apps/tvemu-media/files/avc.mp4"
  [ -f "$media" ] && return 0
  echo "making the reference stream avc.mp4 (target/media/build-media.sh)"
  "$runtime" run --rm -v "$here/../target/media:/src/media:ro" docker.io/library/debian:trixie-slim sh -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq > /dev/null && apt-get install -y -qq --no-install-recommends ffmpeg python3 > /dev/null &&
    sh /src/media/build-media.sh /src/media /out > /dev/null && cat /out/avc.mp4' > "$media.new" || {
    rm -f "$media.new"; echo "the reference stream could not be made" >&2; return 1; }
  mv -f "$media.new" "$media"
  found=$( (sha256sum "$media" 2>/dev/null || shasum -a 256 "$media") | cut -d" " -f1)
  [ "$found" = "$MEDIA_SHA256" ] || echo "note: avc.mp4 is not the stream the checks were written with" \
    "(sha256 $found): another FFmpeg made it" >&2
}

fetch_middleware() {
  mw="$work/middleware"
  mkdir -p "$mw"
  at() {
    [ -d "$mw/$3" ] && return 0
    git init -q "$mw/$3"
    git -C "$mw/$3" fetch -q --depth 1 "https://github.com/rdkcentral/$1.git" "$2"
    git -C "$mw/$3" -c advice.detachedHead=false checkout -q FETCH_HEAD
  }
  at meta-middleware-generic-support 46301078413a1c8210188c52afa43939b5b0a075 meta-middleware-generic-support
  at meta-rdk 222d55d56090f0cd0cb5ae99ab37f08ff9d7a87a meta-rdk
  at meta-rdk-video b855acce6070a59569613a663f78d18fc3104c93 meta-rdk-video
  at meta-rdk-oss-ext-middleware 7475e5490a14a0b90246ae91d93b6e85bd2ac4c0 meta-rdk-oss-ext-middleware
  at meta-rdk-bluetooth refs/tags/1.1.0 meta-rdk-bluetooth
  at meta-python2 refs/tags/rdk-4.0.0 meta-python2
  at meta-oss-common-config refs/tags/1.4.0 meta-oss-common-config
}

cat > "$work/Dockerfile" <<'EOT'
FROM ubuntu:22.04
# python-is-python3: a script of RDK's voice SDK is started as "python".
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gawk wget git diffstat unzip texinfo gcc g++ make build-essential chrpath socat cpio python3 python3-pip \
    python3-pexpect xz-utils debianutils iputils-ping python3-git python3-jinja2 python3-subunit zstd lz4 file \
    locales ca-certificates python-is-python3 && locale-gen en_US.UTF-8 && useradd -m builder
USER builder
WORKDIR /home/builder
# Some of RDK's recipes name their sources with the git protocol, which
# GitHub no longer serves (RDK's own builds fetch through a mirror).
RUN git config --global url."https://github.com/".insteadOf git://github.com/
EOT
"$runtime" build -q -t tvemu-rdke-check "$work" >/dev/null

# The build configuration, written by a script in the container: the Pi's
# local.conf template, and the Pi's layers and their order with this layer in
# place of the Pi's product, vendor and board support layers.
cat > "$work/configure.sh" <<'EOT'
L=/work/rdk/layers
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
source $L/poky/oe-init-build-env "$1" >/dev/null
sed -e "s/##MACHINE##/tvemu-arm64-rdke/" -e "s/##DISTRO_CODENAME##/kirkstone/g" \
    $L/meta-vendor-raspberrypi-dev/conf/template/local.conf.sample > conf/local.conf
cat >> conf/local.conf <<EOC
RDK_TOOLS_PACKAGES = ""
LAYER_SRC_MODE = "0"
MULTICONFIG = ""
INHERIT:remove = "buildhistory"
TVEMU_USERLAND = "$2"
EOC
if [ "${3:-}" = middleware ]; then
# With RDK-E's middleware: the layers and their order of meta-rdk's
# bblayers.conf.sample, with this layer as the product and vendor layer. The
# middleware layers set the distro "rdk", which has its own version of the
# build configuration (meta-rdk, local.conf.sample).
M=/work/rdk/middleware
echo 'CONF_VERSION = "1"' >> conf/local.conf
cat > conf/bblayers.conf <<EOC
LCONF_VERSION = "6"
BBPATH = "\${TOPDIR}"
BBFILES ?= ""
RDKROOT = "/work/rdk"
BBLAYERS = " \
  $L/profile $L/common /work/meta-tvemu-rdke $M/meta-python2 $M/meta-rdk-video $M/meta-rdk \
  $M/meta-middleware-generic-support $M/meta-rdk-oss-ext-middleware $M/meta-rdk-bluetooth \
  $L/meta-image-support-rdke $M/meta-oss-common-config $L/meta-rdk-halif-headers \
  $L/meta-stack-layering-support $L/meta-rdk-oss-reference \
  $L/poky/meta $L/meta-openembedded/meta-oe $L/meta-openembedded/meta-python \
  $L/meta-openembedded/meta-webserver $L/meta-openembedded/meta-multimedia \
  $L/meta-openembedded/meta-networking $L/meta-rdk-auxiliary \
"
EOC
else
cat > conf/bblayers.conf <<EOC
LCONF_VERSION = "6"
BBPATH = "\${TOPDIR}"
BBFILES ?= ""
RDKROOT = "/work/rdk"
BBLAYERS = " \
  $L/meta-image-support-rdke /work/meta-tvemu-rdke $L/meta-rdk-oss-reference $L/profile $L/common \
  $L/meta-rdk-halif-headers $L/poky/meta $L/meta-openembedded/meta-oe $L/meta-openembedded/meta-python \
  $L/meta-openembedded/meta-multimedia $L/meta-openembedded/meta-networking \
  $L/meta-stack-layering-support $L/meta-rdk-auxiliary \
"
EOC
fi
EOT
