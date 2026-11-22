# AAMP is linked against this library. As RDK-E builds it, it needs the
# Firebolt SDK for AAMP (FireboltAamp), which the public layers do not have
# (RDK-E's configuration takes the library out for that reason, "until
# RDKMVE-2474 gets resolved"). Here it is built as the source builds it on a
# desktop: without a way to ask the device about its display and outputs, and
# so without content protection that depends on the answer.
FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"
SRC_URI:append:tvemu = " file://0001-tvemu-build-without-a-device-backend.patch"
EXTRA_OECMAKE:remove:tvemu = "-DCMAKE_USE_FIREBOLT=1"
EXTRA_OECMAKE:append:tvemu = " -DCMAKE_USE_FIREBOLT=0 -DCMAKE_NO_DEVICE_BACKEND=1"
