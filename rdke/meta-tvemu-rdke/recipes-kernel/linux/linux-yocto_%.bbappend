# The kernel of tvemu-arm64-rdke and tvemu-x86-64-rdke: openembedded-core's
# kernel for qemuarm64 or qemux86-64, with what RDK-E expects of a kernel and
# what tv-emu's VM has as devices.

FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"

# The QEMU machine's kernel configuration is the base.
COMPATIBLE_MACHINE:tvemu = "tvemu-arm64-rdke|tvemu-x86-64-rdke"
KMACHINE:tvemu = "qemuarm64"
KMACHINE:tvemu:qemux86-64 = "qemux86-64"

SRC_URI:append:tvemu = " \
    file://tvemu-virt.cfg \
    file://rdke-android.cfg \
    file://rdke.cfg \
    file://rdke-apparmor.cfg \
"
# What only one of the two boards has.
SRC_URI:append:tvemu:qemuarm64 = " file://tvemu-virt-arm64.cfg"
SRC_URI:append:tvemu:qemux86-64 = " file://tvemu-virt-x86-64.cfg"

# openembedded-core adds its sound options for qemux86-64 after the files
# above, and they make ALSA a set of modules (CONFIG_SND=m), which takes the
# built-in virtio sound driver with it: the target had no sound card. The
# machine has its sound from tvemu-virt.cfg, as the ARM64 one does.
KERNEL_FEATURES:remove:tvemu = "cfg/sound.scc"
