# 64-bit programs: the DIAL server's platform library calls basename() with no
# declaration, and the pointer it gets back is cut to 32 bits (see the patch).
FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"
SRC_URI:append:tvemu = " file://0001-basename-is-declared-before-it-is-called.patch"

# So that another call of this kind is an error in the build and not a
# segmentation fault in the VM.
CFLAGS:append:aarch64 = " -Werror=implicit-function-declaration"
