#!/usr/bin/env python3
"""Writes the virtual device's description of its display (EDID): a television
with 1920x1080 at 60 pictures a second as its own mode. The VM's monitor comes
without one (tv-emu's launcher leaves QEMU's out, since its first mode is 75
pictures a second), and RDK's device settings read the television's supported
resolutions, its name and its sound formats from the description.

  make-edid.py FILE

A base block (EDID 1.3) and one CTA-861 extension block, 256 bytes."""
import sys


def closed(block):
    """`block` (127 bytes) with the byte that makes its sum a multiple of 256."""
    assert len(block) == 127, len(block)
    return bytes(block) + bytes([(-sum(block)) % 256])


def timing(clock_khz, h, h_blank, v, v_blank, h_front, h_sync, v_front, v_sync, width_mm, height_mm):
    """A detailed timing descriptor, progressive, both sync signals positive."""
    clock = clock_khz // 10
    return bytes([clock & 255, clock >> 8,
                  h & 255, h_blank & 255, (h >> 8) << 4 | h_blank >> 8,
                  v & 255, v_blank & 255, (v >> 8) << 4 | v_blank >> 8,
                  h_front & 255, h_sync & 255, v_front << 4 | v_sync,
                  (h_front >> 8) << 6 | (h_sync >> 8) << 4,
                  width_mm & 255, height_mm & 255, (width_mm >> 8) << 4 | height_mm >> 8,
                  0, 0, 0x1E])


def text(tag, value):
    return bytes([0, 0, 0, tag, 0]) + (value.encode("ascii") + b"\n").ljust(13, b" ")[:13]


def base():
    maker = "TVE"                               # not a registered manufacturer's code
    code = (ord(maker[0]) - 64) << 10 | (ord(maker[1]) - 64) << 5 | (ord(maker[2]) - 64)
    block = bytes([0, 255, 255, 255, 255, 255, 255, 0, code >> 8, code & 255,
                   1, 0,                        # product code
                   1, 0, 0, 0,                  # serial number
                   1, 2026 - 1990,              # week and year of manufacture
                   1, 3,                        # EDID 1.3
                   0x80,                        # a digital input
                   160, 90,                     # the picture's size in cm
                   120,                         # gamma 2.2
                   0x0A,                        # RGB; the first detailed timing is the display's own mode
                   0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54,     # sRGB's colours
                   0x21, 0x08, 0x00])           # 640x480, 800x600 and 1024x768 at 60
    block += bytes([1, 1]) * 8                  # no standard timings
    block += timing(148500, 1920, 280, 1080, 45, 88, 44, 4, 5, 1600, 900)       # 1920x1080 at 60
    block += timing(74250, 1280, 370, 720, 30, 110, 40, 5, 5, 1600, 900)        # 1280x720 at 60
    block += text(0xFC, "tv-emu TV")            # the display's name
    block += bytes([0, 0, 0, 0xFD, 0, 24, 75, 15, 81, 17, 0, 0x0A, 32, 32, 32, 32, 32, 32])   # the rates it takes
    return closed(block + bytes([1]))           # one extension block follows


def extension():
    blocks = [
        # Video: CTA-861's codes for 1080p60 (the display's own), 720p60, 1080p50, 720p50, 480p60, 576p50.
        bytes([2 << 5 | 6, 0x80 | 16, 4, 31, 19, 3, 18]),
        # Sound: PCM, two channels, at 32, 44.1 and 48 kHz with 16, 20 or 24 bits.
        bytes([1 << 5 | 3, 1 << 3 | 1, 0x07, 0x07]),
        # Speakers: front left and right.
        bytes([4 << 5 | 3, 0x01, 0, 0]),
        # HDMI's own block: its number, and the source's address 1.0.0.0.
        bytes([3 << 5 | 5, 0x03, 0x0C, 0x00, 0x10, 0x00]),
    ]
    data = b"".join(blocks)
    # Underscan, basic sound, YCbCr 4:4:4 and 4:2:2; one of the base block's timings is the display's own.
    head = bytes([2, 3, 4 + len(data), 0x80 | 0x40 | 0x20 | 0x10 | 1])
    return closed((head + data).ljust(127, b"\0"))


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as out:
        out.write(base() + extension())
