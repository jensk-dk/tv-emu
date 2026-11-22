SUMMARY = "Westeros' video sink for decoded frames (westerosrawsink), for the VM"
DESCRIPTION = "A device's vendor layer gives GStreamer the element westerossink, which decodes video in \
the device's hardware and shows it through Westeros. The virtual machine has no video decoder: FFmpeg \
decodes on the CPU (see ffmpeg_%.bbappend). This is the variant of the same sink that takes decoded \
frames (its directory raw) and hands them to the Westeros compositor in buffers of the DRM device. \
GStreamer's playbin finds it by its rank, so a player that leaves the video sink to playbin (AAMP \
without AAMP_ENABLE_WESTEROS_SINK) shows its video with it."

require recipes-graphics/westeros/westeros.inc

LICENSE = "LGPL-2.1-only"
LICENSE_LOCATION = "${S}/../COPYING.LGPL"
LIC_FILES_CHKSUM = "file://${LICENSE_LOCATION};md5=683c7039c56b9e142f0779236233a953"

SRC_URI = "${WESTEROS_SINK_URI} \
           file://0001-raw-dumb-buffers-of-32-bits-per-pixel.patch;patchdir=.. \
           "
SRCREV_FORMAT = "westeros-sink"
S = "${WORKDIR}/git/raw"

COMPATIBLE_MACHINE = "tvemu"

PROVIDES = "virtual/vendor-westeros-sink"
RPROVIDES:${PN} = "virtual/vendor-westeros-sink"

DEPENDS = "gstreamer1.0 gstreamer1.0-plugins-base glib-2.0 wayland wayland-native libdrm virtual/libgbm \
           westeros westeros-simplebuffer westeros-simpleshell essosrmgr"

inherit autotools pkgconfig

EXTRA_OECONF = "--enable-gstreamer1=yes"
CFLAGS:append = " -DWESTEROS_PLATFORM_DRM -I${STAGING_INCDIR}/libdrm -x c++"
# virtio-gpu makes dumb buffers of 32 bits per pixel only (see the patch).
CFLAGS:append = " -DWST_DUMB_BYTES_PER_PIXEL=4"

do_configure:prepend() {
    ln -sf ../westeros-sink.c ${S}/
    ln -sf ../westeros-sink.h ${S}/
    ln -sf ../westeros-sink-version.h ${S}/
    # The variant's Makefile names another variant's library in a branch that is not built.
    sed -i -e 's/^libgstwesterossink_la_SOURCES +=/libgstwesterosrawsink_la_SOURCES +=/' ${S}/Makefile.am
    sed -i -e 's/-lwesteros_simplebuffer_client/-lwesteros_compositor -lwesteros_simplebuffer_client/g' ${S}/Makefile.am
}

FILES:${PN} += "${libdir}/gstreamer-*/*.so"
FILES:${PN}-dev += "${libdir}/gstreamer-*/*.la"
FILES:${PN}-dbg += "${libdir}/gstreamer-*/.debug/*"
FILES:${PN}-staticdev += "${libdir}/gstreamer-*/*.a"
