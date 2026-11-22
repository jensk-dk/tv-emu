# RDK builds FFmpeg with audio decoders only: a device decodes video in its
# hardware, behind the vendor's video sink. The virtual machine has no video
# decoder, so the video decoders that the target's CPU can stand in with are
# added here, for GStreamer's FFmpeg plug-in (avdec_h264 and the others).
EXTRA_OECONF:append:tvemu = " \
    --enable-decoder=h264 --enable-parser=h264 \
    --enable-decoder=hevc --enable-parser=hevc \
    --enable-decoder=mpeg2video --enable-parser=mpegvideo \
    --enable-decoder=vp8 --enable-parser=vp8 \
    --enable-decoder=vp9 --enable-parser=vp9 \
    "
