"""The emulator's display, and how its graphics functionality is provided.

The display has one of the supported resolutions. Graphics are provided in
one of two ways:

  emulated  the target's CPU renders (Mesa's software OpenGL ES and Vulkan);
            the emulator only shows the result
  host      graphics are mapped to the host's graphics acceleration

"auto" prefers host acceleration when the host has a compatible one and
falls back to emulation; the reason for the choice is recorded with the run.
What the target actually rendered with is reported by the workload, so a
result never depends on this module's expectation alone.
"""
import glob
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time

from . import host, imagefile
from .errors import EmuError

RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
DEFAULT_RESOLUTION = "1080p"
CHOICES = ("auto", "host", "emulated")
# How long a workload keeps its last frame on the display for a capture.
SCREEN_HOLD_SECONDS = 4
# The launcher's own window (emulator/gui/viewer.py): it has the toolbar, the
# switch to full screen and remote control input, and shows the display in
# both modes.
LAUNCHER_WINDOW = "launcher"
# QEMU's displays that open a window, in order of preference. SDL's window
# takes the size of the target's display; GTK's gives the display its own.
# One of these shows a VM's display where the launcher's window cannot (see
# window_kind).
WINDOWS = ("sdl", "cocoa", "gtk")
# The ones that can show a display that is rendered on the host GPU, with the
# option that turns that on. QEMU's Cocoa window cannot, except in builds that
# carry the macOS OpenGL patches (see opengl_window); those render through
# ANGLE, which offers OpenGL ES.
OPENGL_WINDOWS = {"sdl": "gl=on", "gtk": "gl=on", "cocoa": "gl=es"}
# Marker blocks every graphics workload draws (target/src/emugfx.c): the four
# corners, in the order top left, top right, bottom left, bottom right.
CORNER_COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
COLOR_TOLERANCE = 12
VIDEO_COLOR_TOLERANCE = 60

# Kernel GPU drivers that Mesa, the target's graphics stack, has no driver for.
PROPRIETARY_DRIVERS = ("nvidia",)

_probes = {}


def resolution(name):
    try:
        return RESOLUTIONS[(name or DEFAULT_RESOLUTION).lower()]
    except KeyError:
        raise EmuError("unknown resolution %r (supported: %s)" % (name, ", ".join(RESOLUTIONS)))


def _qemu_output(binary, *args):
    try:
        done = subprocess.run([binary] + list(args), env=host.tool_env(), capture_output=True, text=True, timeout=60)
        return done.stdout + done.stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def window_backend(binary):
    """The QEMU display that shows the emulator's display in a window."""
    displays = _qemu_output(binary, "-display", "help").split()
    for name in WINDOWS:
        if name in displays:
            return name
    raise EmuError("this QEMU build has no display that opens a window (%s)" % ", ".join(WINDOWS))


def window_kind(binary, requested):
    """Which window shows a VM's display: the launcher's own, or QEMU's
    (named by its display backend).

    The launcher's window gets the display from QEMU's VNC server. That shows
    a display rendered on the host GPU only where QEMU has a working display
    backend that renders without a window (probe_vm). Where it has not, and
    host acceleration is asked for or preferred, the display is shown in
    QEMU's own window: that one can show it, but has no toolbar and takes no
    remote control keys."""
    if (requested or "auto") == "emulated" or probe_vm(binary, launcher_window=True)["available"]:
        return LAUNCHER_WINDOW
    try:
        own = window_backend(binary)
    except EmuError:
        return LAUNCHER_WINDOW
    return own if probe_vm(binary, own)["available"] else LAUNCHER_WINDOW


def opengl_window(binary, window):
    """Whether this QEMU's window of that kind shows a display rendered on
    the host GPU. SDL and GTK windows do. The Cocoa window does only in a
    build that was made with OpenGL at all, which on macOS means one that
    carries the macOS OpenGL patches; such a build also has the display
    without a window. An unpatched build refuses the option when it starts."""
    if window != "cocoa":
        return window in OPENGL_WINDOWS
    return "egl-headless" in _qemu_output(binary, "-display", "help").split()


def dbus_read_back(binary):
    """Whether this QEMU, on macOS, hands a display that the host's GPU drew
    to a listener of its D-Bus display: it reads each picture back from the
    GPU and sends its pixels. That is this project's change to the
    experimental QEMU (docs/macos-experimental-qemu.patch, docs/
    frame-transfer.md); a build without it ends with a segmentation fault
    when it is started with that display and OpenGL. The change brings a
    trace point with it, which names it."""
    return host.host_os() == "macos" and "dbus_gl_read_back" in _qemu_output(binary, "-trace", "help")


def host_graphics_qemu(name):
    """The directory of another QEMU build that a run asking for the host's
    GPU (--graphics host) takes `name` from, or None for the installed one.

    That is the experimental QEMU (host.experimental_qemu_dir), where
    setup.sh --experimental-qemu installed it. On macOS it is taken where
    the installed QEMU has no display device for the host's GPU. On Linux it
    is taken although the installed one has such a device: a QEMU before 11
    holds a target that draws with the host's GPU to 30 pictures a second,
    and the build maps Vulkan too (docs/frame-transfer.md). A build that
    lacks the emulator for a guest leaves that guest to the installed QEMU.
    Nothing is chosen where EMU_QEMU_DIR names a build: that is the user's
    choice. A run that does not ask for the host's GPU keeps the installed
    QEMU, which is what the host is evaluated with."""
    system = host.host_os()
    if system not in ("macos", "linux") or host.qemu_dir_given():
        return None
    if system == "macos":
        usual = shutil.which(name, path=host.tool_path())
        if usual and "virtio-gpu-gl-pci" in _qemu_output(usual, "-device", "help"):
            return None
    directory = host.experimental_qemu_dir()
    other = directory and (shutil.which(name, path=directory) or
                           (system == "macos" and name == "qemu-system-arm"
                            and shutil.which("qemu-system-aarch64", path=directory)))
    if other and "virtio-gpu-gl-pci" in _qemu_output(other, "-device", "help"):
        return directory
    return None


def host_graphics_binary(name):
    """The QEMU program `name` that a run asking for the host's GPU uses."""
    directory = host_graphics_qemu(name)
    if directory:
        return shutil.which(name, path=directory) or shutil.which("qemu-system-aarch64", path=directory)
    return host.find_tool(name)


def _render_node():
    """A DRM render node this user can open: the sign, on Linux, that a GPU
    driver is loaded. Without one the host's own OpenGL is rendered by its
    CPU, and QEMU's display without a window has no device to render on."""
    for path in sorted(glob.glob("/dev/dri/renderD*")):
        if os.access(path, os.R_OK | os.W_OK):
            return path
    return None


def _renderer_maps_vulkan(binary):
    """Whether the virglrenderer this QEMU uses was built to map Vulkan
    (venus). QEMU's device has the option whenever QEMU knows it, and with a
    renderer built without it QEMU ends when the target first uses the GPU
    ("failed to initialize venus renderer"; seen with QEMU 11.0.0 and a
    virglrenderer 1.3.0 built with its defaults). A renderer with it names
    the server program it starts for Vulkan. True where the library is not
    found: then the option decides as before."""
    programs = [binary]
    # Where QEMU's devices are modules, the display device's is what uses the renderer.
    root = os.path.dirname(os.path.dirname(os.path.realpath(binary)))
    programs += glob.glob(os.path.join(root, "lib", "**", "hw-display-virtio-gpu-gl.so"), recursive=True)
    for program in programs:
        try:
            listed = subprocess.run(["ldd", program], capture_output=True, text=True, timeout=30,
                                    env=host.tool_env()).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in listed.splitlines():
            name, _, rest = line.strip().partition(" => ")
            path = rest.split(" (")[0].strip()
            if name.startswith("libvirglrenderer") and os.path.isfile(path):
                try:
                    with open(path, "rb") as library:
                        return b"virgl_render_server" in library.read()
                except OSError:
                    return True
    return True


def probe_vm(binary, window=None, launcher_window=False, guest=None):
    """Whether this QEMU can map the guest's graphics to the host's GPU.
    `guest` is the target's CPU architecture where the caller knows it.

    `launcher_window` says that the launcher's own window shows the display:
    on macOS a QEMU with the read-back (dbus_read_back) can feed that window
    and nothing else that has no window of QEMU's.

    That needs the virtio-gpu device with a host renderer (virglrenderer) and
    a display that gives it a GPU context: the window (`window` names QEMU's
    display for it) when the emulator's display is shown in one, and otherwise
    a display backend that renders without a window.
    """
    key = (binary, window, bool(launcher_window), guest)
    if key in _probes:
        return _probes[key]
    devices = _qemu_output(binary, "-device", "help")
    displays = _qemu_output(binary, "-display", "help")
    # Vulkan is mapped as well where vm_arguments turns that on.
    # Not for a 32-bit ARM target: its kernel does not give the Vulkan driver
    # what it needs from the device ("one of required kernel params (4 or 9)
    # is missing", Debian 13's armmp-lpae kernel 6.12), so the device would
    # only be set up differently for nothing.
    venus = host.host_os() == "linux" and guest != "arm32" \
        and "venus" in _qemu_output(binary, "-device", "virtio-gpu-gl-pci,help") and _renderer_maps_vulkan(binary)
    mapped = "QEMU maps the target's OpenGL ES%s to the host GPU (virtio-gpu with virglrenderer)" \
             % (" and Vulkan" if venus else "")
    if "virtio-gpu-gl-pci" not in devices:
        probe = {"available": False,
                 "reason": "this QEMU build has no GPU-accelerated display device (virtio-gpu-gl); "
                           "it was built without virglrenderer"}
    elif host.host_os() == "linux" and not _render_node():
        found = glob.glob("/dev/dri/renderD*")
        probe = {"available": False,
                 "reason": ("this user cannot open the host's GPU render node (%s)" % found[0]) if found else
                           "the host has no GPU render node (/dev/dri/renderD*): no GPU driver is loaded, and "
                           "the host renders its own graphics on the CPU"}
    elif window and opengl_window(binary, window):
        probe = {"available": True, "venus": venus, "reason": mapped + " and shows it in an OpenGL window"}
    elif window:
        probe = {"available": False,
                 "reason": "QEMU's %s window does not show a display that is rendered on the host GPU" % window}
    elif "egl-headless" not in displays:
        probe = {"available": False,
                 "reason": "this QEMU build has no display backend that renders on the host GPU without a window "
                           "(egl-headless)"}
    elif host.host_os() == "windows":
        # Seen with QEMU 11.1.0: OpenGL ES and Flutter render on the host GPU
        # (virglrenderer on ANGLE), and every frame read from the display is
        # black.
        probe = {"available": False,
                 "reason": "on Windows, QEMU's display that renders on the host GPU without a window "
                           "(egl-headless) stays black: the target renders on the host GPU, but no frame "
                           "reaches the emulator's display. In a window (--window) it does"}
    elif host.host_os() == "macos" and dbus_read_back(binary):
        # With or without the launcher's window: QEMU's D-Bus display has no window of its own,
        # and reads a picture back for whoever listens (the window, or a capture).
        probe = {"available": True, "venus": False,
                 "reason": mapped + (" and hands each picture to the launcher's window (QEMU's D-Bus display, "
                                     "read back from the GPU)" if launcher_window else
                                     ", without a window (QEMU's D-Bus display; a picture is read back from the "
                                     "GPU when one is captured)")}
    elif host.host_os() == "macos":
        # Seen with a QEMU 11.1.90 build that carries the macOS OpenGL patches:
        # QEMU ends with a segmentation fault as soon as the target's driver
        # starts the host renderer (the OpenGL context is made current on a
        # thread it was not made for). In the Cocoa window the same build works.
        probe = {"available": False,
                 "reason": "on macOS, QEMU's display that renders on the host GPU without a window (egl-headless) "
                           "crashes when the target starts to use the GPU. In a window (--window) it works"}
    else:
        probe = {"available": True, "venus": venus, "reason": mapped}
    _probes[key] = probe
    return probe


def probe_container(runtime, tag, platform):
    """Whether the container engine has a GPU render node to give the target."""
    key = (runtime.cli, tag)
    if key in _probes:
        return _probes[key]
    try:
        # The node, and the kernel driver behind it.
        script = ("node=$(ls /dev/dri/renderD* 2>/dev/null | head -n 1); [ -n \"$node\" ] || exit 0; "
                  "echo $node $(basename \"$(readlink /sys/class/drm/${node##*/}/device/driver)\")")
        done = runtime.run("run", "--rm", "--platform", platform, "--device", "/dev/dri", "--entrypoint", "/bin/sh",
                           tag, "-c", script, timeout=120)
        node, _, driver = (done.stdout.strip() if done.returncode == 0 else "").partition(" ")
    except subprocess.TimeoutExpired:
        node, driver = "", ""
    if node and driver in PROPRIETARY_DRIVERS:
        probe = {"available": False,
                 "reason": "the container engine's GPU render node (%s) belongs to the %s kernel driver, which the "
                           "target's graphics stack (Mesa) cannot render with; it works only with that vendor's own "
                           "libraries" % (node, driver)}
    elif node:
        probe = {"available": True, "reason": "the container engine has a GPU render node (%s)" % node}
    else:
        where = "; the engine runs in a virtual machine that offers none" if host.host_os() != "linux" else ""
        probe = {"available": False, "reason": "the container engine has no GPU render node (/dev/dri)" + where}
    _probes[key] = probe
    return probe


def choose(requested, probe):
    """Decide the graphics provider. `probe` is a callable so that asking for
    emulation never touches the host's graphics."""
    requested = requested or "auto"
    if requested not in CHOICES:
        raise EmuError("unknown --graphics %r (one of: %s)" % (requested, ", ".join(CHOICES)))
    if requested == "emulated":
        return {"requested": requested, "provider": "emulated", "reason": "emulation was requested"}
    found = probe()
    if found["available"]:
        return {"requested": requested, "provider": "host", "reason": found["reason"],
                "venus": bool(found.get("venus"))}
    if requested == "host":
        raise EmuError("host graphics acceleration is not available: %s" % found["reason"],
                       hint="use --graphics auto to fall back to emulated graphics")
    return {"requested": requested, "provider": "emulated",
            "reason": "no compatible host graphics acceleration: %s" % found["reason"]}


def vm_arguments(plan, width, height, memory_mb, options, sixty=False):
    """QEMU arguments for the display device; returns (arguments, display
    backend, device description). The display is shown in a window when the
    plan names one, and nowhere otherwise.

    `sixty` asks for a display of 60 pictures a second. QEMU's device
    describes its monitor to the target (EDID) with 75 as the refresh rate of
    the size asked for, and has no setting for another; without the
    description the target's kernel makes the mode itself, at 60."""
    size = "xres=%d,yres=%d" % (width, height)
    if sixty:
        size += ",edid=off"
    # The launcher's own window is not a display backend of QEMU's.
    window = plan.get("window") if plan.get("window") != LAUNCHER_WINDOW else None
    if plan["provider"] != "host":
        # An emulated display adapter without 3D. Its frame-buffer allowance
        # has to grow with the resolution.
        allowance = max(256, (width * height * 4 * 16) >> 20)
        return (["-device", "virtio-gpu-pci,%s,max_hostmem=%dM" % (size, allowance)], window or "none",
                "virtio-gpu (2D), rendering by the target CPU")
    device = "virtio-gpu-gl-pci," + size
    arguments = []
    description = "virtio-gpu with virglrenderer (OpenGL ES on the host GPU)"
    venus = str(options.get("venus", "auto")).lower()
    if venus in ("yes", "on", "true", "1") or (venus == "auto" and plan.get("venus") and host.host_os() == "linux"):
        # Vulkan pass-through shares guest memory with the host renderer.
        device += ",venus=on,blob=on,hostmem=4G"
        if host.host_os() == "linux":       # memfd is Linux's; macOS has no such backend
            arguments += ["-object", "memory-backend-memfd,id=emu-ram,size=%dM" % memory_mb,
                          "-machine", "memory-backend=emu-ram"]
        description = "virtio-gpu with virglrenderer (OpenGL ES and Vulkan on the host GPU)"
    backend = "%s,%s" % (window, OPENGL_WINDOWS[window]) if window else "egl-headless"
    return arguments + ["-device", device], backend, description


def vulkan_environment(binary):
    """What QEMU's environment needs on macOS for the renderer to map Vulkan:
    virglrenderer's server program opens MoltenVK by its bare name, which
    macOS finds only in the directories it is told of. Homebrew has the
    library beside the QEMU it built (opt/molten-vk). {} where it is not
    found, and on other hosts. (macOS takes such variables out of the
    environment of its own programs, the system's Python among them, so
    giving it to the launcher does not reach QEMU.)"""
    if host.host_os() != "macos":
        return {}
    prefix = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(binary)))))
    directory = os.path.join(prefix, "opt", "molten-vk", "lib")
    if not os.path.isfile(os.path.join(directory, "libMoltenVK.dylib")):
        return {}
    return {"DYLD_FALLBACK_LIBRARY_PATH": ":".join([directory, "/usr/local/lib", "/usr/lib"])}


def container_arguments(plan):
    """Container runtime arguments for the chosen provider."""
    return ["--device", "/dev/dri"] if plan["provider"] == "host" else []


# ---------------------------------------------------------- captures ---

def _connect(address):
    """Connect to a socket QEMU listens on (a TCP address or a socket path),
    waiting for QEMU to open it."""
    deadline = time.time() + 30
    while True:
        try:
            if isinstance(address, tuple):
                return socket.create_connection(address, timeout=30)
            found = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            found.settimeout(30)
            found.connect(address)
            return found
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.1)


class Qmp:
    """Minimal client for QEMU's machine protocol, used to capture the display."""

    def __init__(self, address):
        self.address = address
        self._socket = None
        self._buffer = b""

    def capture(self, path, image_format):
        self.command("screendump", filename=os.path.abspath(path), format=image_format)

    def _connect(self):
        self._socket = _connect(self.address)
        self._read()            # greeting
        self.command("qmp_capabilities")

    def _read(self):
        while b"\n" not in self._buffer:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise OSError("QEMU closed the machine protocol connection")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return json.loads(line)

    def command(self, name, **arguments):
        if self._socket is None:
            self._connect()
        self._socket.sendall(json.dumps({"execute": name, "arguments": arguments}).encode() + b"\n")
        while True:
            reply = self._read()
            if "return" in reply:
                return reply["return"]
            if "error" in reply:
                raise OSError("QEMU refused %s: %s" % (name, reply["error"].get("desc")))

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None


class Vnc:
    """Minimal client for QEMU's VNC server, used to capture the display
    where QEMU will not write the image itself."""

    def __init__(self, address):
        self.address = address

    def close(self):
        pass

    def capture(self, path, image_format):
        # A connection per capture: the server states the display's size when
        # one opens, and the target changes that size when it sets a mode.
        connection = _connect(self.address)
        try:
            width, height, pixels = self._frame(connection)
        finally:
            connection.close()
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = pixels[2::4], pixels[1::4], pixels[0::4]
        imagefile.save(path, width, height, rgb, image_format)

    @staticmethod
    def _frame(connection):
        def receive(count):
            data = bytearray()
            while len(data) < count:
                chunk = connection.recv(min(count - len(data), 1 << 20))
                if not chunk:
                    raise OSError("QEMU closed the VNC connection")
                data += chunk
            return data

        receive(12)                                         # the server's protocol version
        connection.sendall(b"RFB 003.008\n")
        if 1 not in receive(receive(1)[0]):                 # 1: no authentication
            raise OSError("QEMU's VNC server does not accept a connection without authentication")
        connection.sendall(b"\x01")
        if receive(4) != b"\0\0\0\0":
            raise OSError("QEMU's VNC server refused the connection")
        connection.sendall(b"\x01")                         # share the display with other clients
        width, height = struct.unpack(">HH", receive(20)[:4])
        receive(struct.unpack(">I", receive(4))[0])         # the display's name
        # Pixels as four bytes: blue, green, red, unused. Raw encoding only.
        connection.sendall(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        connection.sendall(struct.pack(">BxHi", 2, 1, 0))
        connection.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, width, height))
        pixels = bytearray(width * height * 4)
        covered = 0
        while covered < width * height:
            kind = receive(1)[0]
            if kind == 2:                                   # bell
                continue
            if kind == 3:                                   # text from the server's clipboard
                receive(struct.unpack(">xxxI", receive(7))[0])
                continue
            if kind != 0:
                raise OSError("unexpected VNC message %d from QEMU" % kind)
            for _ in range(struct.unpack(">xH", receive(3))[0]):
                x, y, w, h, encoding = struct.unpack(">HHHHi", receive(12))
                if encoding != 0:
                    raise OSError("QEMU's VNC server sent encoding %d, not raw pixels" % encoding)
                data = receive(w * h * 4)
                for row in range(h):
                    start = ((y + row) * width + x) * 4
                    pixels[start:start + w * 4] = data[row * w * 4:(row + 1) * w * 4]
                covered += w * h
        return width, height, pixels


class NoCapture:
    """Stands in where the display cannot be captured, and says why."""

    def __init__(self, reason):
        self.reason = reason

    def capture(self, path, image_format):
        raise EmuError(self.reason)

    def close(self):
        pass


def _private_socket(name):
    """A path for a socket of this run, in a directory to remove afterwards;
    (None, None) on a host without such sockets. The path is short: socket
    paths have a tight length limit."""
    if host.host_os() == "windows" or not hasattr(socket, "AF_UNIX"):
        return None, None
    directory = tempfile.mkdtemp(prefix="emu-", dir="/tmp")
    return os.path.join(directory, name), directory


def _vnc_port():
    """A free TCP port for a VNC display: QEMU counts those from port 5900."""
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port >= 5900:
            return port


def vnc_endpoint():
    """Where QEMU serves a VM's display for the launcher's window. Returns
    (QEMU arguments, address for emulator/rfb.py, directory to remove
    afterwards).

    On macOS the window gets the display another way where it can
    (window_endpoint). Where it cannot, this is a port of the loopback
    address, as on Windows, and not a private socket: a socket of that kind takes 8 KB at a time there, QEMU
    writes one such piece each time its event loop comes round, and a display
    of 1920x1080 (8 MB a picture) then reached the window 6 to 7 times a
    second where the port gives 18 to 19. The port has no password: programs
    of other users of the host can see the display and send keys for the time
    of the run."""
    path, directory = (None, None) if host.host_os() == "macos" else _private_socket("vnc.sock")
    if path:
        return ["-vnc", "unix:" + path], path, directory
    port = _vnc_port()
    return ["-vnc", "127.0.0.1:%d" % (port - 5900)], ("127.0.0.1", port), None


DBUS_DISPLAY = "dbus,p2p=yes"
DBUS_PREFIX = "dbus:"
# The same display with OpenGL: a picture that the host's GPU rendered is
# handed over as the GPU's buffer.
DBUS_GL_DISPLAY = "dbus,p2p=yes,gl=on"
DBUS_GL_PREFIX = "dbus-gl:"
# macOS, with a QEMU that reads a picture of the host's GPU back (dbus_read_back): the display with
# pixels all the same. ANGLE, which is that QEMU's OpenGL, is OpenGL ES.
DBUS_READ_BACK_DISPLAY = "dbus,p2p=yes,gl=es"
# How the launcher's window gets a display that the host's GPU renders.
WINDOW_DISPLAYS = ("auto", "buffer", "vnc")


def probe_buffer_window(binary):
    """Whether the launcher's window can take a VM's display as buffers of the
    host's GPU: {"available": ..., "reason": ...}. That needs QEMU's D-Bus
    display, Linux (the buffers are its dma-bufs), and a Qt whose OpenGL
    context takes them, which the window's own Python is asked."""
    key = (binary, "buffer-window")
    if key in _probes:
        return _probes[key]
    if host.host_os() != "linux":
        probe = {"available": False, "reason": "QEMU hands over GPU buffers on Linux only"}
    elif "dbus" not in _qemu_output(binary, "-display", "help").split():
        probe = {"available": False, "reason": "this QEMU build has no D-Bus display"}
    else:
        from . import window
        probe = window.probe_buffers()
    _probes[key] = probe
    return probe


def window_endpoint(binary, plan, wanted="auto"):
    """Where the launcher's window gets a VM's display from. Returns (QEMU
    arguments, QEMU's display backend or None for the one already chosen,
    address for the window, directory to remove afterwards, a note for the
    user or None).

    On macOS and Linux, for a display that the target's CPU renders, it is QEMU's D-Bus
    display over a private socket (emulator/dbusdisplay.py, which says why);
    the address then starts with "dbus:". For one that the host's GPU renders
    it is the same display with the GPU's buffers, on Linux and where the
    window can take them (probe_buffer_window); the address then starts with
    "dbus-gl:". `wanted` is the run's choice for that case: "buffer" refuses
    where they cannot be taken, "vnc" does not use them. On macOS it is the
    display with pixels for one that the host's GPU renders as well, where
    QEMU reads the picture back (dbus_read_back); nothing else shows such a
    display in the launcher's window there, so "vnc" is not followed.
    Everywhere else, and where this QEMU has no such display, it is QEMU's
    VNC server (vnc_endpoint).
    """
    if wanted not in WINDOW_DISPLAYS:
        raise EmuError("unknown --option window-display=%s (one of: %s)" % (wanted, ", ".join(WINDOW_DISPLAYS)))
    note = None
    read_back = plan["provider"] == "host" and wanted != "buffer" and dbus_read_back(binary)
    if plan["provider"] == "host" and wanted != "vnc" and not read_back:
        found = probe_buffer_window(binary)
        path, directory = _private_socket("display.sock") if found["available"] else (None, None)
        if path:
            return (["-qmp", "unix:%s,server=on,wait=off" % path], DBUS_GL_DISPLAY, DBUS_GL_PREFIX + path, directory,
                    None)
        if wanted == "buffer":
            raise EmuError("the launcher's window cannot take the display as buffers of the host's GPU: %s"
                           % found["reason"], hint="leave out --option window-display=buffer")
        note = "the window gets the display from QEMU's VNC server, which is slower: %s" % found["reason"]
    elif host.host_os() in ("macos", "linux") and (plan["provider"] != "host" or read_back) \
            and "dbus" in _qemu_output(binary, "-display", "help").split():
        path, directory = _private_socket("display.sock")
        if path:
            backend = DBUS_READ_BACK_DISPLAY if read_back else DBUS_DISPLAY
            return ["-qmp", "unix:%s,server=on,wait=off" % path], backend, DBUS_PREFIX + path, directory, None
    arguments, address, directory = vnc_endpoint()
    return arguments, None, address, directory, note


class WindowCapture:
    """Captures a display that the launcher's window gets as buffers of the
    host's GPU: only the window has the picture then, so it is asked.
    `viewer` is set when the window is started."""

    def __init__(self):
        self.viewer = None

    def capture(self, path, image_format):
        if self.viewer is None:
            raise EmuError("the display window was not started")
        answer = self.viewer.ask(do="save-display", path=os.path.abspath(path), format=image_format)
        if not answer.get("saved"):
            raise EmuError("the display window could not capture the display: %s"
                           % (answer.get("reason") or answer.get("error") or "no reason given"))

    def close(self):
        pass


class ReadBackCapture:
    """Captures a display that the host's GPU draws where QEMU reads the
    picture back for a listener of its D-Bus display (dbus_read_back, on
    macOS) and no window shows it: this is the listener. It keeps the newest
    picture and writes it when asked."""

    def __init__(self, qmp_path):
        from . import dbusdisplay
        self._lock = threading.Lock()
        self._size = None
        self._frame = None
        self.client = dbusdisplay.Client(qmp_path, self._on_size, self._on_update)
        self.client.start()

    def _on_size(self, width, height):
        pass

    def _on_update(self, x, y, width, height, frame):
        # The client does not write into a buffer it has handed over.
        with self._lock:
            self._size, self._frame = (width, height), frame
        self.client.shown()

    def capture(self, path, image_format):
        deadline = time.time() + 10
        while self._frame is None and time.time() < deadline:
            time.sleep(0.05)
        with self._lock:
            size, pixels = self._size, self._frame
        if pixels is None:
            raise EmuError("no picture of the display arrived from QEMU's D-Bus display")
        width, height = size
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = pixels[2::4], pixels[1::4], pixels[0::4]
        imagefile.save(path, width, height, rgb, image_format)

    def close(self):
        self.client.close()


def read_back_capture():
    """(QEMU arguments, capture client, directory to remove) for ReadBackCapture."""
    path, directory = _private_socket("display.sock")
    if not path:
        raise EmuError("no private socket for QEMU's D-Bus display could be made")
    return ["-qmp", "unix:%s,server=on,wait=off" % path], ReadBackCapture(path), directory


def capture_endpoint(plan, vnc=None):
    """How the display of a VM is captured during one run. Returns (QEMU
    arguments, a client with capture(path, format) and close(), directory to
    remove afterwards). `vnc` is the address of a VNC server this QEMU already
    has (vnc_endpoint), for a capture that has to come from one.

    QEMU writes the image itself when asked over its machine protocol. It
    refuses while the display is a texture on the host GPU; the image then
    comes from QEMU's VNC server, which the headless display feeds each frame.
    A window that shows such a display feeds nobody, so there is no capture.
    """
    if plan["provider"] == "host" and plan.get("window") not in (None, LAUNCHER_WINDOW):
        return [], NoCapture("QEMU has no way to capture a display that is rendered on the host GPU and shown "
                             "in a window"), None
    if plan["provider"] == "host":
        if vnc:
            return [], Vnc(vnc), None
        arguments, address, directory = vnc_endpoint()
        return arguments, Vnc(address), directory
    path, directory = _private_socket("qmp.sock")
    if path:
        return ["-qmp", "unix:%s,server=on,wait=off" % path], Qmp(path), directory
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return ["-qmp", "tcp:127.0.0.1:%d,server=on,wait=off" % port], Qmp(("127.0.0.1", port)), None


class Screens:
    """Captures the emulator's display each time a workload announces that a
    finished frame is on it (an EMU-SCREEN line)."""

    def __init__(self, directory, run_id, image_format, capture):
        self.directory = directory
        self.run_id = run_id
        self.image_format = image_format
        self._capture = capture        # callable(path) that writes the image
        self.captures = []

    def on_marker(self, marker):
        entry = dict(marker)
        name = "".join(c if c.isalnum() or c in "-_." else "-" for c in
                       str(marker.get("case") or marker.get("test") or "screen"))
        path = os.path.join(str(self.directory), "%s_%s.%s" % (self.run_id, name, self.image_format))
        try:
            os.makedirs(str(self.directory), exist_ok=True)
            self._capture(path)
            entry["file"] = path
            entry["captured_width"], entry["captured_height"] = imagefile.size(path)
        except (OSError, EmuError, ValueError, subprocess.SubprocessError) as error:
            entry["error"] = "%s" % error
        self.captures.append(entry)


def container_capture(runtime, name):
    def capture(path):
        with open(path, "wb") as handle:
            done = subprocess.run([runtime.cli, "exec", name, "/opt/emu/display", "screenshot"], env=host.tool_env(),
                                  stdout=handle, stderr=subprocess.PIPE, timeout=120)
        if done.returncode != 0:
            raise EmuError("the target could not capture its display: %s"
                           % done.stderr.decode(errors="replace").strip()[-300:])
    return capture


def _close(found, expected, tolerance=COLOR_TOLERANCE):
    return all(abs(a - b) <= tolerance for a, b in zip(found, expected))


def capture_is_cut(entry, width, height):
    """Whether a capture is the top left part of a larger display. QEMU's VNC
    server, which the capture of a display rendered on the host GPU is read
    from, shows no more than a fixed size (2560x2048 in QEMU 8.2)."""
    found = (entry.get("captured_width"), entry.get("captured_height"))
    return None not in found and found != (width, height) and found[0] <= width and found[1] <= height


def capture_problems(entry, width, height, allow_cut=False, tolerance=COLOR_TOLERANCE):
    """Compare a captured display image with what the workload said it drew:
    the display size, the corner blocks and the technology's marker block.
    Returns a list of problems, empty when the capture shows that frame. With
    `allow_cut`, a capture that is cut off is compared as far as it reaches.
    Decoded video needs a wider `tolerance` than drawn graphics: its colours
    went through a lossy codec and a colour space conversion."""
    if entry.get("error"):
        return ["the display could not be captured: %s" % entry["error"]]
    cut = allow_cut and capture_is_cut(entry, width, height)
    if (entry["captured_width"], entry["captured_height"]) != (width, height) and not cut:
        return ["the display capture is %dx%d, not %dx%d" % (entry["captured_width"], entry["captured_height"],
                                                             width, height)]
    image = imagefile.load(entry["file"])
    block = height // 12
    half = block // 2
    points = [("top-left corner", half, half, CORNER_COLORS[0]),
              ("top-right corner", width - block + half, half, CORNER_COLORS[1]),
              ("bottom-left corner", half, height - block + half, CORNER_COLORS[2]),
              ("bottom-right corner", width - block + half, height - block + half, CORNER_COLORS[3]),
              ("technology marker", width // 2, half, tuple(entry.get("marker") or ()))]
    problems = []
    for name, x, y, expected in points:
        if x >= entry["captured_width"] or y >= entry["captured_height"]:
            continue        # beyond what a cut capture shows
        found = image.pixel(x, y)
        if len(expected) != 3 or not _close(found, expected, tolerance):
            problems.append("%s is %s, expected %s" % (name, found, expected))
    return problems


def remove_directory(path):
    if path:
        shutil.rmtree(path, ignore_errors=True)
