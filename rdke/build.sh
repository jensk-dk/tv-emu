#!/bin/bash
# Builds a minimal image for the machine tvemu-arm64-rdke or
# tvemu-x86-64-rdke: openembedded-core's core-image-minimal on RDK-E's common
# layers (its base system, its systemd), with this machine's kernel. No RDK
# middleware, and no vendor layer.
#
#   rdke/build.sh [--arch arm64|x86_64] [--middleware] [64|32] [BITBAKE TARGET ...]
#
# --arch names the machine's CPU. The default is the host's own, whose
# programs a host-native VM runs; the other one runs on a simulated CPU.
#
# --middleware adds RDK-E's middleware layers to the build (Thunder and the
# rest), which also makes the distro RDK's own: a build directory of its own,
# and nearly everything is built again for it.
#
# 64 (the default) builds 64-bit programs, which a host-native VM on a Mac
# needs; 32 is RDK-E's own arrangement (see README.md). The build runs in an
# Ubuntu 22.04 container and keeps its work (downloads, shared state, tmp) in
# the container engine's volume "tvemu-rdke-build", since Yocto needs a Linux
# file system: 30 GB and more, and hours the first time. The kernel and the
# root file system are then copied to build/rdke/ARCH, where
# "emu run --mode vm --rootfs rdke" looks for them.
set -eu
if [ "${1:-}" = --arch ]; then
  export TVEMU_RDKE_ARCH=${2:?--arch needs arm64 or x86_64}
  shift 2
fi
. "$(dirname -- "$0")/lib.sh"
layers_kind=""
if [ "${1:-}" = --middleware ]; then
  layers_kind=middleware
  shift
  fetch_middleware
  fetch_media
fi
userland=${1:-64}
[ $# -gt 0 ] && shift
targets=${*:-core-image-minimal}
if [ "$arch" = x86_64 ] && [ "$userland" != 64 ]; then
  echo "the x86-64 machine has 64-bit programs only" >&2; exit 2
fi
out="$here/../build/rdke/$arch"
mkdir -p "$out"

cat > "$work/build-in-container.sh" <<'EOT'
#!/bin/bash
userland=$1; kind=$2; shift 2
cd /build
# The ARM64 machine's build directory has the name it had before there was
# another machine.
directory=build-$userland${kind:+-$kind}
[ "$TVEMU_MACHINE" = tvemu-arm64-rdke ] || directory=build-${TVEMU_MACHINE#tvemu-}-$userland${kind:+-$kind}
. /work/rdk/configure.sh /build/$directory "$userland" "$kind"
cat >> conf/local.conf <<EOC
DL_DIR = "/build/downloads"
SSTATE_DIR = "/build/sstate-cache"
# The work of a recipe is removed when it is built: the volume is small.
INHERIT += "rm_work"
BB_NUMBER_THREADS = "4"
PARALLEL_MAKE = "-j 6"
# LLVM (for Mesa's software renderer) links several large programs at once
# and was ended for want of memory in an engine with 8 GB.
PARALLEL_MAKE:pn-llvm = "-j 3"
EXTRA_OECMAKE:append:pn-llvm = " -DLLVM_PARALLEL_LINK_JOBS=1"
# WebKit, for the same reason: fewer compilers at once, and no link-time
# optimisation, whose link takes more memory than the engine has.
PARALLEL_MAKE:pn-wpe-webkit = "-j 2"
WPE_WEBKIT_LTO:pn-wpe-webkit = ""
EOC
[ -f /work/rdk/local-extra.conf ] && cat /work/rdk/local-extra.conf >> conf/local.conf
bitbake "$@"
EOT
# The copy runs apart from the build, as the container's root: the build's
# user is the container's own (bitbake refuses to run as root), and it can
# write to the host's directory only where the host's user happens to have
# its number. The files get the owner of the directory they are copied to,
# which is the host's user, or root where the engine maps that to the host's
# user (rootless).
cat > "$work/copy-in-container.sh" <<'EOT'
#!/bin/bash
set -e
userland=$1; kind=$2
directory=build-$userland${kind:+-$kind}
[ "$TVEMU_MACHINE" = tvemu-arm64-rdke ] || directory=build-${TVEMU_MACHINE#tvemu-}-$userland${kind:+-$kind}
deploy=/build/$directory/tmp/deploy/images/$TVEMU_MACHINE
kernel=$([ "$TVEMU_MACHINE" = tvemu-arm64-rdke ] && echo Image || echo bzImage)
# Each as a new file that takes the old one's name: a VM that is running
# keeps the image it started from.
place() {
  cp -L "$1" "/out/$2.new"
  chown --reference=/out "/out/$2.new"
  mv -f "/out/$2.new" "/out/$2"
}
place $deploy/$kernel $kernel
image=$(ls -t $deploy/*.ext4 | head -1)
place "$image" rootfs.ext4
echo "copied $kernel and $(basename "$image") (as rootfs.ext4)"
EOT
chmod +x "$work/build-in-container.sh" "$work/copy-in-container.sh"

"$runtime" volume create tvemu-rdke-build >/dev/null
"$runtime" run --rm --user root -v tvemu-rdke-build:/build tvemu-rdke-check chown builder:builder /build
"$runtime" run --rm -v "$work:/work/rdk:ro" -v "$here/meta-tvemu-rdke:/work/meta-tvemu-rdke:ro" \
  -v tvemu-rdke-build:/build -e TVEMU_MACHINE tvemu-rdke-check /work/rdk/build-in-container.sh "$userland" "$layers_kind" $targets
"$runtime" run --rm --user root -v "$work:/work/rdk:ro" -v tvemu-rdke-build:/build:ro -v "$out:/out" \
  -e TVEMU_MACHINE tvemu-rdke-check /work/rdk/copy-in-container.sh "$userland" "$layers_kind"
