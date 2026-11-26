# RDK-E on tv-emu: a proposal, in its first step

A trial of running [RDK-E](https://wiki.rdkcentral.com/x/pVNKG), RDK's stack
for IP video devices, in this emulator. It is a finding and a proposal, not
an agreed requirement: nothing in `openspec/specs/` asks for it, the launcher
does not know it, and it is not part of the target image (`target/`), whose
definition it must not change.

**What there is: a machine definition with a vendor layer for it, and
RDK-E's whole middleware built for it as 64-bit programs. The image boots
host-native on a Mac: Thunder runs with RDK's plug-ins and daemons, RDK's
window manager opens the VM's display through Westeros, and the middleware
reads the device's identity, display, power state and temperature from this
layer's components. There is no application layer: no browser and no user
interface, so the display stays black. Smaller images, with which the steps
were tried one at a time, are described below.**

## The machine: `tvemu-arm64-rdke`

RDK-E is built with Yocto (kirkstone) in three layers that are built apart:
vendor, middleware and application. A device is described by a *machine*
definition and a vendor layer that implements the hardware side. RDK-E's
public reference is the Raspberry Pi 4 (`raspberrypi4-64-rdke`).

[meta-tvemu-rdke](meta-tvemu-rdke) is a Yocto layer with a machine for
tv-emu's ARM64 VM. It is a fusion of two definitions, and every block in its
files says which of the two it is from:

| From | Taken |
|---|---|
| `raspberrypi4-64-rdke` (meta-product-raspberrypi, meta-vendor-raspberrypi-dev) | What makes a machine an RDK-E machine: the includes of the common, middleware and application layers, the overrides `client`, `wpe` and `lxcsecure`, the product settings (systemd, no secure video path, crypto through OpenSSL, the application paths), the vendor layer's package architecture, the list of virtual providers the middleware expects, and the kernel options RDK-E needs (binder, dm-verity, EROFS, AppArmor) |
| `qemuarm64` (openembedded-core) | The hardware: QEMU's `virt` board, the `linux-yocto` kernel, the serial and virtio consoles, Mesa as the graphics stack, a bare ext4 root file system with the kernel beside it, as the launcher boots a VM |
| Neither | The devices of tv-emu's VM in the kernel (virtio disk, network, GPU, input, sound), `/dev/dri/card0` as the display device, Mesa with virgl and llvmpipe |

Left out of the Pi's definition: its boot firmware, device trees, SD card
image, Wi-Fi and Bluetooth firmware, the Broadcom graphics libraries, its
Android kernel, and the overrides `rpi` and `raspberrypi4-64`.

The files:

- `conf/machine/tvemu-arm64-rdke.conf`: the machine.
- `conf/machine/include/tvemu-product.inc`, `tvemu-vendor.inc`,
  `tvemu-preferred-provider.inc`: what the Pi has in `product.inc`,
  `vendor.inc` and `preferred_provider.inc`.
- `conf/machine/include/tvemu-userland-64.inc`, `-32.inc`: see below.
- `recipes-kernel/linux/`: the kernel options, added to `linux-yocto`.

## Host-native means 64-bit programs, and RDK-E is built 32-bit

The Raspberry Pi runs a 64-bit kernel with a **32-bit** userland (Yocto's
multilib `lib32`, ARMv7), and RDK-E's package feeds are built that way.

A host-native VM runs the guest's code on the host's CPU. Apple's CPUs do not
execute 32-bit ARM code at all, so on a Mac a host-native ARM64 VM can run
64-bit programs only. The machine therefore has a setting:

- `TVEMU_USERLAND = "64"` (the default): 64-bit programs only, no multilib.
  This is what host-native on a Mac needs. RDK-E does not do this anywhere
  that was found: its helper that names the package architecture
  (`meta-stack-layering-support`, `get_toolchain_arch`) knows the Pi's
  arrangement and 32-bit CPUs, and calls this one `rdk-arm7ve`, which is
  wrong. The Pi's middleware and application feeds do not fit; both layers
  would have to be built for 64-bit, and it is not known that they build.
- `TVEMU_USERLAND = "32"`: the Pi's arrangement. For a host whose CPU runs
  32-bit ARM code under KVM, and for the simulated CPU (`vm-arm64`). The Pi's
  feeds have the right architecture then (`rdk-arm64`).

On an x86-64 host, host-native is an x86-64 VM, and this machine is not that:
there it is the `vm-arm64` mode, on a simulated CPU. The x86-64 machine below
is for those hosts.

## The x86-64 machine: `tvemu-x86-64-rdke`

`conf/machine/tvemu-x86-64-rdke.conf` is the same fusion with
openembedded-core's `qemux86-64` in the place of `qemuarm64`: QEMU's `q35`
board, the kernel as `bzImage`, the console on `ttyS0`, programs for the
`core2-64` tune. The RDK-E half is the ARM64 machine's, file for file. It is
always built with 64-bit programs. RDK-E has no public x86 build, so
everything here was found by building and running it, on the Linux host
(x86-64, Ubuntu 24.04, QEMU 8.2.2 with KVM) on 2026-11-23:

- *The 64-bit fixes follow the userland, not the CPU.* What the layer
  changed for a 64-bit build of RDK-E's 32-bit code was written for
  `aarch64`; it is now under the override `tvemu64`, which
  `tvemu-userland-64.inc` sets, and holds for both machines.
- *Ne10* (an ARM NEON library) is taken out of the middleware's package
  group, and the *xmidt agent*, which RDK publishes as packages, is taken
  as its x86-64 package.
- *WebKit* needs WebAssembly on x86-64: its optimizing compiler (B3) is on
  there and refers to it, and RDK's recipe turns WebAssembly on for ARM64
  only. The branch-protection setting is ARM64's alone.
- *The kernel's options* are in three files: `tvemu-virt.cfg` for both, and
  one for each board. openembedded-core adds its own sound options for
  `qemux86-64` after them and makes ALSA modules, which left the target
  without a sound card; that feature (`cfg/sound.scc`) is taken out.
- *Thunder ended with a segmentation fault at its first start, in every
  boot.* On this machine Westeros' backend does not get atomic mode setting,
  and in the path without it the refresh thread took the front buffer of a
  window marked for redrawing unchecked, when there was none
  (`gbm_surface_lock_front_buffer` returns NULL). systemd started Thunder
  again, but when the user interface had been started before the fault it
  was gone: about half of the boots. Found on Linux and on macOS on the
  same day; the repair is the one made on macOS
  (`recipes-graphics/westeros-soc/files/0002-no-flip-without-a-new-buffer.patch`).
- *Video from the user interface was black, and the user interface did not
  come back after it.* Seen by the user on 2026-11-23 with Big Buck Bunny
  from "Featured Video on Demand": the sound played, the picture was black,
  and after BACK the display stayed black. On this host the launcher gave
  the VM the host's GPU (virtio-gpu with virgl), which a Mac never gets;
  the pipeline ran without an error (FFmpeg's decoder, `westerosrawsink`,
  AAMP reporting progress), and Westeros drew its frames black. With the
  drawing on the target's CPU (`llvmpipe`, as on the Mac) the card plays and
  BACK shows the home screen again. For an RDK-E target the launcher now
  takes emulated graphics unless `--graphics host` is given. The browser's
  own player (the `rdke-video` check) showed its picture with either.
- *Why it was black with the host's GPU, and the cure* (2026-11-24). The
  sink writes each frame through the CPU's memory into two buffers of the
  DRM device, and Westeros makes an OpenGL ES image of each. With virgl
  such an image is the host's texture of the buffer: what the guest wrote
  is never taken to it, and it has the format the buffer was made with (32
  bits per pixel), not the one asked for. Westeros' renderer now copies the
  two planes into textures where the renderer is virgl
  (`recipes-graphics/westeros/files/0002-copy-video-planes-where-the-renderer-is-virgl.patch`;
  `WESTEROS_RENDER_COPY_VIDEO` in Thunder's environment, 1 or 0, says so
  for any renderer). With `--graphics host` Big Buck Bunny now plays with
  its picture and BACK shows the home screen again (seen in captures of the
  launcher's window, two runs), and the VM's 4 CPUs are 77 % idle during the
  1920x1080 stream. The launcher's window got 22.5 pictures a second of it
  over VNC. Since 2026-11-24 the window takes the GPU's own buffers over
  D-Bus (`emulator/gui/gldisplay.py`; `docs/frame-transfer.md`), and gets
  every picture the target hands over: 30.0 a second of the home screen
  and of the same video with QEMU 8.2.2, which holds a GPU-accelerated
  target to that, and 60.0 of both with a QEMU 11.0.0 built by hand
  (`EMU_QEMU_DIR`). Emulated graphics is still the default for an RDK-E
  target on Linux: with the host's own QEMU its home screen is at 60. Only `libwesteros_render_embedded`, the
  renderer RDK's window manager loads, has the change; the copy was not
  timed, and the frame rate inside the VM was not measured.
- *The launcher's window gets the display over D-Bus on Linux too*, as on
  macOS, for a display that the target's CPU renders (QEMU 8.2.2 has the
  display; `emulator/graphics.py`, `window_endpoint`). Measured on
  2026-11-23 as the pictures that reach the window in 10 s, host-native on
  an Intel Core i7-10700K (8 cores, 16 threads): 59.9 a second at the home
  screen with the VM's 4 CPUs. While Big Buck Bunny plays at 1920x1080 it
  is the VM's CPUs that set the rate, since they decode and draw: 30.0 with
  4 CPUs (`--cpus`; the default), 36 with 6, 56.5 with 8 and 59.3 with 12.
  With 4 CPUs Thunder's process takes 2.1 of them and the web process 0.7.
  Over VNC the window got 23 to 24 a second of the same video with 4 CPUs
  (and none of a still screen, which VNC does not send again). Not
  measured: the pictures the VM itself shows, a stream of 60 frames a
  second, other hosts.
  Why 4 CPUs are not enough here, looked into the same day: the time is
  `llvmpipe`'s. Its four threads are each 57 % busy at 30 pictures a
  second, about 19 ms of drawing for a picture where a refresh is 16.7 ms,
  so every picture takes two refreshes (on the Mac the same threads were
  27 % busy at 35). Two things that could have explained it did not:
  with the VM's four CPU threads held on four separate cores of the host
  (`taskset`) the rate stayed 30.0, and on two cores' sibling threads it
  fell to 24, so the host's scheduler was not putting them badly; and with
  Mesa alone built for `x86-64-v3` (AVX2; 72 thousand AVX instructions in
  the driver where the `core2-64` build has 61) and put into a copy of the
  image, the rate and the threads' load were the same, since `llvmpipe`
  makes its drawing code at run time for the CPU it finds. The whole image
  was not built with that tune: the parts outside Mesa take a quarter of
  the time at most (the web process, 0.7 of a CPU).
  The launcher therefore gives an RDK-E target in a host-native VM half of
  the host's CPU threads when `--cpus` is not given, at least the usual 4
  and at most 8 (`emulator/run.py`, `default_cpus`): 8 on this host. With
  that default, in three runs of four: 60.0 at the home screen and 56.7 to
  58.5 during the video, with `llvmpipe`'s eight threads 61 to 68 % busy.
  The fourth run, the first after the change, gave 35 and 34 with the same
  8 CPUs; what was different in it is not known.
  *A home screen left visible under an application costs that much*, found
  on 2026-11-25 with `./emu verify rdke-rate`, which got 35 pictures a
  second of the video in every run (60 at the home screen). The check
  started the page with the video through org.rdk.RDKShell's `launch`,
  past the user interface. The user interface hides itself when it starts
  an application (`launchApp` in its script calls `setVisibility` for its
  own client with `false`); started past it, it stays visible, the
  compositor draws it under the video at every refresh, and a picture then
  takes longer than a refresh although no thread is busy all the time
  (`llvmpipe`'s eight threads in the compositor 38 % each, the browser's
  14 %). With `setVisibility` for `residentapp`, `false`, the same run went
  from 35.3 to 59.7 at once. The check now makes that call, as the user
  interface would, and gets 60.0 and 60.0 with the VM's CPUs 68 % and 49 %
  idle. An application started some other way than by the user interface
  has to hide the home screen itself, or be given more CPUs or the host's
  GPU.
- *The image keeps 3 MB of journal*, which its services fill in a minute or
  two. The stand-in for org.rdk.RDKShell therefore keeps its lines in
  `/run/tvemu/rdkshell.log` as well, and the checks read both.
- *Left as found:* the Xcast plug-in's process leaves a crash dump at each
  boot (Dobby, the SSH server and the Bluetooth manager, repaired on macOS
  on 2026-11-23, start as meant here too: no failed unit after boot);
  `CONFIG_VIRTIO_INPUT` comes out as a module (the keys arrive through the
  virtio serial port and do not need it); why the backend has no atomic
  mode setting here was not looked for.

The browser image for it (`rdke/build.sh --arch x86_64 --middleware 64
tvemu-browser-image`, 9004 tasks) built in 113 minutes up to WebKit and 68
more for WebKit, with 8 bitbake threads on 16 CPU threads; the kernel is
10 MB and the root file system 948 MB. Started host-native under KVM, the
kernel and init are up in 2 s. `rootfs-option`, `rdke-browser`,
`rdke-launcher` and `rdke-video` pass with it (the browser's page at 27 to
34 frames a second with emulated graphics, the video check's stream playing with the browser's
processes at 137 % of one CPU, sound through virtio-snd to the host).

Not done on the Linux host: the ARM64 image was not built or run there (it
would run on a simulated CPU), and the smaller images (minimal, Wayland,
Westeros, Thunder, middleware) were not built for x86-64 one by one. The
x86-64 image was not tried on Windows or on an Intel Mac.

The x86-64 image was built again on Linux on 2026-11-24 with the Mac's
repairs of 2026-11-23 that were in the repository by then (Dobby's settings
file, the SSH server's key directory, the Bluetooth manager; see "Left as
found" above). It does not have the repair of the DIAL library, which was
not yet in the repository, nor the Mac's work of 2026-11-24 ("The start-up,
looked at again" below: the journal's size, the cloud client, the second
SSH listener, the resolutions, Thunder's listening address, the HLS
stream). None of those changes names a CPU, so they are expected to hold
for it; that is not tried, and the four checks of 2026-11-24 were run on
the Mac only. In turn, the Linux work of that day (Westeros' renderer
copies video planes where the renderer is virgl) is not built on the Mac:
the ARM64 image of 2026-11-24 was built before it came in.

## Building the minimal image

    rdke/build.sh            # 64-bit programs, for a host-native VM
    rdke/build.sh 32         # RDK-E's own arrangement; not built yet
    rdke/build.sh 64 TARGET  # another image, such as tvemu-wayland-image
    rdke/build.sh --arch x86_64 ...   # or arm64; the default is the host's CPU

The image built last for a CPU architecture is the one in `build/rdke/ARCH`
(`arm64` or `x86_64`). What follows was done with the ARM64 machine on macOS.

builds openembedded-core's `core-image-minimal` for the machine, on RDK-E's
common layers, in an Ubuntu 22.04 container, and copies the kernel and the
root file system to `build/rdke/arm64`. Built on the macOS host (ARM64, the
container engine with 6 CPUs and 8 GB) on 2026-11-20: 2379 tasks, no error
left. The kernel is 21 MB and the root file system 57 MB. The build's work is
kept in the container engine's volume `tvemu-rdke-build`, 18 GB after the
build, 12 GB of it downloads; `docker volume rm tvemu-rdke-build` removes it.

What is in the image: the `linux-yocto` 5.15 kernel with this layer's
options, glibc and BusyBox, and RDK-E's systemd 230 (from
`meta-rdk-oss-reference`) with RDK's logger. What is not: Thunder, the
entertainment services, Westeros, a browser, or anything else of RDK-E's
middleware and application layers, and no hardware abstraction.

Two things had to be changed to get there, both kept in the scripts:

- **Yocto's fake-root tool.** RDK's fork of poky has pseudo 1.9.0, with which
  the first packaging step failed every time in this container
  (`linux-libc-headers`, "got *at() syscall for unknown directory").
  `rdke/lib.sh` replaces the recipe with the one of openembedded-core's own
  kirkstone branch (1.9.3), in the fetched copy of poky.
- **Yocto's own QEMU.** Every image of a QEMU machine builds QEMU for the
  build host, for `runqemu`. The machine takes that out
  (`EXTRA_IMAGEDEPENDS`): the emulator has its own.

What the image showed when it was started (`./emu run --mode vm --rootfs
rdke`, host-native on the Mac's hypervisor, the guest reporting the Apple
CPU):

- It boots to a root shell on the console in about 2 s, with an automatic
  login, which the Pi's build configuration turns on (`debug-tweaks`).
- systemd is RDK's 230, and the system comes up "degraded": RDK's
  `syslog-ng.service` ends with status 2 and is not started again. Not
  looked into; its configuration is RDK's.
- The kernel options hold as far as they were looked at: `/dev/binder` is
  there, AppArmor is among the active security modules, and virtio-gpu is
  `/dev/dri/card0` with a render node.
- There is no sound device and no network address: the launcher gives an
  RDK-E target no sound card yet, and the minimal image configures no
  network.

## Wayland on the VM's display

    rdke/build.sh 64 tvemu-wayland-image
    ./emu run --mode vm --rootfs rdke --window

`tvemu-wayland-image` is the minimal image with Mesa, Weston 10 and Weston's
example clients, and two systemd units of this layer
(`recipes-graphics/tvemu-wayland-demo`) that start Weston on the DRM device
at boot, as root, and then `weston-simple-egl`. Built and started on the
macOS host on 2026-11-20:

![Weston with weston-simple-egl on the VM's display](wayland-weston.png)

- The picture above is the VM's display at 1920x1080, taken from QEMU
  (`screendump`): Weston's desktop shell and the client's triangle, which
  turns. The launcher's window shows that display; a run with `--window`
  started and ended without an error, and the window's own picture was not
  looked at.
- Weston renders with OpenGL ES 3.2 on Mesa's `llvmpipe`, that is, on the
  target's CPU: this Mac's QEMU has no host GPU for the guest. The client
  takes about 40 % of one CPU.
- The root file system is 248 MB, most of it LLVM, which `llvmpipe` needs.
  The build volume holds 38 GB after this build, 21 GB of it downloads.

What had to be done beyond naming the packages:

- **The Wayland EGL library.** RDK-E's layers take `libwayland-egl` out of
  Wayland, because a SoC vendor's graphics libraries bring their own, and
  have the plain one as a package, `wayland-default-egl`. Weston's build did
  not find it; `recipes-graphics/wayland/weston_%.bbappend` names it.
- **LLVM and memory.** With 8 GB in the container engine, LLVM's linker was
  ended for want of memory. `rdke/build.sh` has LLVM link one program at a
  time and compile with three jobs.
- **The engine's disk** was enlarged from 60 GB to 200 GB on the Mac
  (`colima start --disk 200`). `setup.sh` still creates 60 GB.

Weston is a stand-in: RDK-E's compositor is Westeros, which is below.

## Westeros on the VM's display

    rdke/build.sh 64 tvemu-westeros-image
    ./emu run --mode vm --rootfs rdke --window

`tvemu-westeros-image` is the minimal image with Mesa, Westeros 2.1.4 and
its device backend for DRM/KMS, and two units of this layer
(`recipes-graphics/tvemu-westeros-demo`) that start Westeros on the DRM
device at boot and then Westeros' own test client, `westeros_test`. Built and
started on the macOS host on 2026-11-20:

![Westeros with westeros_test on the VM's display](wayland-westeros.png)

- The picture is the VM's display at 1920x1080, taken from QEMU: the test
  client's triangle, full screen, composed by Westeros. Both units stayed
  active for the 25 s they were watched, and a run with `--window` started
  and ended without an error; the window's own picture was not looked at.
- Rendering is on the target's CPU (`llvmpipe`), as with Weston. Westeros
  takes about 40 % of one CPU for composing 1920x1080 at 60 frames a second,
  and the client about as much.
- The root file system is 226 MB.

The first part of a vendor layer is what made it work
(`recipes-graphics/westeros-soc`, `recipes-graphics/westeros`):

- **The device backend, `westeros-soc-drm`.** The recipe is the Pi's
  (meta-vendor-raspberrypi-dev) without its limit to the Pi's GPU and its
  Pi-specific patch and switches, at the release the Pi's layer names.
- **No planes.** virtio-gpu has one plane. The backend is told so
  (`WESTEROS_GL_NO_PLANES`), and Westeros composes everything with OpenGL
  ES. Video on a plane of its own behind the graphics, as on a set-top box,
  is therefore not there.
- **An opaque frame buffer** (`0001-graphics-frame-buffer-depth.patch`). The
  backend registers its frame buffer with an alpha channel, for that video
  plane; virtio-gpu's plane takes opaque buffers only, and setting the mode
  failed (`drmModeSetCrtc`, EINVAL). The patch makes the depth a build
  setting, and this machine sets 24.
- **The window's size.** Westeros starts with a window of 1280x720, and the
  backend registers it as a frame buffer of the display mode's size, which
  the kernel refuses when the two differ (`drmModeAddFB`, EINVAL; Westeros
  then ended with a segmentation fault). The unit starts Westeros with
  `--window-size` set to the display's mode, which is the one the emulator's
  `--resolution` gives.
- **Westeros for Mesa** (`westeros.bbappend`): the switches the Pi's layer
  sets for its Mesa driver, and `wayland-default-egl`.

Not looked at: other resolutions than 1080p, Essos, the video sink, and
graphics on the host's GPU.

## Remote control keys

The keys of the emulator's remote control reach Westeros and its clients:
those typed on the host's keyboard in the display window, and those clicked
on the on-screen remote control (Ctrl+Alt+R, or the toolbar).

How a key travels:

1. The display window sends it as it does for the Debian root file system:
   a line, `press CODE` or `release CODE`, with the Linux key code of
   `emulator/remote.py`, down a connection to a port it listens on.
2. For an RDK-E target the launcher gives the VM a virtio serial port named
   `tvemu.remote`, which QEMU connects to that port. Nothing of the target's
   network is used.
3. In the target, `tvemu-remote` (`recipes-support/tvemu-remote`, started by
   a systemd unit) reads the lines and gives the keys to the kernel as key
   events of a keyboard it makes with uinput, "tvemu remote control".
4. Westeros reads the kernel's input devices itself and passes the keys to
   the client that has the keyboard focus, as it does with a real remote
   control's.

Run on the macOS host on 2026-11-20, with `westeros_test --verbose` as the
client: OK, Red, Green, Blue, 5, BACK, Play, P+ and EXIT each arrived as a
press and a release with a key symbol of their own (Return, XF86Red,
XF86Green, XF86Blue, 5, XF86Back, XF86AudioPlay, XF86Close and one for P+),
sent straight from the window's key channel, as a key of the host's keyboard
(G) and as a click on the on-screen remote control (Blue).

- Found, and avoided: `westeros_test` ended with a segmentation fault when it
  got an arrow key. The tool moves its surface on those keys, through
  Westeros' shell interface (`wl_simple_shell`), which it takes a handle on
  only when started with `--shell`; without the option the handle is null,
  and the next frame after an arrow key uses it all the same
  (`westeros-test.cpp`, `drawFrame`, `wl_simple_shell_set_geometry`). It is
  a fault of the tool, in Westeros 2.1.4, and has nothing to do with the
  VM or with how the keys arrive. The unit now starts it with `--shell`:
  run by hand without the option it ended with status 139 on Up, and with
  it it was still running after Up, Up, Left, Down and Right.
- Not tried: the other keys of the 32, a key held down, RedRat input (the
  launcher still refuses a RedRat profile with `--rootfs rdke`), and what
  RDK-E's own key handling makes of these codes, which is in middleware this
  image does not have.
- No verification check covers this; it was run by hand.

## RDK-E's middleware: what a build of it needs

    rdke/probe-middleware.sh        # 64-bit programs
    rdke/probe-middleware.sh 32     # RDK-E's own arrangement

fetches the middleware layers that RDK-E's middleware manifest names and has
Yocto resolve the middleware's package group for this machine, in a dry run:
nothing is built. Run on 2026-11-20:

- **The layers are public.** All seven were fetched without a login:
  meta-rdk, meta-rdk-video, meta-middleware-generic-support,
  meta-rdk-oss-ext-middleware, meta-rdk-bluetooth, meta-python2 and
  meta-oss-common-config. Whether every source repository that their recipes
  name is public as well is seen only when they are fetched in a build.
- **All 3266 recipes parse** with this machine, with either userland.
- **Every recipe of the middleware is there.** What does not resolve is the
  vendor side. 81 of the package group's packages fall away, each for want
  of one of ten things that a vendor layer provides:
  `virtual/mfrlib`, `virtual/vendor-devicesettings-hal`,
  `virtual/vendor-pwrmgr-hal`, `virtual/vendor-deepsleepmgr-hal`,
  `virtual/vendor-hdmicec-hal`, `virtual/vendor-audio-service`,
  `virtual/vendor-systemaudioplatform`, `virtual/vendor-displayinfo-soc`,
  `virtual/vendor-miracast-soc` and
  `virtual/vendor-rdk-gstreamer-utils-platform`; and an eleventh, GStreamer
  (`gstreamer1.0-plugins-base-app`), which the middleware masks in
  openembedded-core because a vendor layer delivers it.
- **64-bit and 32-bit come out the same**: the same ten, the same 81. Nothing
  in resolving the middleware asks for the 32-bit arrangement.
- **Thunder and the core services resolve today**, with no vendor stand-in:
  `wpeframework`, its client libraries, `entservices-apis`, `rbus`,
  `iarmbus`, `rdk-logger`, `telemetry` and `rfc`, for 64-bit: 2976 tasks, of
  them some 200 recipes to compile.
- **There is no browser in the middleware.** No recipe for WPE WebKit is in
  these layers: it is in the application layer.

That a recipe resolves does not say that it compiles, least of all for
64-bit; that is seen in a build.

### Thunder and the core services, built and run

    rdke/build.sh --middleware 64 tvemu-thunder-image
    ./emu run --mode vm --rootfs rdke

`--middleware` adds RDK-E's middleware layers to the build. They set RDK's
own distro, so the build has a directory of its own and compiles the base
system again (once). `tvemu-thunder-image` is the minimal image with Thunder
4.4.8 (`wpeframework`), its client libraries, `rbus`, `iarmbus`,
`rdk-logger`, `telemetry`, `rfc` and `entservices-apis`. Built for 64-bit programs on the macOS
host on 2026-11-20: 3186 tasks, no error left; the root file system is
147 MB. Started host-native:

- `wpeframework.service` is active and listens on 127.0.0.1:9998; the rbus
  router and session manager, the IARM bus daemon and telemetry run beside
  it.
- Asked over JSON-RPC from the target's shell (`curl` to
  `http://127.0.0.1:9998/jsonrpc`), Thunder answers: `Controller.1.version`
  gives 4.4.8, `Controller.1.subsystems` lists Platform, Security, Network,
  Graphics and others as active, and `Controller.1.status` lists its
  plug-ins, the Controller and OCDM.
- So RDK's code for these parts compiles and runs as 64-bit programs. One
  place did not compile as it is: the OpenCDM plug-in prints a `size_t`
  with `%d`, an error under `-Werror=format` where `size_t` is not an `int`.
  The layer relaxes that warning for it
  (`recipes-middleware/entservices/entservices-opencdmi.bbappend`), as RDK's
  virtual-device build does for its power manager plug-in.
- Found and fixed: **activating the OCDM plug-in ended Thunder**
  (`Controller.1.activate`, callsign OCDM), with a segmentation fault. Two
  things came together, neither of them about 64-bit or the VM:
  - The image lacked `entservices-apis`, which has the libraries that carry
    the plug-ins' interfaces between processes (the proxy stubs). The
    plug-in's part in a process of its own could therefore not be
    instantiated ("Failed to find a Proxy"), and the plug-in said so. The
    image has the package now.
  - The plug-in cleans up twice when it cannot start: its `Initialize` calls
    `Deinitialize` itself, which sets its service to null, and Thunder then
    calls `Deinitialize` once more for the failed activation, which uses the
    null service. Any failure to start does that, on any device.
    `0001-ocdm-deinitialize-once.patch` makes the second call return.
  Run after both: the plug-in activates, twice in a row, and Thunder keeps
  its process. With the proxy stubs moved away in the running target, to
  make it fail as before, the activation is answered with an error
  (`ERROR_OPENING_FAILED`), the plug-in stays deactivated, and Thunder keeps
  its process. The plug-in decrypts nothing: the image has no DRM system.
- Found: `dobby.service`, RDK's container daemon, which the packages bring
  with them, does not start. Looked into and repaired on 2026-11-23, see
  "The middleware, built".
- This image has no compositor: it was built to try Thunder alone.

**RDK builds a virtual device of its own.** The middleware layers have a
variant `vdevice_x86-64-mw`: an x86-64 build with a small package group
(Thunder, HDMI-CEC, IARM bus, telemetry, the power manager and LED control
plug-ins) on an XFCE image, with stand-ins for the hardware abstraction
compiled from stubs that the plug-ins' repositories carry (`vdevice-noop`),
and with hardware abstraction over binder (AIDL) for the power manager. Its
vendor and product layers are not public (looked for on 2026-11-20). It
shows that RDK itself builds middleware that is neither ARM nor 32-bit, and
where stubs for a machine without hardware can be taken from.

## The vendor layer: the ten components, and one more

    rdke/build.sh --middleware 64 tvemu-middleware-image
    ./emu run --mode vm --rootfs rdke

RDK-E's middleware expects a vendor layer to provide ten things
(`virtual/...`, see the probe above). The Raspberry Pi's implementations of
them are written for Linux' own interfaces (DRM, ALSA, the kernel's CEC
framework, sysfs), not for Broadcom's. `recipes-vendor` therefore builds
the same sources at the same releases and replaces what in them is the
Pi's. What stands in for hardware that a VM does not have is a file of the
virtual device (`tvemu-device`: `/etc/tvemu`, and `/run/tvemu`, made at each
start), which can be read and written while the target runs.

| Component (recipe) | In the VM | Seen working |
|---|---|---|
| Device settings (`devicesettings-hal-tvemu`) | The display is virtio-gpu's connector, `card0` and "Virtual-1" where the Pi has `card1` and "HDMI-A-1". Its EDID is the one QEMU gives the display. The front panel's LED is `/run/tvemu/leds/ACT`. Temperature and serial number are the virtual device's | Connected displays: HDMI0, with the EDID; connected audio ports: HDMI0. The LED's brightness went from 0 to 255 when the power state was set to ON |
| Display information (`displayinfo-soc`) | `card0` | Connected, 1920x1080 |
| Manufacturer data (`mfrlibs-hal-tvemu`) | Serial number and revision from `/etc/tvemu/cpuinfo`, in the form of the Pi's `/proc/cpuinfo` | Serial number 00000000TVEMU001 and hardware id tvemu1 in the answers of DeviceInfo and System |
| Power manager (`pwrmgr-hal-tvemu`) | The Pi shows its power state in the CPU's frequency governor, which a VM does not have: it is `/run/tvemu/scaling_governor`. The temperature is `/run/tvemu/temperature` | STANDBY to ON through the System plug-in: the file went from `conservative` to `performance`. Writing 71000 to the temperature file changed the thermal state the plug-in reports from 45 to 71 |
| Deep sleep (`deepsleepmgr-hal-tvemu`) | unchanged | built; not tried |
| HDMI-CEC (`hdmicec-hal-tvemu`) | unchanged: it uses `/dev/cec0`, which the VM's kernel does not have | built; not tried |
| System audio (`systemaudioplatform`) | unchanged, on GStreamer | built; not tried: the VM has no sound device |
| GStreamer utilities, platform part (`rdk-gstreamer-utils-platform`) | unchanged | built; Rialto and the media plug-ins build against it |
| Miracast (`miracast-hal-tvemu`) | unchanged, on GStreamer | built; not tried |
| Audio service (`audio-service-tvemu`) | nothing, as on the Pi | |

Also in `recipes-vendor`: two more providers with nothing in them, as on the
Pi (protected-content GStreamer elements, the security API's adapter);
GStreamer's adaptations as the Pi's layer has them; and **`sysint-soc`**, the
vendor's part of RDK-E's system integration, which is not one of the ten and
without which the middleware does not start properly: the device's
properties (`/etc/device-vendor.properties`: make tv-emu, model TVEMU), the
unit `nvram.service` that the plug-ins' start-up waits for, the remote
control's key map, and the settings of Thunder's process for the VM's
display (Westeros' backend, `card0`, no planes). With it RDK's window
manager starts in Thunder and opens the display at 1920x1080; the picture is
black, since nothing is installed that draws.

**The middleware, built.** With these, `packagegroup-middleware-layer`
builds: 8145 tasks, none failing, on the macOS host on 2026-11-20. The image
is 639 MB. Started host-native, the system comes up in about a minute with
one failed unit (`dobby.service`, RDK's container daemon, which ends with a
segmentation fault).

**Dobby ended with a segmentation fault for want of its settings file;
repaired.** Looked into on 2026-11-23. Dobby reads `/etc/dobby.json`. The
middleware's recipe installs its settings as `/etc/dobby.generic.json` and
leaves it to the image to give them that name unless a vendor layer brings
its own; RDK-E's `middleware-test-image` does that, this layer's images did
not. Without the file Dobby takes defaults that have no GPU and VPU part and
prints them through a null pointer (`Settings::dumpHardwareAccess`,
`Settings.cpp:607` of Dobby 3.23.0, from a core dump with the debug
package). `tvemu-middleware-image.bb` now does the step of RDK-E's image.
Run after it, in the browser image: `dobby.service` is active, no unit has
failed, and `DobbyTool list` answers "no containers". No container was
started with it.

**The SSH server did not start; repaired.** At start-up the console showed
"Failed to start SSH Per-Connection Server", again every five seconds. RDK's
start script for it (`/lib/rdk/start_ssh.sh`) ends with
"DROPBEAR_RSAKEY_DIR is not set" unless `/etc/default/dropbear` names the
directory of the host key. A vendor layer writes that for its images and has
the key made there; the Pi's does it in two image steps
(`meta-vendor-raspberrypi-release`, `conf/machine/include/vendor.inc`), and
this layer had neither. `tvemu-middleware-image.bb` now has both, with the
Pi's directory (`/opt/dropbear`). Run after it on 2026-11-23, in the browser
image: the key is made at the first start, `dropbear.service` is active and
listens on the VM's port 22, and no unit has failed. No log-in was tried.
The server takes root without a password, as RDK's development builds do.
The launcher forwards a port of this host's loopback address to it when a run
asks for that (`--option forward=2222:22`, see "Starting an image") and not
otherwise; a log-in from the host was made that way on 2026-11-24.

**The Bluetooth manager is not started.** `btmgr.service` ended with "Could
not initialize BTRCore/HAL module" and was started again for as long as the
VM ran, with "Failed to start Bluetooth Manager Daemon over IARM IPC" each
time: the VM has no Bluetooth controller and its kernel no Bluetooth
("Can't open HCI socket: Address family not supported by protocol"). The
image no longer enables the unit (`tvemu-middleware-image.bb`; the
package's systemd preset is changed as well as the link removed, since the
preset enables the unit again when the image is put together). The package
stays, for the Bluetooth plug-in and the remote control manager link against
its library. Run after it on 2026-11-23: the unit is disabled and inactive,
no unit fails or is started again in a loop, and the plug-in
`org.rdk.Bluetooth` is still activated; no call to it was tried.

**The XCast plug-in's process ended with a segmentation fault; repaired.**
A few seconds after Thunder started, the `WPEProcess` of XCast ended in
`fprintf()`, called from the DIAL server's library (xdialserver,
`gdialService::getInstance` to `gdial_plat_util_log`; from a core dump).
`server/plat/gdial-plat-util.c` calls `basename()` with no declaration in
sight, so the C compiler takes its result to be an int: the whole pointer on
32-bit ARM, its lower half where a pointer has 64 bits. The first message
the library logs is the end of the process. A patch declares it
(`recipes-middleware/xdial`), and the recipe now makes a call of an
undeclared function an error in this library's build. Run after it on
2026-11-23: no process ends with a signal at start, the plug-in is
activated, the library logs, and the DIAL server listens on the VM's ports
56889 and 56890 and on UDP 1900. No DIAL request was made to it.

**The start-up, looked at again on 2026-11-24** (macOS, ARM64,
host-native), with a log-in over the forwarded SSH port:

- *The image kept too little of its journal to say.* RDK-E keeps 3 MB of
  it in memory, in two files, which the middleware fills in under a minute:
  30 seconds after a start the first lines were gone, and "no unit was
  started again" (above, 2026-11-23) was said of what was left. The image
  now keeps 64 MB (`tvemu-middleware-image.bb`), which holds a whole start
  with room to spare (16 MB after 40 seconds).
- *The client of the operator's cloud (parodus, for WebPA) ended at every
  start and was started again every 40 seconds; it is no longer started.*
  Seen as soon as the journal held a start: "Bad webpa url", then an abort
  (signal 6). Its server's address comes from a device's configuration, and
  the virtual device has none. The image does not enable its four units.
- *The SSH server failed its first start in at least four boots of eight,
  with "Failed listening on '22': Address already in use", and started at
  the retry five seconds later; repaired.* The image had both of dropbear's
  units enabled: RDK's `dropbear.service`, which listens all the time, and
  openembedded-core's `dropbear.socket`, with which systemd itself listens
  on port 22. Starting the service closes the socket (they are declared to
  conflict), and by hand that went well 20 times of 20, also with the host
  key still to be made and with RDK's restart of the service on a change of
  address at the same moment; at start-up it did not. Why not was not
  found. The image no longer enables the socket unit, and in eight boots of
  eight after that the server started at once and no unit failed.
- *Two plug-ins are deactivated, and both by design.* `org.rdk.AVOutput`
  refuses to start on anything but a television ("Invalid profile type for
  TV", "Not supported"): the picture settings it has are a TV's.
  `org.rdk.UserPreferences` is started by nothing in the image (the
  middleware's services each have a unit that starts them, and this one has
  none); it starts when asked (`Controller.1.activate`). Neither is changed.
- *The current resolution was given as 720p, and no resolution as
  supported; repaired.* Three causes, one behind the other:
  - The hardware layer asks Westeros' backend for the mode through its
    display server (the socket `display` in `XDG_RUNTIME_DIR`, the one
    `westeros-gl-console` talks to), and the backend starts that server in
    the code that looks for planes, which this image turns off
    (`WESTEROS_GL_NO_PLANES`). With no answer, RDK's service gave the
    resolution it has in store, 720p. A patch starts the server in either
    case (`recipes-graphics/westeros-soc`, the fourth); it is not specific
    to the VM.
  - The television's supported resolutions are read from the display's
    description (EDID), and the launcher starts this image without QEMU's
    (`edid=off`, for a mode of 60 pictures a second). The virtual device now
    has a description of its own, `/etc/tvemu/edid`: a television named
    "tv-emu TV" with 1920x1080 at 60 as its own mode, 720p, 1080p at 50,
    576p and 480p, and two channels of PCM sound. `tvemu-device` makes it
    with a script (`make-edid.py`), and the hardware layer reads it where
    the connector gives none (`recipes-vendor/halif`, the second patch).
    The kernel does not get it: the display's modes are as before.
  - The list of the device's own supported resolutions stayed empty: the
    Pi's hardware layer names its table of resolutions with a count of 0
    ("info available at runtime"), and RDK's device settings plug-in takes
    the list from that table alone. The count is now the table's (the third
    patch). A Pi with the same two releases would have the same empty list;
    that was not tried.
  Seen after it: `getCurrentResolution` gives 1080p60 at 1920x1080,
  `getSupportedResolutions` the table's 18 (480p to 2160p, which is the
  Pi's table; nothing but 1080p was set), `getSupportedTvResolutions` the
  description's, and `readEDID` the 256 bytes.
- *Thunder listens on every address of the target*, not on its loopback
  address alone, as RDK-E's own `middleware-test-image` has it for
  development images: with that, a forwarded port reaches its JSON-RPC
  interface. The VM's network is QEMU's user-mode one, so nothing outside
  this host reaches the target, and nothing on this host does unless a run
  forwards a port.
- *The volume after a start is the hardware layer's choice, not a fault of
  the VM.* The Pi's code sets the soft volume control to 75 % when it
  unmutes with no volume in store (`dsAudio.c`), and RDK's display settings
  service reports 75 as well (it was noted as 100 on 2026-11-21, which was
  after the check had set it). Left as it is.
- *Thunder no longer ended when one display was taken away and another
  made at once* (below, "Video and sound": about three starts of ten on
  2026-11-21). In twelve such changes of twelve, in one boot of the image
  of 2026-11-23, Thunder kept running. The fault had the mark of the one
  the second `westeros-gl` patch repaired the day before (signal 11 in the
  refresh thread, a window marked for drawing with no buffer); that it was
  the same one was not shown.

**What RDK-E's code assumes of 32-bit ARM.** Found by building and running
it as 64-bit programs; each is handled in this layer, with a comment at the
place:

- *Formats.* By far the most common: sizes, 64-bit numbers and times printed
  with formats that fit on 32-bit only, in recipes that make the warning an
  error. Not errors here, for all service plug-ins and five other components
  (`recipes-middleware/include/tvemu-64bit-formats.inc`).
- *Handles in 32 bits.* RDK's device settings plug-in keeps the hardware
  layer's handles in an `int32_t`; its interface is defined so. A handle is
  an address, and half of a 64-bit address is lost: the hardware layer
  refused every handle, and no display was reported. The hardware layer here
  puts the lost half back where a handle comes in (`dsHalWidenHandle`, at
  136 functions). It can, because its handles all point into its own tables.
- *A length written through the wrong pointer* in the TR-069 component
  (patched), *a pointer cast to a 32-bit number* in rtRemote (let through),
  *code that is not position-independent linked into a shared library* in
  the app managers (compiled so now), and *a callback whose handle is an
  `int`* in the device settings manager (let through).
- *32-bit only inputs:* two of RDK's patches to GStreamer set a compiler
  option of 32-bit ARM (left out for 64-bit), and a cloud agent is unpacked
  from a package built for 32-bit ARM (the 64-bit one of the same release is
  taken).

**What only RDK-E's layered build hides.** RDK builds vendor layer and
middleware apart and joins them as packages. Built in one build: the
Bluetooth stack is patched and installed by two layers (one is masked),
three files are provided by two packages each, a library does not name the
platform part it links against, and one source has its revision from the
vendor layer.

**Not done, of "as much as feasible":** a simulated HDMI link for CEC (the
kernel has a virtual CEC driver); a sound device, without which the audio
settings and system audio have nothing to act on (the image has had one
since 2026-11-21, see "Video and sound"); power states and the display's
resolution tied to the launcher. The resolutions are reported rightly since
2026-11-24 (above), and `rdke-device` checks the display, the identity, the
power state and the front panel as RDK's services give them.

## The browser, and RDK's user interface

    rdke/build.sh --middleware 64 tvemu-browser-image

builds `tvemu-middleware-image` with RDK's browser and RDK's reference user
interface on top:

- **WPE WebKit 2.46.2**, from RDK's own recipe and with RDK's patches, and
  its backend for Westeros (`wpe-backend-rdk`, through Essos).
- **The browser's Thunder plug-in** (`webkitbrowser-plugin`), which offers
  the browser under several call signs with their own settings:
  `WebKitBrowser`, `HtmlApp`, `LightningApp`, `ResidentApp` and others.
- **RDK's reference user interface** (`rdke-refui` 5.0.24, a Lightning
  application), served by the image's own web server as on a device, and
  started at boot in `ResidentApp` (`tvemu-refui`).
- **A page to try the browser on** (`tvemu-browser-page`), which shows the
  size of its window, a count of frames drawn and the last key it was given.
- **`tvemu-app-start CALLSIGN URL`**, which shows a page in one of the
  plug-in's browsers, full screen and with the keys.

On a device the user interface comes from RDK-E's third layer, the
application layer (`meta-application-rdke-dev`), which is built apart from
the middleware and joined to it as packages. Here its two recipes for the
user interface are redone in this layer, so that one build gives the image.

**RDK-E no longer has the browser in the middleware.** Its configuration sets
the distro feature `enable_bolt_apps`, which takes WPE WebKit, the plug-in
and the backend out of the middleware's package group: the browser is meant
to come as an application package, run in a container by the application
managers. This image names them itself, as RDK devices had them before. The
container daemon that the new way needs (Dobby) starts here since
2026-11-23, but no container was run with it, see "What is open".

**RDK's start script for the user interface does not fit this middleware.**
`residentApp.sh` calls `org.rdk.RDKShell.1.launch`. This middleware has
`org.rdk.RDKWindowManager` in RDKShell's place, which makes displays and
gives the focus but starts nothing. `tvemu-app-start` does the three steps
that "launch" did: a display from the window manager (`createDisplay`, named
`wst-` and the call sign, which is the name in the plug-in's configuration),
the plug-in started and given its address through Thunder's controller, and
the focus (`setFocus`).

**The user interface itself starts every application with RDKShell too.**
A card on its Home screen ends in `org.rdk.RDKShell.1.launch`; before that
the interface shows an empty page of its own and asks RDKShell which kinds
of application there are (`getAvailableTypes`). Without RDKShell that
question fails and the empty page stays: a card gave a blank screen. The
releases of the user interface from 6.0 on have no RDKShell calls; they
start applications with `org.rdk.AppManager`, as packages in containers,
which is RDK-E's way and is not tried here (see "What is open").

The image therefore has a **stand-in for RDKShell** (`tvemu-rdkshell`): a
Thunder plug-in under the call sign `org.rdk.RDKShell` that answers the
calls this user interface makes, with the window manager and the
applications' own plug-ins.

| RDKShell's call | What the stand-in does |
| --- | --- |
| `launch` | a display from the window manager, the application's plug-in activated on it and given its address, the focus; the event `onLaunched` |
| `destroy`, `kill` | the plug-in deactivated; the event `onDestroyed` |
| `suspend` | the plug-in suspended, its display hidden |
| `setVisibility`, `getVisibility`, `setFocus` | the window manager's `setVisible`, `getVisibility`, `setFocus` |
| `addKeyIntercept(s)`, `removeKeyIntercept` | the window manager's calls of the same names |
| `enableInactivityReporting`, `setInactivityInterval`, `resetInactivityTime` | the window manager's calls of the same names |
| `getAvailableTypes`, `getState` | the browser's call signs that this Thunder has, and those that run |
| `getClients`, `getZOrder` | the window manager's displays |
| `moveToFront`, `moveToBack`, `moveBehind`, opacity, scale, bounds, animations | answered with success, nothing changed |
| `launchApplication` (a native application) | refused |

It is started by a unit of its own (`wpeframework-rdkshell.service`), as
RDK-E starts Thunder's plug-ins, and the user interface's unit waits for it.
RDKShell's other events (first frame, inactivity, focus) are not sent.

**The first-run steps are marked as done.** The user interface shows its
first-run steps (pair a remote control, with a countdown of 30 s; choose a
language; set up the network) until it has once reached its Home screen,
which it notes in the browser's storage. The emulator discards what a
target wrote when it ends, so every start was a first run. The image's copy
of the user interface loads a script before it (`tvemu-first-run.js`) that
sets that note, and the interface goes from its splash picture to Home. To
see the first-run steps:

    tvemu-app-start ResidentApp 'http://127.0.0.1:50050/lxresui/index.html?firstrun#splash'

**The EXIT key ends an application.** The user interface asks for the keys
Home and Escape wherever the focus is, and takes either as the way back to
its Home screen. The emulator's remote control has EXIT, whose Linux key
code the Pi's key map for the window manager does not have; it arrived as
"volume down". The image's key map (`/etc/rcu_keymap.json`, from
`sysint-soc`) is the Pi's with five keys added: EXIT as Escape, and the
four colour keys, whose Linux codes the window manager does not know.

**Three things had to be changed for the browser to run:**

- *The names of the graphics libraries.* RDK patches libepoxy to take them
  from the build, for a vendor layer to give. Without them libepoxy looks
  for a library called `EGL_LIB_NAME`, and the browser's web process ends at
  its first drawing call. The layer gives Mesa's.
- *Branch target identification (BTI).* openembedded-core builds 64-bit ARM
  code with `-mbranch-protection=standard`, which marks WebKit's library as
  safe for BTI. The JavaScript interpreter in it is assembly without the
  landing instructions that the marking promises. An Apple CPU has BTI, a
  host-native VM gives it to the target, and the kernel ended the web
  process with "undefined instruction" at the first script it ran. A
  Raspberry Pi 4's CPU has no BTI and does not show this. The layer builds
  WebKit without the option.
- *RDK's player (AAMP).* The plug-in's bindings for it need AAMP built, and
  AAMP did not build here. The bindings were left out at first; "Video and
  sound" says what it took to have them.

WebKit is also the one thing here that a container engine with 8 GB cannot
build as it is: a single source file took 5.4 GB to compile. The build ran
with two compilers at a time, without link-time optimisation, and with 8 GB
of swap added to the engine's VM for the time of the build.

**What was seen**, on macOS (ARM64), host-native, on 2026-11-21:

- **The image starts RDK's user interface by itself.** At first the display
  showed the reference user interface's first-run steps about 50 s after
  the kernel started, and it was taken through them with the remote
  control's keys (pairing a remote control skipped, a language chosen, the
  network step skipped) to its Home screen, with the RDK logo, its side
  menu and its rows of applications. With the first-run steps marked as
  done, the image's log has the interface at its Home screen 10 s after
  systemd starts, and a capture 45 s after the launcher was started shows
  it. Some of those tiles stay plain colours:
  their pictures are fetched from the internet and did not all arrive.
- **The page in `HtmlApp`** (`browser-page.png`, taken from QEMU), after
  `systemctl stop tvemu-refui` and
  `tvemu-app-start HtmlApp file:///usr/share/tvemu/page/index.html`: full
  screen at 1920x1080, with the plug-in reporting 31 to 45 frames a second.
  The drawing is done by Mesa's `llvmpipe`, on the target's CPU.
- **Keys in the page.** OK, the four arrows, Back, the digit 1 and Play, sent
  from the launcher's window, arrive in the page as `Enter`, `ArrowUp`,
  `ArrowDown`, `ArrowLeft`, `ArrowRight`, `Backspace`, `1` and `MediaPlay`,
  with the key codes a web page expects (13, 38, 40, 37, 39, 8, 49, 179).
- **Applications from the Home screen.** With the stand-in for RDKShell,
  the first two cards of the row "Lightning Apps" (GuessThatCity, FRacer)
  each opened their application full screen in the plug-in `LightningApp`;
  the applications are fetched from the internet. The arrow keys moved the
  selection inside FRacer, which showed 37 to 47 frames a second. EXIT ended
  each application and brought the Home screen back, with the card still
  selected. The other cards and rows were not tried.
- **The colour keys and EXIT in a page:** `ColorF0Red`, `ColorF1Green`,
  `ColorF2Yellow`, `ColorF3Blue` (403 to 406) and `Escape` (27).
- **`./emu verify rdke-browser`** does the page and its keys by itself and
  passes (28 s): it boots the image, shows the page, compares the picture
  in the launcher's window with what the page draws, and sends thirteen
  keys.
- **`./emu verify rdke-launcher`** passes (28 s): with the user interface
  running it calls RDKShell's `launch` for `HtmlApp` with the image's page,
  as the user interface does for a card, finds the page's picture in the
  window, sends OK to the application, and ends it with EXIT. Before it
  waited for the user interface to ask for its keys, EXIT was not taken in
  about one run of five; it presses EXIT again in that case. The presumed
  cause, that the user interface takes no key while it changes screens, was
  not confirmed.

**Found, and open:**

- *The user interface asks for plug-ins that are not there* (HdmiInput,
  UsbAccess, Cobalt, Amazon, Netflix, FireboltApp), and Xcast ends with a
  failure after it starts. The interface carries on without them. Its cards
  for those applications (YouTube, Netflix, Amazon) cannot start anything.
- *The stand-in keeps no stacking order.* The user interface hides itself
  when an application starts and shows itself when it ends, so nothing was
  seen to be wrong; a picture of the interface over a running application
  (its volume or settings overlays) was not tried.
- *The browser of the user interface is over its memory limit:* Thunder
  logs "Critical memory usage" for it (about 260 MB of 250 MB) at the Home
  screen. Nothing was seen to follow from it.
- *No video was played* from the Home screen.
- *Not tried:* video and sound in the browser, the other call signs
  (`WebKitBrowser`, `LightningApp`), the web inspector, a simulated CPU
  (`--arch arm64` on a host that is not ARM64), and any host but the Mac.

## Video and sound

The browser image plays video with sound in RDK's browser, with the
target's CPU doing the decoding. Four things were missing or wrong, and one
fault was found in the browser:

**The VM had no sound card.** The launcher gave a target from the RDK-E
root file system no driver features at all. It now gives it the emulated
sound card (virtio sound), with the host-side sound process behind it, as
it does for the Debian root file system's sound workloads. The kernel
already had the driver. `--mute` and `./emu audio` work as for those.

**ALSA's default device was the Pi's.** The device settings component, whose
source is the Pi's, installs `/etc/asound.conf` and names the Pi's HDMI sound
card in it and in its code. The default device could not be opened, and
nothing played. The recipe now names the VM's card ("SoundCard") and its
plain PCM output. The soft volume control of that configuration is kept:
RDK's volume setting (`org.rdk.DisplaySettings`, `setVolumeLevel`) moves it.

**RDK's FFmpeg has no video decoders.** RDK builds FFmpeg with audio
decoders only, since a device decodes video in its hardware, behind the
vendor's video sink. The layer adds the decoders for H.264, HEVC, MPEG-2,
VP8 and VP9 (`ffmpeg_%.bbappend`), and the image has GStreamer's FFmpeg
plug-in (`gstreamer1.0-libav`, whose licence flag the Pi's vendor
configuration, taken over here, already accepts). These are software
decoders of patented formats: that is a matter for whoever distributes an
image, and is why RDK leaves them out.

**A video with the `loop` attribute stops.** This is a fault in the image's
WebKit (2.46.2) with its GStreamer (1.18), not in the VM, and it is not
repaired here. WebKit plays a looping video as a "segment", and takes the
message that the segment is done as the end of the stream. GStreamer's MP4
reader sends that message when it has *read* the file to its end, which for
the five-second reference stream is about 2.3 seconds into playing it.
WebKit then seeks to the start in the middle of the stream, and that seek
does not complete: the sound card's output stays paused, the player's time
stands still, and the page still says "playing". It was first taken for a
fault in how WebKit draws video without the vendor's sink, and WebKit was
built with GStreamer's GL path to go around that; it then stopped in every
start, where before it stopped in about one of three. The media
framework's own log showed the cause. WebKit is built as RDK configures it
again, and the reference page starts the stream again itself when it has
ended. `video.html?loop` uses the attribute, and shows the fault.

WebKit draws the video itself: RDK builds it to leave a hole in the page for
the vendor's video sink, which is only done where a device says so
(`WEBKIT_GST_HOLE_PUNCH_QUIRK`), and the VM does not.

**There was nothing to play.** The image has the H.264 and AAC reference
stream of the emulator's media checks (`tvemu-media`: 1280x720, 25 frames a
second, 5 seconds, marker blocks in its corners, an 880 Hz tone) and a page
that plays it again and again and says in its address what the player reports.
`rdke/build.sh` makes the stream with `target/media/build-media.sh`, as the
Debian target's build does; it is not kept in the repository.

    tvemu-app-start HtmlApp file:///usr/share/tvemu/media/video.html

**The user interface plays its video with RDK's player (AAMP), and five
things kept that from working.** A card of "Featured Video on Demand" ended
in "AAMPMediaPlayer is not defined". The interface plays those streams (HLS,
from public test servers) with AAMP through bindings in the browser.

- *AAMP was not built.* RDK-E's configuration for bolt apps
  (`rdke-rdkm-config.inc`) takes the features `webkitbrowser-plugin` and
  `build_external_player_interface` away, and with them AAMP's bindings and
  the library AAMP is linked against (the player interface). The layer names
  both for AAMP again.
- *The player interface needs a library that the public layers do not have.*
  As RDK-E builds it, it reaches the device through RDK's Firebolt SDK for
  AAMP (`FireboltAamp`); RDK-E's configuration leaves the library out "until
  RDKMVE-2474 gets resolved". Here it is built as its source builds it on a
  desktop, with a patch that offers that way to a device build: it asks the
  device nothing about its display and outputs, so nothing that depends on
  the answer (content protection by output, for one) is there.
- *There was no video sink.* The Pi's environment for Thunder tells AAMP to
  use `westerossink`, a device's sink that decodes in hardware. The VM
  decodes with FFmpeg, so the layer builds the variant of the same sink that
  takes decoded frames (`westerosrawsink`, recipe `westeros-sink`), and
  AAMP's pipeline finds it by its rank. That sink asked the DRM device for
  buffers of one byte per pixel; virtio-gpu makes buffers of 32 bits per
  pixel only, the request failed, and the sink wrote the frame to an address
  that was not mapped, which ended the browser's web process. A patch asks
  for the same bytes as a 32-bit buffer.
- *The picture was black.* Westeros took the sink's two buffers (brightness,
  colour) as one two-plane image, which Mesa's `llvmpipe` draws black. With
  OpenGL ES's external images hidden from Thunder's process
  (`MESA_EXTENSION_OVERRIDE`), Westeros takes each buffer as an image of its
  own and converts the colours itself.
- *AAMP chose a Dolby sound track.* The image has no decoder for one, and
  the pipeline ended with "missing a plug-in". AAMP is told that the device
  has none (`AAMP_CFG_TEXT`), and takes the stream's AAC track.

AAMP's own build also stopped on a size printed with `%d`, which is an error
only in a 64-bit build.

**What was seen**, on macOS (ARM64), host-native, on 2026-11-21:

- **`./emu verify rdke-video` passes**, in ten starts of ten: the page is
  started over the user interface with `org.rdk.RDKShell`'s launch, the
  player's time moves, the launcher's window shows the stream's picture full
  screen with its marker blocks in the stream's colours, and the stream's
  880 Hz tone reaches the host-side sound process and the host's output
  device (played at volume 0 for the check). Two of the ten took longer than
  the others (49 s and 120 s, against 34 s); why was not looked at.
- The same was seen with WebKit built with GStreamer's GL path, in six
  starts of six, up to the host's output device, which took no sound at the
  time.
- Pausing and resuming the sound card's output directly (ALSA, without the
  browser) works, on the plain device and through the soft volume control.

And on 2026-11-22, by hand (the remote control's keys sent to the launcher's
window, captures of the window, the sound that reached the host-side sound
process):

- The first card of "Featured Video on Demand" plays Apple's HLS test
  stream: the stream's own clock in the picture went from 19.13 s to 27.00 s
  between two captures taken about 8 s apart, and the stream's tones reached
  the host-side sound process.
- The second card plays its stream at 1920x1080. BACK returns to the user
  interface, and the card plays again when started again.
- The browser's web process did not end in these runs.
- `./emu verify rdke-video rdke-browser rdke-launcher audio-host-vm` pass on
  the image with these changes, once each.

**Found, and open:**

- *Video was shown at far fewer pictures a second than the stream has; repaired.*
  Measured on 2026-11-22 with a 1920x1080 stream of 60 frames a second:
  FFmpeg and the sink deliver 53 to 57 frames a second and Westeros takes
  about 55 (the same stream in a test pipeline), but RDK's window manager
  put 22.6 pictures a second on the VM's display, and the launcher's window
  got 6 to 7 of them a second in most runs (about 19 in one).
  The window manager draws 40 times a second by default and waits a whole
  frame's time before each drawing; the swap then waits for Westeros' own
  60-a-second timer, so a picture came every 33 or 50 ms in turn. The image
  now sets `RDK_WINDOW_MANAGER_FRAMERATE=60`, with which the VM's display
  gets 31 pictures a second at the home screen and 35 while the 1080p
  stream plays.
  *Repaired on 2026-11-23: the display now gets 60 pictures a second, at
  the home screen and while that stream plays, all drawn by the VM's CPU.*
  The drawing was never the limit: at 35 pictures a second each of
  `llvmpipe`'s four threads was 27 % busy. Three things were:
  - *Each picture took two rounds of Westeros' refresh thread.* The window
    manager's swap waits for that thread (`WESTEROS_GL_USE_REFRESH_LOCK`),
    and marked its window as changed only after the wait, so the buffer was
    shown a round later than it could be. And with no vertical blank to
    wait for (`WESTEROS_GL_NO_VBLANK`) a round was not a refresh interval
    long but the work plus a fixed sleep. A patch to `westeros-gl`
    (`recipes-graphics/westeros-soc`, the third) marks the window before
    the wait and times the rounds by the clock.
  - *The window manager's wait before each drawing.* It has to fit in one
    round together with the drawing, so the image now sets
    `RDK_WINDOW_MANAGER_FRAMERATE=1000` (a wait of 1 ms) and the swap is
    what paces the window manager. A number above 60 used to end Thunder
    at once (this is the "5" of before: a restart loop). The refresh thread
    asked for a buffer when none had been swapped since the last one it
    showed, got none, and used it (signal 11 in `wstVRefresh`, in
    `gbm_bo_get_handle`); the second patch adds the check that the other
    path of `westeros-gl` already has.
  - *The display mode was one of 75 pictures a second.* QEMU's display
    device describes its monitor that way and has no setting for it, and
    Westeros shows a picture each refresh. For this image the launcher now
    leaves the description out (`edid=off`), and the kernel then makes the
    mode itself, at 60.
  Measured by hand through the launcher as it is (macOS, ARM64,
  host-native, 4 CPUs for the VM): 59.9 pictures a second at the home
  screen and 59.8 to 60.0 while the 1920x1080 stream of 60 frames a second
  plays, with the same number reaching the launcher's window; the VM's
  CPUs are 41 % idle during the stream, and QEMU takes 1.5 of the host's
  CPUs at the home screen and 2.6 during the stream. All 60 pictures taken
  of the still home screen are the same and none of 60 taken during the
  stream has a black patch. Without the refresh lock the rate was 51 to 59
  but 11 to 14 pictures in 60 had black patches, since the lock is also
  what finishes the drawing before the swap. Not measured: whether each of
  the stream's frames is shown once (the sink's count of dropped frames),
  other streams, a host with fewer or slower CPUs.
  The faster pace first showed a fault: about one picture in twenty lacked
  a part of what it should show (the logo missing from the home screen for
  one picture, black patches in video), in QEMU's own display. Westeros
  reads a client's buffer where it is and gives it back to the client when
  the next one is committed, while Mesa's `llvmpipe` does the drawing only
  when the picture is swapped; the client was by then drawing its next
  picture into the buffer. Westeros finishes each surface's drawing before
  going on for one platform (Broadcom Nexus); a patch asks for the same
  here (`recipes-graphics/westeros`). Of 160 pictures of the still home
  screen, 10 lacked a part without it and none with it, and none of 240
  taken during the 1080p stream had a black patch.
  The way from QEMU to the window was the launcher's fault, and is repaired
  on macOS: QEMU sent each picture (8 MB, uncompressed, over VNC) through a
  private Unix socket, which takes 8 KB at a time on macOS, one piece each
  time QEMU's event loop came round: 130 to 200 ms a picture. Over a port of
  the loopback address a picture arrives in 8 ms, and the window gets 12 to
  18 pictures a second of what the VM shows (23 then, about 35 now). The launcher now uses the port on
  macOS as it does on Windows; it has no password, so programs of other
  users of the host can see the display and send keys during a run. What
  holds the window at about 16 to 18 now is QEMU's own pace for VNC: its
  server looks every 30 ms, and waits 50 ms longer after each look that
  found nothing new, so pictures leave it 40 ms apart at the median and
  115 ms apart one time in ten, while the VM shows one every 28 ms. A
  client that draws nothing was tried against it in several ways on
  2026-11-22: asking again before the pixels are read, keeping two requests
  open and 16-bit pixels (an eighth of the bytes) all gave 15 to 16 a
  second; asking for the whole display each time gave 21. So VNC does not
  get the window to what the VM shows, whatever the client does.
  The launcher's window now follows QEMU's D-Bus display on macOS in place
  of VNC (`emulator/dbusdisplay.py`): QEMU sends each picture when the VM
  shows it, over a private socket pair, and the window gets all 35 to 36 a
  second, at the home screen and while the 1080p stream plays, with the
  window's process at 4 to 6 % of a CPU.
- *With the host's GPU the user interface is no faster, and video ends
  Thunder.* Tried on 2026-11-22 with the experimental QEMU for macOS
  (`./setup.sh --experimental-qemu`, `--graphics host`, QEMU's own window):
  the image starts, the VM's kernel reports virgl, and at the home screen
  the VM's CPUs are 98 % idle, yet the display still gets 22 pictures a
  second. So the drawing was never what held the user interface at 22.6:
  it is the window manager's wait of 25 ms before each picture together
  with Westeros' own 60-a-second timer, which the swap waits for (the two
  give a picture every 33 or 50 ms in turn). When the video sink hands
  Westeros its first frame in this mode, Thunder ends and is started
  again: the sink's buffers of the DRM device are not something the host's
  renderer takes as they are. Not looked at further. In this mode there is
  no launcher window either: keys sent through QEMU's control channel did
  not reach the user interface, and the display cannot be captured, so
  what the window showed was not seen by the one who ran this.
  Tried again on 2026-11-23, before and after the repair of the picture
  rate above: the display gets 2 to 6 pictures a second with the VM's CPUs
  about 85 % idle, where the VM's CPU now draws 60. The window manager's
  pace makes no difference, and neither does Westeros' finishing of each
  surface (2.2 with it, 3.9 without: `WESTEROS_RENDER_NO_FINISH=1`). The
  cause is not found. The machine was used over a remote connection during
  these runs, and whether macOS held back QEMU's window for that was not
  looked at. Thunder did not restart when `westerosrawsink` started in
  these runs. QEMU's display without a window (`egl-headless`) crashes on
  macOS, so a display drawn by the host's GPU has no way into the
  launcher's window there.
  Found and repaired on 2026-11-24 (`docs/frame-transfer.md`, "Measured on
  the Mac"): the target handed over 25 pictures a second because QEMU
  answers the GPU's fences from a timer of 10 ms on macOS, and four of them
  go into a picture; and QEMU's D-Bus display, which feeds the launcher's
  window, used OpenGL on a thread that had not initialized it. With this
  project's change to the experimental QEMU the launcher's window shows the
  host-drawn display at 60.0 pictures a second at the home screen and 60.1
  during video, with the VM's 6 CPUs 97 % and 83 % idle (emulated graphics
  in the same runs: 60.0 and 55.8, 68 % and 47 % idle), and AAMP and the
  browser's own player play the reference stream with picture and sound.
  `./emu verify rdke-rate-host` checks the rate and the picture. Until
  2026-11-25 emulated graphics was what an RDK-E target got unasked there.
  Since that evening, at the user's direction, a host-native RDK-E target
  on a Mac is drawn by the host's GPU unasked where a QEMU that reads the
  picture back is installed (`./setup.sh --experimental-qemu`); the run
  says so, `--graphics emulated` asks for the other, and a Mac without
  that QEMU emulates as before. The image's checks then run with the
  host's GPU as well, except `rdke-rate`, which asks for emulated graphics
  by name. `rdke-rate-host-60` plays a 1920x1080 clip of 60 frames a
  second, made on the host with the Debian image's FFmpeg, and asks 50
  pictures a second of the window and 50 shown frames a second of the
  browser's player; that floor is the reference stream's, and no number
  of its own is agreed for the clip. The ARM64 image was built again that day with the
  renderer's change for virgl, which AAMP's frames need there.
- *RDK's HDMI-CEC reader kept one of the VM's CPUs busy; repaired.* The VM
  has no CEC adapter, so the driver cannot be opened, and the library's
  reader thread (`Bus::Reader::run`) then asked the unopened driver for a
  frame again and again without a pause, each time answered by an exception.
  A patch to the library (`recipes-middleware/hdmicec`) has it wait 100 ms
  after such an answer. No thread of Thunder is busy at the home screen
  now. In one run after the change the video card stayed black; it played
  in the two runs after that, and what happened was not found.
- *No check plays a stream with AAMP.* What is said of it above was seen by
  hand. The user interface's streams are on public servers, so a check of
  them would depend on the network; a stream in the image, in a form AAMP
  takes (HLS or DASH), is not made yet.
- *A capture can show a picture in part.* One capture of 1080p video had a
  band of another frame at its top. The launcher's window gets a picture in
  several pieces and a capture can fall between them; whether the sink's
  reuse of its three buffers adds to it was not looked at.
- *Hiding external images is for the whole of Thunder's process*, the
  browser included. The checks of the browser pass with it. Whether the
  two-plane image also fails with the host's GPU (virgl) was not tried.
- *The device starts at three quarters of its volume.* The sound card's soft
  volume control is at 75 % after boot (about 13 dB down). Setting the
  volume through RDK's display settings service puts the control where the
  service says. Looked into on 2026-11-24: it is the Pi's hardware layer
  that chooses 75 %, and the service reports the same (see "The start-up,
  looked at again").
- *Thunder ends with a segmentation fault when one display is taken away
  and another made at once.* The check first stopped the user interface
  (`systemctl stop tvemu-refui`) and started the page with
  `tvemu-app-start`; in about three starts of ten Thunder (`WPEFramework`)
  then ended on signal 11 in Westeros' refresh thread (`wstVRefresh`), and
  systemd does not start it again. It was not seen when an application is
  started over the running user interface, which is what the check does
  now. The cause was not looked for. Not seen again on 2026-11-24, in
  twelve tries (see "The start-up, looked at again").
- *Looping video*, as above: a page that sets `loop` on a video sees it stop.
  Later WebKit and GStreamer versions were not looked at for a repair.
- *A host output device that takes no sound.* The host-side sound process
  now keeps at most a second of sound waiting for the host's player and
  drops what is older, so that the target is not stopped by it; before, the
  VM stood still with the device.
- *AAMP has a stream in the image and a check, since 2026-11-24.* The
  reference stream is in the image as an HLS stream too (`hls.m3u8`, the
  stream of `avc.mp4` in five segments of a second, which `rdke/build.sh`
  makes without encoding it again), with a page that plays it with AAMP's
  object (`aamp.html`). The browser gives a page that object only when its
  address has a host (`CanInjectJSBindings` in the plug-in's extension), so
  a page from a file has none; the image's web server, which serves the
  user interface, serves the directory as well
  (`http://127.0.0.1:50050/tvemu-media/aamp.html`). `./emu verify
  rdke-aamp` plays it: the picture in the launcher's window and the tone at
  the host. AAMP was seen to stay at the end of this stream without
  reporting that it had completed, and to report a time that runs ahead of
  the picture; the page starts the stream again when the time stands
  still.
- *Not tried:* DASH, and adaptive streams and Media Source Extensions in the
  browser's own player (HLS was played with AAMP only), the other codecs,
  Dolby sound, protected content, subtitles, seeking and trick play in AAMP,
  and a simulated CPU.

## Starting an image

    ./emu run --mode vm --rootfs rdke [--window]

The launcher does not build the image. It looks in `build/rdke/ARCH` for the
guest's CPU architecture, `arm64` or `x86_64` (or in the directory that
`--option rdke-dir=DIR` names), for

- the kernel, as `Image` or `bzImage` (Yocto's names for it; `vmlinuz` is
  taken too),
- the root file system, as `rootfs.ext4` (or `rootfs.img`): the image's
  `.ext4` file from Yocto's `tmp/deploy/images/MACHINE/`, copied
  under that name,
- and, only if the image has one, an initial RAM disk as `initrd.img`.

It boots them in a VM of that architecture (`--arch native` for the host's
own, which is the default; `--arch arm64` on an x86-64 host for the ARM64
image on a simulated CPU) with a virtio disk, network and display, and with
the kernel command line `console=ttyAMA0 root=/dev/vda rootfstype=ext4 rw`
(`ttyS0` for x86-64). Where only the other architecture's image is built,
the launcher names it. The
root file system is not written to: changes are discarded when the VM ends.
The target's console is in the terminal, boot messages included
(`--option verbose-boot=no` turns them off).

What is typed or piped into the launcher goes to the target's console, so
the shell can be used from a script as well:

    (sleep 10; echo 'uname -a'; sleep 2) | ./emu run --mode vm --rootfs rdke --timeout 20

A run reaches ports of the target from this host where it asks for them:

    ./emu run --mode vm --rootfs rdke --window --option forward=2222:22,9998:9998,10000:10000

    ssh -p 2222 root@127.0.0.1
    curl -d '{"jsonrpc":"2.0","id":1,"method":"Controller.1.status"}' http://127.0.0.1:9998/jsonrpc

`--option forward=HOST:TARGET[,HOST:TARGET...]` has QEMU listen on the HOST
ports of this host's loopback address, and on no other address, and pass
each connection on to the target's port: here the SSH server (root, no
password), Thunder's JSON-RPC interface, and the web inspector of the user
interface's browser (10000; `HtmlApp` has 10001). Nothing is forwarded
unless a run asks: the SSH server lets in whoever reaches it. A port of
this host that is in use is named before the VM is started. The option is
the launcher's and holds for the Debian root file system too. Tried on
2026-11-24 (macOS): the log-in, Thunder's answers, and the inspector's
page (its address answered; it was not used).

`./emu verify rootfs-option` checks this path with a stand-in, the Debian
VM image of the host's CPU architecture started the same way, and with the
image in `build/rdke/ARCH` where a host has built one.

## What is checked

    rdke/check-parse.sh

fetches RDK-E's common layers at the versions its vendor manifest names and
runs Yocto's parser (bitbake) on them with this machine, in a container,
once for each userland. Run on macOS (ARM64) on 2026-11-20: the configuration
and all 2658 recipes parse with 0 errors in both, the kernel is `linux-yocto`
5.15 for `qemuarm64` with this layer's four option files, and Mesa 22.0.3 has
the `virgl` and `swrast` drivers. Run on Linux (x86-64) on 2026-11-23 for
the x86-64 machine, which the script takes on an x86-64 host
(`TVEMU_RDKE_ARCH=arm64` or `x86_64` chooses otherwise): 2688 recipes parse
with 0 errors, with the 64-bit userland, the only one it has.

That shows that the definition is consistent with RDK-E's common layers.
That it builds and boots is shown by the minimal image above, with the
64-bit userland only.

    ./emu verify rootfs-option rdke-browser rdke-launcher rdke-video

`rootfs-option` boots whatever image is in `build/rdke/ARCH` to its own
init. `rdke-browser` needs `tvemu-browser-image` there: it shows the image's
page in RDK's browser, compares the picture that reaches the launcher's
window, and sends remote control keys through the window to the page.
`rdke-launcher` needs the same image: with the reference user interface
running, it starts an application with the call the user interface makes
for a card, and ends it with the EXIT key. On a host without the image, or
with another image, both end as unavailable. Westeros alone, the
middleware's device interfaces and the user interface's own screens are not
covered by a check.

`rdke-video` needs the same image too: RDK's browser plays the image's
reference stream, the launcher's window shows its picture, and its tone
reaches the host-side sound process and the host's output device (see
"Video and sound" for what was seen).

    ./emu verify rdke-health rdke-device rdke-aamp rdke-rate

Four more, since 2026-11-24, for what had only been looked at by hand. They
need an image built from the layer of that day or later, and end as
unavailable with an older one where they can tell.

- `rdke-health`: the image starts to its user interface with the system's
  state "running"; no unit failed, failed a start or was started again; no
  process ended on a signal; every plug-in that Thunder starts by itself is
  started (those that are not started by the image's configuration are
  listed in the result); and Thunder and the SSH server answer this host
  through forwarded ports. It reads the journal, and says so when that
  does not go back to the start.
- `rdke-device`: what RDK's services say of the virtual device, asked
  through Thunder from this host: the connected display, the current
  resolution against the display's mode, the supported resolutions, the
  display's description, the serial number, maker and model, the power
  state and the front panel's light. It reads; it sets nothing.
- `rdke-aamp`: RDK's player plays the reference stream as an HLS stream
  from the image itself, with the picture in the launcher's window and the
  tone at the host, as `rdke-video` has them for the browser's own player.
- `rdke-rate`: how many pictures a second reach the launcher's window, at
  the home screen and while the browser plays the reference stream (with
  the home screen hidden under it, as the user interface hides itself when
  it starts an application), counted over 10 s each. A host-native guest has to give 50; for a guest
  on a simulated CPU the check gives the numbers and ends as unavailable.
- `rdke-browser-other-graphics`, `rdke-launcher-other-graphics`,
  `rdke-video-other-graphics`, `rdke-aamp-other-graphics`,
  `rdke-health-other-graphics` and `rdke-device-other-graphics`
  (2026-11-26): each of those six checks a second time, with the graphics
  that an RDK-E image does not get unasked on the host. On a Mac with the
  experimental QEMU that is emulated graphics, so the target's own drawing
  stays checked there; on a host where the image is emulated unasked it is
  the host's GPU, and the check ends as unavailable where the launcher's
  window cannot show such a display. Each says which graphics it asked for
  and requires that the launcher gave it. All six pass on the Mac
  (2026-11-26, in the whole of `./emu verify`); none was run on Linux.

*How the power state gets to ON, and the fault in `rdke-device`*
(2026-11-26, macOS, from the journal of boots with emulated graphics).
The image starts at STANDBY: the middleware's PowerManager says "Setting
default powerstate to POWER_STATE_STANDBY" (`PLATCO_BOOTTO_STANDBY`) with
"Power State Before Reboot: ON". RDK's user interface sets ON when it
starts, about 3 s after the kernel: it compares the state before the
reboot with the state now and calls `setPowerState`. It makes two calls
within 3 ms. The first carries a state that PowerManager reads as UNKNOWN
and refuses ("Failed to set power state: 1"); the second carries ON and
finds "a state change request in progress for UNKNOWN state", which it
cancels. `rdke-device` found STANDBY for the whole 60 s it waits in three
whole runs of the checks on 2026-11-25. On 2026-11-26 the state was
STANDBY 60 s after the start in one boot by hand and ON in the 23 boots
after it, in the whole run of the checks (both graphics) and in a run of
the check alone. That the two calls race, so that now and then ON is
lost, is the likely cause and is **not shown**: the one boot that stayed
at STANDBY did not have its journal read, and none could be made to
since. Why it was three of three whole runs on one day and none on the
next is not known. Nothing in the layer was changed for it; the check's
failure message now carries the journal's lines about those calls. A
device without that user interface stays at STANDBY until something
sets ON.

Every RDK-E check now starts the image with Thunder's and the SSH server's
ports forwarded to free ports of this host. Not covered by a check:
Westeros alone, a video from the user interface's own cards (which are
streams from the internet), setting a resolution or a power state, and a
container.

## What is open

1. **The vendor layer, in part.** Its components are there and the
   middleware builds on them (see above); several are not adapted to the VM
   or not tried. When this list was first written, the machine named recipes
   that did not exist: the
   hardware abstraction for device settings, power, deep sleep, HDMI-CEC,
   manufacturer data and others (`...-hal-tvemu`), and Westeros' video
   sink (now there for decoded frames, see "Video and sound"). A build of the vendor layer
   stops at the first of them. The Pi's `vendor_pkg_versions.inc`, which pins
   the versions of what a vendor layer delivers, is not taken over either.
2. **The 32-bit userland, and other build hosts.** Everything here is
   built with 64-bit programs, in a container on the Mac (engine disk
   200 GB, memory 8 GB, with swap added for WebKit). The 32-bit userland,
   which is how RDK-E is built, is not built at all, and nothing is built
   on Linux or Windows.
3. **The kernel options, in full.** Binder, AppArmor and virtio-gpu were
   seen at work in the booted image; dm-verity, EROFS and sound were not
   looked at. `CONFIG_ASHMEM`, which the Pi sets, is left out.
4. **The application layer as RDK-E means it.** The browser and the user
   interface are in the image directly (see above). RDK-E's own way, the
   browser as an application package that the application managers run in
   a container, is not tried. Its container daemon (Dobby) starts in this
   image; no container was started with it. The user interface in the
   image is the last line of releases that starts applications with
   RDKShell (5.0.24), on a stand-in for it; the releases from 6.0 on use
   the application managers.
   Looked into on 2026-11-23, nothing changed: the application managers
   are all in this image and activated (`org.rdk.AppManager`,
   `LifecycleManager`, `RuntimeManager`, `AppPackageManager`,
   `AppStorageManager`, `DownloadManager`, `PreinstallManager`,
   `RDKWindowManager`, `OCIContainer`), with no application installed. So
   is RDK-E's start of the user interface: `sceneset.service` copies the
   "factory apps" from `/etc/rdk/factoryapps` to the preinstall directory,
   has them installed and starts `com.rdkcentral.refui` with the
   application manager. Here it finds no packages ("Failed to open factory
   apps location", "StartPreinstall failed"). What is missing is the
   packages and what the runtime manager needs to start one:
   - three packages ("bolt", RDK's format of an OCI layout with an EROFS
     layer under dm-verity, signed): a base layer (`com.rdkcentral.base`),
     the browser as a runtime (`com.rdkcentral.wpe`) and the user interface
     (`com.rdkcentral.refui`, releases 6.0 on), built with
     `meta-bolt-distro`, `meta-bolt-wpe` and `bolt-tools`. RDK publishes a
     set for the Raspberry Pi 4 (base 0.2.0, wpe 0.3.1, refui 6.0.9); none
     was downloaded, and no 64-bit set was found. The build names a
     manifest of them in `FACTORY_APPS_JSON_FILE`, which is not set here;
   - the certificate the packages are signed with, in `/etc/rdk/certs`;
   - a "GPU layer" of the platform (`/usr/share/gpu-layer`), which the
     Pi's vendor layer has as a recipe (`gpu-layer.bb`) and this layer has
     not;
   - the kernel's overlay file system, which is off in this kernel
     (`CONFIG_OVERLAY_FS`); EROFS and dm-verity are on, loop devices are a
     module.
   Not tried: installing or starting any package.
5. **The launcher's side, in part.** `./emu run --mode vm --rootfs rdke`
   boots an image from `build/rdke/arm64`, and the remote control's keys
   reach it (`rdke-browser` checks that), and the target's sound is played
   through the host (`rdke-video`). Ports of the target are forwarded where
   a run asks (`--option forward`). Captures (`--screenshot`), recording and
   RedRat input are refused, and the launcher does not build the image.
6. **RDK's own virtual device.** RDK's build scripts mention a "vdevice"
   product layer (build-scripts, pull request 30, June 2026). No public
   repository of it was found on 2026-11-20. If one is published, it may be
   a better base than this fusion.

## Sources

Read on 2026-11-20, all Apache-2.0 or MIT: `vendor-manifest-raspberrypi`
(develop), `meta-product-raspberrypi`, `meta-vendor-raspberrypi-dev`
(adba061), `rdke-generic-manifest` 1.1.1, `build-scripts` 1.0.5,
`meta-stack-layering-support` 5.0.4, all on github.com/rdkcentral;
`meta-raspberrypi` (kirkstone); and `qemuarm64.conf` and `qemu.inc` of
RDK's fork of poky (`rdk-4.7.0`). Lines taken from RDK's files keep their
meaning and are marked with where they are from.
