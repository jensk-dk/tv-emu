"""The root file systems the launcher can start a target from.

"debian" is the evaluation's own image, which the launcher builds from
target/ and which has the workloads, the driver features and the STB
simulator. "rdke" is an RDK-E image built with Yocto for the machine
tvemu-arm64-rdke or tvemu-x86-64-rdke (rdke/README.md): the launcher does not
build it, it boots the files it finds, and the target then runs its own
software."""
import pathlib

from . import host
from .errors import EmuError
from .paths import BUILD_DIR, ROOT

DEBIAN = "debian"
RDKE = "rdke"
CHOICES = (DEBIAN, RDKE)
DEFAULT = DEBIAN

# The guest CPU architectures an RDK-E machine is defined for, and the
# machine of each.
RDKE_MACHINES = {"arm64": "tvemu-arm64-rdke", "x86_64": "tvemu-x86-64-rdke"}
RDKE_ARCHS = tuple(RDKE_MACHINES)
# Where its files are looked for, and the option that names another place.
RDKE_DIR_OPTION = "rdke-dir"
RDKE_README = "rdke/README.md"
# The names a file may have: Yocto's own first, then the Debian image's.
RDKE_KERNEL = ("Image", "bzImage", "vmlinuz")
RDKE_ROOT = ("rootfs.ext4", "rootfs.img")
RDKE_INITRD = ("initrd.img",)       # optional: Yocto's kernel for the machine needs none


def rdke_arch():
    """The guest CPU architecture an RDK-E image is started with on this host
    when nothing names one: the host's own, which runs host-native, unless
    only the image of another one is built here."""
    native = host.host_arch()
    there = [arch for arch in RDKE_ARCHS if _present(BUILD_DIR / RDKE / arch)]
    if native in RDKE_ARCHS and (native in there or not there):
        return native
    return there[0] if there else RDKE_ARCHS[0]


def rdke_dir(options=None, arch=None):
    named = (options or {}).get(RDKE_DIR_OPTION)
    return pathlib.Path(named).expanduser() if named else BUILD_DIR / RDKE / (arch or rdke_arch())


def _first(directory, names):
    for name in names:
        if (directory / name).is_file():
            return directory / name
    return None


def _present(directory):
    return bool(_first(directory, RDKE_KERNEL) and _first(directory, RDKE_ROOT))


def rdke_files(options=None, arch=None):
    """The kernel, the root file system and the initial RAM disk (or None) of
    the RDK-E image for the guest CPU architecture `arch` (rdke_arch() when
    None); raises EmuError when the image is not there."""
    directory = rdke_dir(options, arch)
    kernel, root = _first(directory, RDKE_KERNEL), _first(directory, RDKE_ROOT)
    if not kernel or not root:
        missing = ["%s (%s)" % (what, " or ".join(names)) for what, found, names in (
            ("kernel", kernel, RDKE_KERNEL), ("root file system", root, RDKE_ROOT)) if not found]
        raise EmuError("no RDK-E image in %s: it has no %s" % (directory, " and no ".join(missing)),
                       hint="the launcher does not build the RDK-E root file system; %s says how it is built with "
                            "Yocto and which files go there (--option %s=DIR names another directory)"
                            % (RDKE_README, RDKE_DIR_OPTION))
    return {"directory": directory, "kernel": kernel, "root": root, "initrd": _first(directory, RDKE_INITRD)}


def rdke_state(options=None, arch=None):
    """One line for "emu doctor" and "emu build": whether the image is there."""
    try:
        files = rdke_files(options, arch)
    except EmuError as error:
        return False, str(error)
    where = files["directory"]
    try:
        where = where.resolve().relative_to(ROOT)       # as the documents name it
    except ValueError:
        pass
    return True, "%s and %s in %s%s" % (files["kernel"].name, files["root"].name, where,
                                        ", with %s" % files["initrd"].name if files["initrd"] else "")
