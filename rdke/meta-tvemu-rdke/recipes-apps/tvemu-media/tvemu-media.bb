SUMMARY = "A reference stream and a page that plays it, to try video and sound on"
DESCRIPTION = "The H.264 and AAC reference stream of the emulator's media checks (avc.mp4: 1280x720, 25 \
frames a second, 5 seconds, a moving test pattern with marker blocks in its corners and an 880 Hz tone; \
target/media/build-media.sh makes it, and rdke/build.sh puts it here) and a page that plays it in a loop \
and says in its address what the player reports. The same stream as an HLS stream (hls.m3u8 and hls/, five \
segments of a second, which rdke/build.sh makes from avc.mp4) and a page that plays that one with RDK's \
player, AAMP. The browser gives AAMP's object to pages that have a host in their address only, so the \
image's web server serves the directory too: http://127.0.0.1:50050/tvemu-media/aamp.html."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avc.mp4 file://video.html file://aamp.html file://hls.m3u8 file://hls"
S = "${WORKDIR}"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${datadir}/tvemu/media
    install -m 0644 ${WORKDIR}/avc.mp4 ${WORKDIR}/video.html ${D}${datadir}/tvemu/media/
    install -m 0644 ${WORKDIR}/aamp.html ${WORKDIR}/hls.m3u8 ${D}${datadir}/tvemu/media/
    install -d ${D}${datadir}/tvemu/media/hls
    install -m 0644 ${WORKDIR}/hls/avc.m3u8 ${WORKDIR}/hls/avc-*.ts ${D}${datadir}/tvemu/media/hls/
    # The document root of the image's web server (lighttpd, on the target's loopback address).
    install -d ${D}/opt/www
    ln -s ${datadir}/tvemu/media ${D}/opt/www/tvemu-media
}

FILES:${PN} = "${datadir}/tvemu/media /opt/www/tvemu-media"
