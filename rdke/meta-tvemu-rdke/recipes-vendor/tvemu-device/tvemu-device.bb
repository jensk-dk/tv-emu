SUMMARY = "The virtual device's identity and the state that stands in for its sensors"
DESCRIPTION = "What a board has in its firmware and its sensors, the VM has in files: a serial number, \
a hardware revision and the description of the television it is connected to (/etc/tvemu), and a temperature \
(/run/tvemu, made at each start). The vendor layer's components read them."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://cpuinfo file://serial-number file://tvemu-device.conf file://make-edid.py"
S = "${WORKDIR}"

inherit python3native

# The display's description (EDID) is made, not kept as a binary file: the
# script says what is in it.
do_compile() {
    python3 ${WORKDIR}/make-edid.py ${B}/edid
}

do_install() {
    install -d ${D}${sysconfdir}/tvemu ${D}${sysconfdir}/tmpfiles.d
    install -m 0644 ${WORKDIR}/cpuinfo ${WORKDIR}/serial-number ${D}${sysconfdir}/tvemu/
    install -m 0644 ${B}/edid ${D}${sysconfdir}/tvemu/edid
    install -m 0644 ${WORKDIR}/tvemu-device.conf ${D}${sysconfdir}/tmpfiles.d/tvemu-device.conf
}

FILES:${PN} = "${sysconfdir}/tvemu ${sysconfdir}/tmpfiles.d"
