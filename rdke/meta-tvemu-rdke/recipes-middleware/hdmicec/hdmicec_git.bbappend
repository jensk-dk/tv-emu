# RDK's HDMI-CEC library, for a device whose CEC driver cannot be opened: the
# VM has no CEC adapter (/dev/cec0), and the library's reader thread then kept
# one CPU busy (see the patch).
FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"
SRC_URI:append:tvemu = " file://0001-tvemu-reader-waits-when-the-driver-is-not-open.patch"
