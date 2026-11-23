# 64-bit programs only: no multilib. The targets are then named without the
# Pi's "lib32-" prefix (packagegroup-vendor-layer, vendor-test-image), and the
# Pi's 32-bit middleware and application package feeds do not fit: those
# layers have to be built for this machine.
#
# "tvemu64" is the override for what a 64-bit build needs of RDK-E's sources,
# whichever the CPU (ARM64 or x86-64): mostly formats and casts that fit a
# 32-bit build only (recipes-middleware).
MACHINEOVERRIDES .= ":tvemu64"
