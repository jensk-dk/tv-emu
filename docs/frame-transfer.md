# Frame transfer and drawing: from the target's display to the launcher's window

How a picture of a VM's display gets from QEMU into the launcher's window on
the three hosts, what each way costs, what limits the rate today, and what the
best way is for each host. Written on 2026-11-24 from measurements on the
Linux host (with its own QEMU 8.2.2 and with a QEMU 11.0.0 built for this)
and from QEMU's source; nothing was run on Windows for it. The macOS part was
first written from the source alone and then run on the Mac the same day:
"Measured on the Mac" below has what came of it, and where it differs from
what was read, that section is the one to go by.
The
Linux way for host graphics was built the same day
("Built: the GPU's buffer in the launcher's window" below).
What was measured and what was only read is said for each statement, and
"Not verified" at the end lists what is still open.

Container mode is not covered: there a program in the target captures the
compositor's output ([target/src/emuscreen.c](../target/src/emuscreen.c)).

## Summary

| Host | Target's graphics | Today | Limit today | Best way | Needs |
|---|---|---|---|---|---|
| Linux | emulated (the target's CPU draws) | D-Bus, pixels over a socket: 60 a second | none at 1080p | keep; shared memory later | shared memory needs QEMU 9.2 (seen working with 11.0.0) |
| Linux | host GPU (virgl) | D-Bus with the GPU's buffer (no copy): 30 a second with QEMU 8.2.2, 60 with QEMU 11.0.0; VNC, where the host does not take the buffers: 22 | QEMU 8.2 answers the GPU's fences every 10 ms | as it is, with QEMU 11 | 60 needs QEMU 11 with virglrenderer 1.1.2 or later, which Ubuntu 24.04 does not have: a build of both (`EMU_QEMU_DIR`) |
| macOS | emulated | D-Bus, pixels over a socket: 60 a second | none at 1080p | keep | nothing |
| macOS | host GPU (experimental QEMU) | D-Bus with a read-back in QEMU: 60 a second (measured on 2026-11-24 with this project's change to that QEMU; before it, QEMU's own window only, at 25) | none at 1080p | keep | the experimental QEMU built with the change (`./setup.sh --experimental-qemu`) |
| Windows | emulated | VNC | VNC's 30 ms look | D-Bus, shared memory | to be tried: whether the QEMU build has the D-Bus display |
| Windows | host GPU | QEMU's own window only | the display without a window stays black | D-Bus with the shared Direct3D texture (no copy), else read-back into shared memory | the same, and a viewer change |

The three findings behind the table:

1. **At 1080p the copies are not what limits the rate.** On the Linux host
   every copy of a frame costs 0.5 to 1.4 ms of the 16.7 ms a frame has (table
   below). The pixel path that macOS and Linux use for emulated graphics
   reaches the display's 60 a second with them.
2. **What limits the rate is waiting.** QEMU's VNC server looks at the
   display every 30 ms. QEMU before 11.0 answers the fences of a
   GPU-accelerated target from a timer of 10 ms, which holds the RDK-E image
   to 30 pictures a second on the Linux host whatever shows them. With QEMU
   11.0.0 and virglrenderer 1.3.0 on the same host it hands over 59.9.
3. **Handing over the GPU's buffer works on the Linux host**, with the NVIDIA
   driver: QEMU 8.2.2 sends it, and Qt takes it as a texture in its own
   OpenGL context when Qt is started with EGL.

## The ways QEMU can hand over a picture

All but VNC are methods of QEMU's D-Bus display, which QEMU calls on a
listener that the viewer registers (`ui/dbus-display1.xml` in QEMU's source;
[emulator/dbusdisplay.py](../emulator/dbusdisplay.py) is the launcher's
listener).

| Way | Methods | What crosses | In QEMU since | Hosts |
|---|---|---|---|---|
| VNC | (the RFB protocol) | encoded pixels, when QEMU's timer looks | long ago | all |
| Pixels | `Scanout`, `Update` | the pixels, in the message | 7.0 | all |
| Shared memory | `ScanoutMap`, `UpdateMap` | a handle to memory both map, then rectangles | 8.2 on Windows (`Win32.Map`), 9.2 on Linux (`Unix.Map`) | Linux and Windows; not macOS, see below |
| GPU buffer | `ScanoutDMABUF`, `UpdateDMABUF`; `ScanoutDMABUF2` since 10.1 | a file descriptor of the GPU's buffer, then rectangles | 7.0 | Linux |
| GPU texture | `ScanoutTexture2d`, `UpdateTexture2d` | a handle of a shared Direct3D 11 texture | 8.2 | Windows |

The versions were read from QEMU's releases (8.2.2, 9.0.0, 9.1.0, 9.2.0,
10.0.0, 10.1.0, 10.2.0, 11.0.0); the "7.0" and "8.2 on Windows" entries are
from memory of the history and from the names in the Linux host's 8.2.2
build.

What a picture goes through on each way, for a display the target's CPU drew
(it is in QEMU's memory) and for one the host's GPU drew (it is a texture):

| Way | CPU-drawn display | GPU-drawn display |
|---|---|---|
| VNC | encode, socket, decode, paint | read-back, then the same |
| Pixels | into the message, socket, paint | read-back, then the same (QEMU does this on Windows only) |
| Shared memory | paint (the viewer reads QEMU's own memory) | read-back into that memory, paint (on Windows only) |
| GPU buffer or texture | (not for these) | none: the viewer draws from the buffer |

The compositing is the target's in every case: what crosses is the finished
full picture, and `Update` names the rectangle of it that changed.

## Measured on the Linux host

Host: `linux-x86_64@intel-core-i7-10700k`, Ubuntu 24.04.5, X11, NVIDIA
RTX 4070 with the driver 595.99.02 (open kernel modules), QEMU 8.2.2,
virglrenderer 1.0.0, Qt 6.11.3 (PySide6). Target: the RDK-E image for x86-64
(`rdke/README.md`), host-native under KVM, 1920x1080, at its home screen
unless said otherwise.

### What a copy costs

One frame of 1920x1080 at four bytes a pixel is 8.3 MB. Sixty of each, the
mean:

| Step | ms |
|---|---|
| Copy in memory | 0.50 |
| Through a socket pair, send and receive | 1.07 |
| Copy out of shared memory (memfd) | 1.13 |
| QPainter: frame into the viewer's image | 0.48 |
| QPainter: image into a window, 1:1 | 0.53 |
| QPainter: image scaled smoothly to 1600x900 | 2.23 |
| OpenGL ES: upload into a texture | 1.38 |
| OpenGL ES: read-back from a texture | 0.94 |
| OpenGL ES: import of QEMU's buffer as a texture | 0.2 to 0.4 |

The pixel path as the launcher has it (socket, into the image, into the
window) is about 2 ms of these, of 16.7 ms. At 3840x2160 each is four times
as much, and the same path would take half of a frame's time.

### Emulated graphics

The window gets 59.9 pictures a second over D-Bus with the pixel methods
(60.0 with the VM's 8 CPUs; `rdke/README.md`). Over VNC it got 23 to 24 of
a video.

### Host graphics (virgl)

- **The window over VNC: 22.5 pictures a second** during 1920x1080 video
  (with `-display egl-headless`, which reads each picture back).
- **The target hands over 30 pictures a second, whatever the display.**
  Counted in QEMU (`-trace virtio_gpu_cmd_res_flush`): 30.6 a second with
  `-display egl-headless` and nobody watching, 30.9 with `-display
  dbus,p2p=yes,gl=on` and a listener that answers at once. The gaps between
  the pictures are 33.3 ms (10 % and 90 % of them: 33.1 and 33.5), two
  refreshes of the display's 60.
- **Why 30: QEMU answers a fence up to 10 ms late.** A fence is the
  target's question whether the GPU is done with a command. Traced
  (`virtio_gpu_fence_ctrl`, `virtio_gpu_fence_resp`): the answer came after
  9.87 ms in the median (90 %: 10.42 ms), and a picture has about four
  fenced commands. QEMU 8.2.2 asks virglrenderer for finished fences from a
  timer of 10 ms (`virtio_gpu_fence_poll` in `hw/display/virtio-gpu-virgl.c`).
  QEMU 11.0.0 is the first release that has virglrenderer tell it instead
  (`VIRGL_RENDERER_ASYNC_FENCE_CB`, with virglrenderer 1.1.2 or later);
  10.2.0 and before do not have it.
- **With QEMU 11.0.0 and virglrenderer 1.3.0 the target hands over 59.9.**
  Both were built into a scratch directory on this host (with libepoxy
  1.5.10 and libslirp 4.9.7; nothing installed) and run with the same
  command line and image. A fence is answered after 0.50 ms in the median
  (90 %: 0.83 ms; 0.68 and 0.94 with `-display egl-headless`), and a
  listener of `-display dbus,p2p=yes,gl=on` gets `UpdateDMABUF` 59.9 times a
  second, 16.7 ms apart (10 % and 90 % of the gaps: 16.5 and 16.8). The
  buffer it sends is as with 8.2.2: `AB24`, the same modifier, two buffers in
  turn.
- **QEMU sends the GPU's buffer.** With `-display dbus,p2p=yes,gl=on` a
  listener gets `ScanoutDMABUF` (signature `huuuutb`) and `UpdateDMABUF`
  (`iiii`) for every picture: 1920x1080, stride 7680, format `AB24`
  (four bytes a pixel as red, green, blue, alpha), modifier
  `0x0300000000e08014` (one of NVIDIA's), top row first (QEMU's `y0_top`
  is not set, and QEMU's own windows turn a picture over when it is not:
  `gd_egl_refresh` in `ui/gtk-egl.c`). The target
  switches between two buffers, so both methods come for each picture.
- **The NVIDIA driver takes it.** `eglCreateImage` with the descriptor,
  format and modifier gives an image; bound to a texture and read back, it
  is the home screen. The modifier is among the 13 the driver names for the
  format. It works on the X11 display and on the driver's device without a
  window system alike.
- **Qt takes it in its own context, when that is an EGL one.** By default
  Qt on X11 makes a GLX context here (OpenGL 4.6), which has no EGL display
  and so cannot import. With `QT_XCB_GL_INTEGRATION=xcb_egl` Qt makes an
  OpenGL ES 3.2 context on EGL, and the same import works in it.
- **Mapping the buffer is no way.** `mmap` of the descriptor works, but
  reading the 8.3 MB out took 315 ms.
- **No shared memory in QEMU 8.2.2.** Its D-Bus display has the pixel and
  the GPU-buffer methods on Linux; `Unix.Map` came with 9.2. And for a
  GPU-drawn display QEMU has no read-back in the D-Bus display on Linux in
  any release read.

### Shared memory, with QEMU 11.0.0

For a CPU-drawn display (`-device virtio-gpu-pci`, `-display dbus,p2p=yes`)
and a listener whose `Interfaces` property names
`org.qemu.Display1.Listener.Unix.Map`, QEMU sends `ScanoutMap` (signature
`huuuuu`: descriptor, offset, width, height, stride, format) and `UpdateMap`
(`iiii`) in place of `Scanout` and `Update`. The descriptor maps, and the
memory holds the picture (1920x1080, stride 7680, format `0x20020888`). The
messages of a picture are then 40 bytes where they were 8.3 MB.

The RDK-E image shows its pictures from two buffers in turn, so every picture
comes as a `Scanout` or `ScanoutMap` of a whole frame, with a new descriptor
each time; a listener has to map each and close the one before.

Not explained: with QEMU 11.0.0 the same CPU-drawn display changed 44 to 54
times a second in five runs (with the pixel methods, with shared memory and
with no display at all), and 55 to 60 with QEMU 8.2.2. That is the target's
own drawing, not the transfer: it was the same without a listener. The
build's options were QEMU's defaults.

With host graphics the VM's 4 CPUs are 77 % idle during 1920x1080 video; with
emulated graphics the same video needs 8 CPUs for 57 pictures a second.

## Built: the GPU's buffer in the launcher's window

Built on 2026-11-24, for Linux, and run with QEMU 8.2.2 on the host above.

- **The listener** ([emulator/dbusdisplay.py](../emulator/dbusdisplay.py))
  takes the descriptors that come with a message, hands each
  `ScanoutDMABUF` to the viewer, and answers an `UpdateDMABUF` when the
  viewer has drawn the picture, or after 0.1 s where it draws nothing (a
  hidden window). `ScanoutDMABUF2` is not offered: QEMU then sends the
  first form for a buffer of one plane, which is what a display is.
- **The viewer** ([emulator/gui/gldisplay.py](../emulator/gui/gldisplay.py))
  has an OpenGL widget for such a display. It makes an EGL image of the
  descriptor and a texture of the image, through `ctypes`, and draws the
  texture scaled into the window. Qt is started with
  `QT_XCB_GL_INTEGRATION=xcb_egl` and asked for OpenGL ES 3. It does not
  wait for the screen's refresh when it shows a picture (swap interval 0):
  QEMU holds the target's drawing until the picture is drawn, so a window
  that waits sets the target's pace, and with the screen asleep the NVIDIA
  driver let such a window show one picture a second. The toolbar, the
  keys and the on-screen remote control are as before.
- **Captures** are read back from the texture: the checks' `save-display`,
  and `--screenshot`, which asks the window where only it has the picture.
- **The choice** (`window_endpoint` in
  [emulator/graphics.py](../emulator/graphics.py)): for host graphics the
  launcher asks the windows' Python whether Qt's context takes GPU buffers
  (`python -m emulator.gui.gldisplay --probe`; `./emu doctor` shows the
  answer). Where it does, QEMU gets `-display dbus,p2p=yes,gl=on`; where it
  does not, `-display egl-headless` and VNC as before, with a note.
  `--option window-display=vnc` asks for VNC, `=buffer` refuses to fall
  back. A buffer that the driver refuses once the run is on is said in the
  window and on the terminal, with that option.

Measured, the RDK-E image with `--graphics host`, the VM's CPUs as the
launcher's checks give them (8), 1920x1080, as pictures that QEMU announced
and the window drew in 10 s (one run each, the screen asleep):

| | Over VNC (before) | GPU's buffer, QEMU 8.2.2 | GPU's buffer, QEMU 11.0.0 |
|---|---|---|---|
| Home screen | (a still screen is not sent again) | 30.0 a second | 60.0 |
| Big Buck Bunny, 1920x1080 | 22.5 | 30.0 | 60.0 |

So the window shows every picture the target hands over: 30 a second where
QEMU answers the fences from its 10 ms timer, 60 where it does not (above).
QEMU 11.0.0 is the one built for this document, with virglrenderer 1.3.0,
taken with `EMU_QEMU_DIR`.

While the window still waited for the screen's refresh, QEMU 8.2.2 gave 34
to 53 pictures a second in seven runs, different each time: holding back
the answer to QEMU changes when the fences are answered. That was with the
screen awake; with it asleep the same window drew one picture a second.

What QEMU 11.0.0 needed from the launcher on Linux:

- **The window has to listen before QEMU starts.** QEMU connects to the
  window's port for the remote control's keys, and tries again each second
  (`reconnect-ms`). QEMU 11.0.0 ends, aborted and without a message, 1.3 s
  after its start when nothing listens there; the window sometimes took
  longer to start. The launcher now waits for the port
  (`wait_listening` in [emulator/window.py](../emulator/window.py)).
  QEMU 8.2.2 only tries again.
- **Vulkan only where the renderer has it.** QEMU 11's display device has
  the option for Vulkan (`venus`) whatever virglrenderer it is built with,
  and the launcher turned it on wherever the option is. With a
  virglrenderer built without it QEMU ends when the target first uses the
  GPU ("failed to initialize venus renderer"). The launcher now looks at
  the library (`_renderer_maps_vulkan` in
  [emulator/graphics.py](../emulator/graphics.py)).
- QEMU 11.0.0 says "audio: Can not open `virtio-sound.in' (no host audio
  driver)" for the launcher's sound device, which only plays. It goes on,
  and the target's sound was not checked with it here.

Also seen:

- **A 4K display reaches the window whole** (3840x2160, the OpenGL ES
  test), where VNC in QEMU 8.2.2 serves 2560x2048 of it.
- **The Debian image's checks pass on this way**: the window checks of the
  host-native VM and `window-display` of both simulated ARM targets, all
  with host graphics, which compare the picture pixel for pixel
  (`tasks.md` has the list).
- **The launcher's checks with each QEMU**, on 2026-11-24, the checks of
  the host-native VM and of the RDK-E image:

  | | Passed | Not passed |
  |---|---|---|
  | QEMU 8.2.2 | 39 of 41 | `rdke-rate`; `resolution-vm` once, passed in two runs alone after |
  | QEMU 11.0.0 | 38 of 39 | `rdke-rate` |

  `rdke-rate` fails without these changes as well: it plays the reference
  stream with emulated graphics, gets 35 pictures a second and wants 50.
  The two checks more with QEMU 8.2.2 are `window-display` of the simulated
  ARM targets, which the QEMU 11.0.0 built here cannot run. `rdke-aamp`,
  `rdke-health` and `rdke-device` were unavailable in both: the RDK-E image
  was older than the checks.
- **QEMU ends on a failed assertion when the target shuts down** while a
  listener for GPU buffers is there (`dbus_scanout_texture: Assertion
  'tex_id' failed`, QEMU 8.2.2 and 11.0.0 as released). The
  launcher has the window let go of the display when a workload reports
  its exit status, which avoids it. An RDK-E target that is shut down from
  inside, and not by closing the window, still ends QEMU 8.2.2 that way.
  The QEMU 11.0.0 that the setup script builds has a change for it
  ([linux-experimental-qemu.patch](linux-experimental-qemu.patch)): a
  scanout without a texture tells the listener that the display is off.
  Tried with the launcher's workaround switched off: QEMU 8.2.2 and
  11.0.0 as released end with status -6 after the workload, the changed
  11.0.0 ends as it should.

### QEMU 11 from the setup script, with Vulkan on the host's GPU

`./setup.sh --experimental-qemu --arm-targets` builds QEMU 11.0.0 and
virglrenderer 1.3.0 with the Vulkan mapping (Venus) for the three guest
architectures (README, "Linux"). The first run of every check with it, on
2026-11-25, had nine checks fail that pass with QEMU 8.2.2: the four
`video-*-vm` checks, the same four for ARM64, and `gles-vm-arm32`. All of
the video failures came from the one case in which `mpv` draws with
Vulkan, which with QEMU 8.2.2 is drawn by the target's CPU:

- **A window format with 16 bits a channel ended the compositor's
  drawing.** `mpv` takes the deepest format on offer, and on the virtual
  GPU that was `R16G16B16A16_UNORM`. Its pictures go to the compositor as
  GPU buffers, the compositor draws with the virtual GPU's OpenGL ES, and
  the host has to take each buffer into its own OpenGL ES
  (`vrend_renderer_pipe_resource_set_type: failed to create egl image`).
  NVIDIA's EGL names no layout for `ABGR16161616` (asked with
  `eglQueryDmaBufModifiersEXT`; it names thirteen for the 8-bit, the
  10-bit and the 16-bit float formats). After the one refusal the host
  renderer treats the compositor's context as faulty ("Illegal command
  buffer"), and every picture after it was the one before or black, for
  every program. That is why the cases after the Vulkan one failed too.
  Now a Vulkan layer in the image
  ([target/src/emu_vulkan_formats.c](../target/src/emu_vulkan_formats.c))
  leaves the 16-bit formats out of what a program is offered on the
  virtual GPU; `mpv` then takes `A2R10G10B10_UNORM`.
- **The player's own transfer queue ended the host's Vulkan device.** With
  the format out of the way, the first frame gave
  `VK_ERROR_DEVICE_LOST` from the host's `vkQueueSubmit2` (seen with a
  virglrenderer that says where it gives up; the host's kernel log has
  `NVRM: Xid 32` from the renderer's thread), and `mpv` aborted. With
  `--vulkan-async-transfer=no` it plays; `--vulkan-async-compute=no` alone
  does not help, and `--vo=gpu-next` plays as well. The `media-decode`
  workload now passes the first.
- **A 32-bit ARM target has no Vulkan through the virtual GPU.** Mesa says
  "one of required kernel params (4 or 9) is missing" with Debian 13's
  kernel for it. The launcher no longer turns the Vulkan mapping on for
  that target, so its display device is set up as with QEMU 8.2.2.
  `vulkan-vm-arm32` and `video-vulkan-vm-arm32` fail with both QEMUs: the
  target's CPU renderer for Vulkan ends there with "malloc(): invalid
  size", and the compositor often ends with it and is started again.
  `gles-vm-arm32` failed once with QEMU 11 ("lost the connection to the
  Wayland compositor") and passed in two runs after; whether the Vulkan
  mapping had a part in it is not known.

With these, on the same host: `video-wayland-vm`, `video-gles-vm`,
`video-vulkan-vm` and `video-flutter-vm` pass with QEMU 11.0.0, the Vulkan
case played by "Virtio-GPU Venus (NVIDIA GeForce RTX 4070)" with no frame
dropped. FULLRUN

## Measured on the Mac

Host: `macos-arm64@apple-m6`, the experimental QEMU 11.1.90 (commit
`c95b8c49`, with virglrenderer 1.3.0 and ANGLE on Metal), on 2026-11-24.
Target: the RDK-E image for ARM64, host-native, 1920x1080, with the VM's
6 CPUs. The numbers of pictures are of the launcher's own window, which drew
them (`./emu verify rdke-rate rdke-rate-host`), not of a listener that only
counts.

### Why QEMU's own window showed 25 pictures a second

With `--graphics host` in QEMU's Cocoa window the target handed over 25.1
and 26.3 pictures a second at its home screen (`-trace
virtio_gpu_cmd_res_flush`), with its CPUs 98 % idle. The gaps between the
pictures were 33 and 50 ms, two and three refreshes. (On 2026-11-22 and 23
the same build gave 2 to 22; what was different then is not known.)

The cause is the one found on Linux, for another reason. A fence was answered
after 11.3 ms in the median (90 %: 12.6 ms), and a picture has four fenced
commands. This QEMU has the fence answer without a timer, and virglrenderer
1.3.0 has its side of it, but virglrenderer needs `eventfd` for the thread
that watches the fences, and macOS has none: it answers a fence only when
QEMU asks, and QEMU asks from its timer of 10 ms (a sample of QEMU's threads
shows `virtio_gpu_fence_poll` calling `virgl_renderer_poll`, and the answers
coming from there). With the timer at 1 ms on macOS a fence is answered after
1.37 ms (90 %: 1.51 ms) and the target hands over 59.9 pictures a second.

### The D-Bus display with OpenGL, before any change

`-display dbus,p2p=yes,gl=es` starts, and ends with a segmentation fault at
its first refresh: `glFlush` in `dbus_gl_refresh`, with no OpenGL context on
that thread. With that passed, it ends the same way when the target's driver
starts the host renderer (`EGL_MakeCurrent`, from `virgl_renderer_init`).
Both are one fault, and it is `egl-headless`'s too: on macOS QEMU's main loop
runs on another thread than the one that sets the display up, and ANGLE wants
EGL used from the thread that initialized it. QEMU's Cocoa display knows
that and initializes EGL at the first request for a context
(`cocoa_gl_lazy_init`); the D-Bus display and `egl-headless` do it when QEMU
starts.

### This project's change to the experimental QEMU

In `docs/macos-experimental-qemu.patch`, as a patch that the tap's formula
applies to QEMU; 262 lines in five files, all of it for macOS only:

- the D-Bus display initializes EGL at the first request for a context, on
  the main loop's thread, as the Cocoa display does, with a surface of one
  pixel for its contexts;
- a scanout that the GPU drew is read back into the surface's memory in the
  display's own context (which shares the textures of virglrenderer's) and
  sent as pixels with `Scanout`, the method every listener has; a picture
  that comes bottom row first is turned;
- a surface that the target draws in memory is sent from that memory, without
  a texture;
- fences are asked about every millisecond while any is open;
- a trace point, `dbus_gl_read_back`, by which the launcher and `setup.sh`
  know a QEMU that has the change.

The launcher's viewer needed no change. The launcher takes this way where
QEMU has the change and its own window shows the display
(`emulator/graphics.py`, `dbus_read_back` and `window_endpoint`).

### With the change

| | Emulated graphics | Host graphics |
|---|---|---|
| Window, home screen | 60.0 a second | 60.0 a second |
| Window, 1280x720 stream in the browser, shown at 1920x1080 | 55.8 (59.4 in a second run) | 60.1 (60.0) |
| The VM's CPUs idle, home screen | 68 % | 97 % |
| The VM's CPUs idle, during the stream | 47 % (51 %) | 83 % |
| QEMU's share of a host CPU, home screen | (not taken) | 34 to 43 % |

The picture in the window is the right one (the home screen, and the
stream's corner and marker blocks, which the check looks for). RDK's player
(AAMP) and the browser's own player both play the reference stream with host
graphics, with picture and sound; AAMP's frames go through Westeros' video
sink, which needs the renderer's change of the same day for virgl
(`rdke/README.md`).

The QEMU measured on 2026-11-24 was built from the same source and the
same change in a scratch directory, with the formula's options. On
2026-11-25 `./setup.sh --experimental-qemu` built it through Homebrew and
installed it (the script found the earlier build as outdated, put the
change into the tap and built again), and with the installed QEMU
`rdke-rate-host` gave 60.1 pictures a second at the home screen and 60.1
during video.

Measured on 2026-11-25, one run each, in the launcher's window:

| | Host GPU | Emulated |
|---|---|---|
| 3840x2160, OpenGL ES test (Debian image), frames drawn a second | 433 | 35 |
| 3840x2160, Flutter, frames a second, paced by the display | 49.0 | 4.6 |
| 1920x1080, Flutter, paced by the display | 61.0 | not taken that day |
| RDK-E browser, a 1920x1080 clip of 60 frames a second: pictures a second in the window | 60.0 | 50.8 |
| the same: frames the player counted a second; dropped | 59.7; none | 59.4; none |
| the same: the VM's 6 CPUs idle | 58 % | 33 % |

- **3840x2160: the read-back is not a limit.** The launcher's window got
  122 pictures a second from the OpenGL ES test at 3840x2160 (125 at
  1920x1080), counted at the window over 8 s. The capture of the 4K display
  from the window is whole.
- **What falls short at 3840x2160 is a picture drawn in memory.** Flutter
  gets 49 to 57 frames a second there (61 at 1920x1080), and the Wayland
  test, which draws in shared memory, is shown 62 times a second (117
  emulated). In a profile of QEMU during the Flutter test (`sample`, 6 s,
  53 frames a second) the main loop spent 6.6 ms a picture in
  virglrenderer's upload of a texture from the target's memory
  (`vrend_renderer_transfer_write_iov`, `glTexSubImage2D`) and 1.8 ms in
  the read-back (`glReadPixels`, most of it waiting for the GPU); it was
  idle 41 % of the time. So the cost is the target's compositor handing
  the host a full picture from memory each frame. Why the Flutter
  application's picture takes that way, when it draws with the GPU, was
  not looked for. This corrects the first reading of the same day, which
  suspected the read-back.
- **A stream of 60 frames a second** reaches the window whole with the
  host's GPU. The clip was made for this (FFmpeg's test picture, H.264,
  8 Mbit/s), copied into the target and played by the browser's own
  player; the player's count is of frames it handed on, not of what the
  window got.
- **The Debian target on this way** is checked now: `graphics-host-vm`
  runs in the launcher's window where only that has the picture, with
  captures taken from the window (`--screenshot` works the same way).
- **The launcher takes the experimental QEMU by itself** for a run with
  `--graphics host`, where the installed QEMU has no host graphics
  (`host_graphics_qemu` in [emulator/graphics.py](../emulator/graphics.py));
  other runs keep the installed one.
- **Vulkan (Venus on MoltenVK) does not work with the target as it is.**
  With `--option venus=yes` QEMU starts and the renderer opens MoltenVK
  (the launcher has to name its directory to QEMU; macOS takes such a
  variable out of the environment of its own Python), then QEMU reports
  that mapping a shared buffer failed and the target's `vkCreateInstance`
  returns an error. The tap's notes say why: 16 KB pages on the host, 4 KB
  in the target, and a Vulkan driver in the target that has to align its
  buffers to 16 KB, which needs a Mesa change that is not in Mesa.
- **With a kernel of 16 KB pages the target reaches the Apple GPU through
  Vulkan, and still cannot show a picture with it.** A copy of the target
  image with Debian's `linux-image-arm64-16k`, built in a scratch
  directory, lists "Virtio-GPU Venus (Apple M6)" as a Vulkan device, and
  OpenGL ES and Flutter run on it as before. The Vulkan test fails at
  `vkCreateDevice` (`VK_ERROR_EXTENSION_NOT_PRESENT`): the device has 78
  extensions and `VK_KHR_swapchain` is not one. Mesa's driver offers it
  only where the host's Vulkan can share buffers the Linux way
  (dma-buf), which MoltenVK cannot. So a changed Mesa in the target is
  needed in any case; the tap's author has one, not tried here.
- **Without a window** the host's GPU works as well now: `-display
  dbus,p2p=yes,gl=es` needs no window, and for a capture the launcher
  attaches a listener of its own (`ReadBackCapture` in
  [emulator/graphics.py](../emulator/graphics.py)), so that QEMU reads
  the picture back. With nothing to capture nobody listens and nothing is
  read back.
- **Faults seen earlier in QEMU's own window are gone on this way**: the
  HEVC stream loses no frame on a host-native target (0 of 125 through
  Wayland, OpenGL ES and Vulkan, three runs), and on a simulated ARM64
  target it ends, with none lost through OpenGL ES.

## Read in the source, not run

### macOS: the experimental QEMU (11.1.90, commit `c95b8c49`)

What follows was read before anything was run on the Mac. It held, with one
addition: the fence answer without the timer is in the source and in the
build, and is of no use on macOS (above).

- The D-Bus display starts with OpenGL through ANGLE: `egl_init` in
  `ui/egl-helpers.c` has a macOS branch that its comment gives to "every EGL
  user in a macOS build (cocoa, egl-headless, dbus, ...)".
- For a GPU-drawn picture it then sends nothing. In `ui/dbus-listener.c`,
  `dbus_scanout_texture` and `dbus_call_update_gl` have a body for Linux
  (the buffer's descriptor) and one for Windows, and none for macOS.
- The Windows body is a read-back and has nothing of Windows in it: the
  texture gets a framebuffer (`egl_fb_setup_for_tex`), the changed
  rectangle is read into the display's memory (`egl_fb_read_rect`) and sent
  with `Update`.
- Shared memory is not there on macOS: the display's memory is shareable
  only where it comes from `memfd_create`, which is Linux's
  (`util/memfd.c`). The methods are built for every host but Windows; on
  macOS QEMU has nothing to hand over with them.
- The Cocoa window draws through an ordinary ANGLE window surface. Nothing
  in `ui/` uses an IOSurface, the buffer that macOS shares between
  processes.
- The fence answer without the timer is in this source, where the
  virglrenderer it is built with is 1.1.2 or later. Which one the build's
  virglrenderer (commit `890d0648`) is was not looked up.
- The launcher's own note (`emulator/graphics.py`): `-display egl-headless`
  ends with a segmentation fault in this build when the target starts to use
  the GPU, the OpenGL context being made current on a thread it was not made
  for.

### Windows (QEMU 11, from winget)

- In QEMU's source the D-Bus display on Windows has all three ways: pixels,
  shared memory (`Win32.Map`), and for a GPU-drawn picture either a shared
  Direct3D 11 texture (when ANGLE runs on Direct3D 11) or the read-back into
  the shared memory.
- Whether the QEMU that `setup.ps1` installs is built with the D-Bus display
  is not known here: `qemu-system-x86_64 -display help` on the Windows host
  says.
- The launcher's connection would be different there. On macOS and Linux it
  hands QEMU a socket's descriptor over the machine protocol (`getfd`,
  `add_client`); on Windows QEMU takes a socket with `get-win32-socket`, and
  Python has no pair of Unix sockets to give.
- The launcher's own note: `-display egl-headless` stays black on Windows
  (QEMU 11.1.0), so a GPU-drawn display has no way into the launcher's
  window there today. Whether the D-Bus display's read-back, which is other
  code, shows the picture was not tried.

## The best way for each host

### Linux

1. **Emulated graphics: as it is.** Shared memory would take the socket's
   1 ms off each frame and needs QEMU 9.2; it is worth having only together
   with a newer QEMU for the next point, or for 4K.
2. **Host graphics: the GPU's buffer over D-Bus.** No copy at all, and it
   works with this host's driver. Built on 2026-11-24 (above), as planned
   here:
   - the listener takes `ScanoutDMABUF` and `UpdateDMABUF` with the
     descriptor (and `ScanoutDMABUF2` from QEMU 10.1), and answers
     `UpdateDMABUF` only when the picture is drawn, as QEMU holds the
     target's drawing until then;
   - the viewer's display becomes an OpenGL widget that imports the buffer
     as an EGL image (through `ctypes`; PySide6 has no such call) and draws
     it, bottom row first; Qt is started with
     `QT_XCB_GL_INTEGRATION=xcb_egl` on X11;
   - screenshots, recordings and the checks' captures read the picture back
     from the texture (about 1 ms);
   - VNC stays for a host where the import is refused.
   With QEMU 8.2.2 that gives the target's 30 pictures a second in the
   window in place of 22.
3. **Sixty with host graphics: QEMU 11 with virglrenderer 1.1.2 or later.**
   Ubuntu 24.04 has 8.2.2 and 1.0.0, so this means a build of both for the
   launcher, as the Mac has one (`EMU_QEMU_DIR`). Measured with such a
   build: 59.9 pictures a second reach a listener. It took four sources
   (QEMU, virglrenderer, libepoxy, libslirp; the host's packages lack their
   development files) and about ten minutes. In the launcher's window that
   build gives 60.0 a second (above). Points 2 and 3 together are
   what makes host graphics the better choice for the RDK-E image on this
   host: 60 a second with the VM's CPUs three quarters idle, where emulated
   graphics needs 8 CPUs for 57. Either alone gives 30 (point 2) or 22
   (point 3, over VNC).
4. **Before QEMU 11 becomes the launcher's on Linux**: the slower CPU-drawn
   display seen with it (above) has to be understood, and Vulkan on the
   host's GPU has to be tried on a host with Mesa's drivers. The setup
   script provides it, with the ARM targets (`--experimental-qemu`), and
   the launcher's checks were run with it ("QEMU 11 from the setup
   script", above).

### macOS

1. **Emulated graphics: as it is.**
2. **Host graphics: a read-back in the experimental QEMU.** Done on
   2026-11-24 ("Measured on the Mac"): the window gets 60 pictures a second.
   It took 262 lines and not the 20 to 30 guessed here, since the display
   also had to initialize EGL on the right thread and the fences had to be
   answered faster. `./setup.sh --experimental-qemu` builds the
   experimental QEMU again with the change; run on 2026-11-25, and the
   installed build gives the same result.
3. **No copy at all** would be an IOSurface handed to the viewer: a new
   method in QEMU's interface, a way to pass the surface (a Mach port, which
   D-Bus does not carry, or a global identifier, which Apple has deprecated)
   and a native layer in the viewer. A week or two, against a day or two for
   point 2, and only worth it if the read-back turns out to be what limits
   the rate. At 1920x1080 it does not: the window gets every picture.

### Windows

1. **Try the D-Bus display at all** (`-display help`). If the build has it,
   emulated graphics goes from VNC to shared memory (`Win32.Map`), which
   ends VNC's 30 ms look as it did on the other two hosts.
2. **Host graphics** then has the read-back into the same shared memory
   without a change to the viewer, if it does not stay black as
   `egl-headless` does, and the shared Direct3D texture as the way without
   a copy, for which the viewer needs native calls.

### In common

One listener and one viewer, with the ways in this order and the first that
the host's QEMU offers: the GPU's buffer or texture, shared memory, pixels,
VNC. The listener says which interfaces it has in its `Interfaces` property,
and QEMU chooses by that.

## Not verified

- **Vulkan on the host's GPU with other drivers than NVIDIA's.** Both
  faults found with it (above) are about what NVIDIA's driver takes. Mesa's
  drivers may take the 16-bit buffers and the transfer queue; the layer and
  the player's option are there on every host all the same.
- **Vulkan programs other than `mpv` and the graphics test.**
- **Why the CPU-drawn display is slower with the QEMU 11.0.0 built here**
  (44 to 54 a second against 55 to 60).
- **The target's sound with QEMU 11** was not listened to.
- **Whether a picture is ever shown half drawn.** None was seen in the
  captures; nothing looked for one. The target shows its pictures from two
  buffers in turn, so the one the window draws from is not being written.
- **Other drivers.** Only the NVIDIA driver 595 on X11 was tried. Mesa's
  drivers (Intel, AMD), a Wayland session and a screen with a scale factor
  were not.
- **Anything on Windows.** All of it is read from the source and from the
  launcher's earlier notes.
- **On macOS:** everything listed as not measured under "Measured on the
  Mac".
- **3840x2160.** The copy times are for 1920x1080.

## How the measurements were made

- The copies: a Python program with the launcher's own Qt
  (`build/host/gui`), sixty frames of random bytes for each step; the
  OpenGL ES steps on the driver's EGL device without a window system.
- QEMU 11.0.0: `configure --target-list=x86_64-softmmu --enable-kvm
  --enable-opengl --enable-virglrenderer --enable-dbus-display
  --enable-slirp`, with virglrenderer 1.3.0, libepoxy 1.5.10 and libslirp
  4.9.7 built into the same prefix first.
- QEMU's messages: QEMU started as the launcher starts it for the RDK-E
  image with `--graphics host`, but with `-display dbus,p2p=yes,gl=on`, and
  a listener made of `emulator/dbusdisplay.py`'s connection code that also
  takes the descriptors (`recvmsg`) and answers every call.
- The target's rate and the fences: `-trace virtio_gpu_cmd_res_flush -trace
  'virtio_gpu_fence_*' -D FILE` on the same command line, 30 to 35 s, the
  rate over the last 8 s.
- The import: `eglCreateImageKHR` with `EGL_LINUX_DMA_BUF_EXT` and the
  message's width, height, format, stride and modifier, through `ctypes`;
  the image bound to a texture with `glEGLImageTargetTexture2DOES`, the
  texture read back through a framebuffer and saved.
