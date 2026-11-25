"""The viewer's display for a picture that is a buffer of the host's GPU.

Where QEMU renders the target's display on the host GPU, on Linux, it hands
over the GPU's buffer and no pixels (emulator/dbusdisplay.py). This widget
takes such a buffer as a texture of its own OpenGL context and draws it: no
copy of the picture is made on the way from the target to the window.

The buffer comes as a file descriptor (a Linux dma-buf). EGL makes an image
of it (EGL_EXT_image_dma_buf_import), and OpenGL ES a texture of the image.
Qt has no call for either, so both are made through the host's libEGL and
libGLESv2, in the context Qt made. That context has to be an EGL one: on X11
Qt makes a GLX context unless it is told otherwise, which `prepare()` does
before the application object is made.

    python -m emulator.gui.gldisplay --probe

says, as one line of JSON, whether this host's Qt can make such a context and
whether its EGL takes such buffers: the launcher asks before it tells QEMU to
send them (emulator/graphics.py).
"""
import ctypes
import json
import os
import sys

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PySide6.QtOpenGLWidgets import QOpenGLWidget

EGL_EXTENSIONS, EGL_NONE, EGL_NO_IMAGE = 0x3055, 0x3038, None
EGL_WIDTH, EGL_HEIGHT, EGL_LINUX_DMA_BUF = 0x3057, 0x3056, 0x3270
EGL_FOURCC, EGL_PLANE0_FD, EGL_PLANE0_OFFSET, EGL_PLANE0_PITCH = 0x3271, 0x3272, 0x3273, 0x3274
EGL_PLANE0_MODIFIER_LO, EGL_PLANE0_MODIFIER_HI = 0x3443, 0x3444
IMPORT_EXTENSION = "EGL_EXT_image_dma_buf_import"
MODIFIER_EXTENSION = "EGL_EXT_image_dma_buf_import_modifiers"
NO_MODIFIER = 0x00ffffffffffffff

GL_TEXTURE_2D, GL_RGBA, GL_UNSIGNED_BYTE, GL_BGRA = 0x0DE1, 0x1908, 0x1401, 0x80E1
GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, GL_LINEAR = 0x2800, 0x2801, 0x2600, 0x2601
GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE = 0x2802, 0x2803, 0x812F
GL_COLOR_BUFFER_BIT, GL_TRIANGLE_STRIP, GL_BLEND, GL_SCISSOR_TEST, GL_DEPTH_TEST = 0x4000, 5, 0x0BE2, 0x0C11, 0x0B71
GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_COMPLETE = 0x8D40, 0x8CE0, 0x8CD5
GL_FRAMEBUFFER_BINDING, GL_PACK_ALIGNMENT, GL_UNPACK_ALIGNMENT, GL_UNPACK_ROW_LENGTH = 0x8CA6, 0x0D05, 0x0CF5, 0x0CF2
GL_VENDOR, GL_RENDERER, GL_VERSION = 0x1F00, 0x1F01, 0x1F02

# The four corners come from the vertex's number, so that no vertex data has
# to be handed over. `flip` turns a buffer whose first row is the bottom one.
VERTEX_SHADER = """#version 300 es
uniform float flip;
out vec2 at;
void main() {
    vec2 corner = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
    at = vec2(corner.x, mix(1.0 - corner.y, corner.y, flip));
    gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0);
}
"""
# `swap` is for pixels that came as blue, green, red where the texture holds
# red, green, blue. What the target leaves in the fourth byte is not shown.
FRAGMENT_SHADER = """#version 300 es
precision mediump float;
uniform sampler2D picture;
uniform float swap;
in vec2 at;
out vec4 colour;
void main() {
    vec4 found = texture(picture, at);
    colour = vec4(mix(found.rgb, found.bgr, swap), 1.0);
}
"""


class Refused(Exception):
    """The host's graphics driver did not take a buffer, or has no way to."""


def prepare():
    """Make Qt's OpenGL contexts EGL ones, of OpenGL ES 3. To be called before
    the application object is made."""
    if sys.platform.startswith("linux"):
        # Qt's X11 plug-in chooses GLX unless this says EGL; its Wayland one has EGL only.
        os.environ.setdefault("QT_XCB_GL_INTEGRATION", "xcb_egl")
    wanted = QSurfaceFormat()
    wanted.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
    wanted.setVersion(3, 0)
    wanted.setAlphaBufferSize(0)
    # The window does not wait for the screen's refresh when it shows a
    # picture: QEMU holds the target's drawing until the picture is drawn, and
    # with the screen asleep the NVIDIA driver lets a window that waits show
    # one picture a second.
    wanted.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(wanted)


class _Libraries:
    """The host's EGL and OpenGL ES libraries, with what this module calls."""

    def __init__(self):
        pointer, integer, unsigned = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint
        try:
            self.egl = egl = ctypes.CDLL("libEGL.so.1")
            self.gl = gl = ctypes.CDLL("libGLESv2.so.2")
        except OSError as error:
            raise Refused("the host's EGL and OpenGL ES libraries could not be loaded: %s" % error)
        egl.eglGetCurrentDisplay.restype = pointer
        egl.eglQueryString.restype, egl.eglQueryString.argtypes = ctypes.c_char_p, [pointer, integer]
        egl.eglGetProcAddress.restype, egl.eglGetProcAddress.argtypes = pointer, [ctypes.c_char_p]
        gl.glGetString.restype, gl.glGetString.argtypes = ctypes.c_char_p, [unsigned]
        gl.glTexParameteri.argtypes = [unsigned, unsigned, integer]
        gl.glTexImage2D.argtypes = [unsigned, integer, integer, integer, integer, integer, unsigned, unsigned, pointer]
        gl.glReadPixels.argtypes = [integer, integer, integer, integer, unsigned, unsigned, pointer]

        def extension(name, result, *arguments):
            address = egl.eglGetProcAddress(name)
            return ctypes.CFUNCTYPE(result, *arguments)(address) if address else None

        self.create_image = extension(b"eglCreateImageKHR", pointer, pointer, pointer, unsigned, pointer, pointer)
        self.destroy_image = extension(b"eglDestroyImageKHR", unsigned, pointer, pointer)
        self.image_to_texture = extension(b"glEGLImageTargetTexture2DOES", None, unsigned, pointer)

    def display(self):
        """The EGL display of the context that is current, with its extensions."""
        found = self.egl.eglGetCurrentDisplay()
        if not found:
            raise Refused("Qt's OpenGL context is not an EGL one (%s)" % self.context_name())
        return found, (self.egl.eglQueryString(found, EGL_EXTENSIONS) or b"").decode().split()

    def context_name(self):
        return " / ".join((self.gl.glGetString(name) or b"?").decode(errors="replace")
                          for name in (GL_VENDOR, GL_RENDERER, GL_VERSION))

    def require_import(self):
        """Raise Refused unless buffers can be taken in the current context."""
        _, extensions = self.display()
        if IMPORT_EXTENSION not in extensions:
            raise Refused("the host's EGL does not take GPU buffers (%s is missing; %s)"
                          % (IMPORT_EXTENSION, self.context_name()))
        if not (self.create_image and self.destroy_image and self.image_to_texture):
            raise Refused("the host's EGL has no images of GPU buffers (%s)" % self.context_name())


class Shaped:
    """Where a display of a known size is drawn in a widget: scaled to it,
    keeping its shape, and centred. `display_size()` is the display's."""

    def natural_size(self):
        """The widget size at which one pixel of the display is one pixel of
        the screen."""
        ratio = self.devicePixelRatioF()
        width, height = self.display_size()
        return QSize(round(width / ratio), round(height / ratio))

    def sizeHint(self):
        return self.natural_size()

    def shown_rect(self):
        """Where in the widget the display is drawn."""
        width, height = self.display_size()
        scale = min(self.width() / width, self.height() / height)
        shown = QSize(max(1, round(width * scale)), max(1, round(height * scale)))
        return QRect(QPoint((self.width() - shown.width()) // 2, (self.height() - shown.height()) // 2), shown)


class GLDisplay(Shaped, QOpenGLWidget):
    """The target's display, drawn from the GPU's buffer. Has what the
    viewer's other display has: on_size, on_update, on_state, picture()."""

    def __init__(self):
        super().__init__()
        self.message = "waiting for the target's display"
        self.client = None
        self.failure = None             # why the host took no buffer, once it did not
        self.on_failure = lambda text: None
        self.drawn = 0                  # pictures of the target's that were drawn, for the checks
        self._size = None               # the display's
        self._libraries = None
        self._program = None
        self._waiting = None            # a buffer that is still to be made a texture
        self._pixels = None             # or a picture that came as pixels
        self._texture = None            # (texture, EGL image or None, width, height, top row first, blue first)
        self._owed = False              # the client waits to hear that a picture was drawn
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(160, 90)

    def display_size(self):
        return self._size or (1920, 1080)

    def has_picture(self):
        return self._texture is not None or self._waiting is not None or self._pixels is not None

    # ------------------------------------------------------ from the client

    def on_size(self, width, height):
        self._size = (width, height)
        self.updateGeometry()
        self.update()

    def on_buffer(self, buffer):
        if self._waiting is not None:
            _close(self._waiting["descriptor"])
        self._waiting, self._pixels = buffer, None
        if self._texture is None:
            self.update()               # else with the picture that QEMU announces next

    def on_update(self, x, y, width, height, pixels):
        if pixels is not None:
            # A whole picture as pixels: what QEMU sends while the target does
            # not use the GPU. dbusdisplay.Client hands over all of it each time.
            self._pixels = (width, height, pixels)
        self._owed = True
        if self.isVisible() and not self.window().isMinimized():
            self.update()
        else:
            self._settle()              # nothing is drawn while the window cannot be seen

    def on_state(self, text):
        self.message = text
        self.update()

    def _settle(self):
        if self._owed:
            self._owed = False
            if self.client is not None:
                self.client.shown()

    # -------------------------------------------------------------- OpenGL

    def initializeGL(self):
        try:
            self._libraries = self._libraries or _Libraries()
            self._libraries.require_import()
        except Refused as error:
            self._fail(str(error))
            return
        self._texture = None            # a new context has none of the old one's
        self.context().aboutToBeDestroyed.connect(self._release)
        program = QOpenGLShaderProgram(self)
        if not (program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER)
                and program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT_SHADER)
                and program.link()):
            self._fail("the host's OpenGL ES did not take the viewer's shaders (%s): %s"
                       % (self._libraries.context_name(), program.log().strip()))
            return
        self._program = program

    def _fail(self, text):
        if self.failure is None:
            self.failure = text
            self.message = "the display cannot be shown: " + text
            self.on_failure(text)

    def _release(self):
        self.makeCurrent()
        self._drop(self._texture)
        self._texture, self._program = None, None
        self.doneCurrent()

    def _drop(self, entry):
        if entry is None or self._libraries is None:
            return
        texture, image = entry[0], entry[1]
        self._libraries.gl.glDeleteTextures(1, ctypes.byref(ctypes.c_uint(texture)))
        if image:
            display, _ = self._libraries.display()
            self._libraries.destroy_image(display, image)

    def _new_texture(self):
        gl = self._libraries.gl
        texture = ctypes.c_uint()
        gl.glGenTextures(1, ctypes.byref(texture))
        gl.glBindTexture(GL_TEXTURE_2D, texture)
        for name in (GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T):
            gl.glTexParameteri(GL_TEXTURE_2D, name, GL_CLAMP_TO_EDGE)
        return texture.value

    def _import(self, buffer):
        """Make the buffer the texture that is drawn. The descriptor is closed
        either way: the image keeps the buffer."""
        libraries = self._libraries
        try:
            display, extensions = libraries.display()

            def image(with_modifier):
                attributes = [EGL_WIDTH, buffer["width"], EGL_HEIGHT, buffer["height"],
                              EGL_FOURCC, buffer["format"], EGL_PLANE0_FD, buffer["descriptor"],
                              EGL_PLANE0_OFFSET, 0, EGL_PLANE0_PITCH, buffer["stride"]]
                if with_modifier:
                    attributes += [EGL_PLANE0_MODIFIER_LO, buffer["modifier"] & 0xffffffff,
                                   EGL_PLANE0_MODIFIER_HI, buffer["modifier"] >> 32]
                attributes.append(EGL_NONE)
                values = (ctypes.c_int32 * len(attributes))(*[ctypes.c_int32(value & 0xffffffff).value
                                                             for value in attributes])
                return libraries.create_image(display, None, EGL_LINUX_DMA_BUF, None, values) or None

            named = buffer["modifier"] != NO_MODIFIER and MODIFIER_EXTENSION in extensions
            found = image(True) if named else None
            if found is None:
                # Also the second try for a driver that names a layout and then wants none named.
                found = image(False)
            if found is None:
                raise Refused("the host's graphics driver did not take the target's picture as a GPU buffer "
                              "(EGL error 0x%04x for format %s, layout 0x%016x, %dx%d; %s)" % (
                                  libraries.egl.eglGetError(),
                                  buffer["format"].to_bytes(4, "little").decode("ascii", "replace"),
                                  buffer["modifier"], buffer["width"], buffer["height"], libraries.context_name()))
        finally:
            _close(buffer["descriptor"])
        while libraries.gl.glGetError():
            pass
        texture = self._new_texture()
        libraries.image_to_texture(GL_TEXTURE_2D, found)
        error = libraries.gl.glGetError()
        if error:
            self._drop((texture, found))
            raise Refused("the host's OpenGL ES did not make a texture of the target's picture "
                          "(error 0x%04x; %s)" % (error, libraries.context_name()))
        old, self._texture = self._texture, (texture, found, buffer["width"], buffer["height"],
                                             buffer["top_first"], False)
        self._drop(old)

    def _upload(self, width, height, pixels):
        """A picture that came as pixels (four bytes each: blue, green, red,
        unused; top row first) into a texture."""
        gl = self._libraries.gl
        old = self._texture
        if old is not None and old[1] is None and old[2:4] == (width, height):
            texture = old[0]
            gl.glBindTexture(GL_TEXTURE_2D, texture)
        else:
            texture = self._new_texture()
            self._drop(old)
        gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
        gl.glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
        data = (ctypes.c_char * len(pixels)).from_buffer(pixels) if isinstance(pixels, bytearray) else pixels
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        self._texture = (texture, None, width, height, True, True)

    def _take_waiting(self):
        """Make a texture of what came since the last picture was drawn."""
        waiting, self._waiting = self._waiting, None
        pixels, self._pixels = self._pixels, None
        if self._program is None:
            if waiting is not None:
                _close(waiting["descriptor"])
            return
        try:
            if waiting is not None:
                self._import(waiting)
            elif pixels is not None:
                self._upload(*pixels)
        except Refused as error:
            self._fail(str(error))

    def paintGL(self):
        self._take_waiting()
        if self._libraries is not None:
            gl = self._libraries.gl
            for state in (GL_BLEND, GL_SCISSOR_TEST, GL_DEPTH_TEST):
                gl.glDisable(state)
            ratio = self.devicePixelRatioF()
            gl.glViewport(0, 0, round(self.width() * ratio), round(self.height() * ratio))
            gl.glClearColor(ctypes.c_float(0), ctypes.c_float(0), ctypes.c_float(0), ctypes.c_float(1))
            gl.glClear(GL_COLOR_BUFFER_BIT)
            if self._texture is not None and self._program is not None and self.failure is None:
                texture, _, _, _, top_first, blue_first = self._texture
                target = self.shown_rect()
                exact = target.size() == self.natural_size()
                # The viewport counts from the bottom left corner.
                gl.glViewport(round(target.x() * ratio), round((self.height() - target.y() - target.height()) * ratio),
                              round(target.width() * ratio), round(target.height() * ratio))
                self._program.bind()
                self._program.setUniformValue1i(self._program.uniformLocation("picture"), 0)
                self._program.setUniformValue1f(self._program.uniformLocation("flip"), 0.0 if top_first else 1.0)
                self._program.setUniformValue1f(self._program.uniformLocation("swap"), 1.0 if blue_first else 0.0)
                gl.glActiveTexture(0x84C0)
                gl.glBindTexture(GL_TEXTURE_2D, texture)
                for name in (GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER):
                    gl.glTexParameteri(GL_TEXTURE_2D, name, GL_NEAREST if exact else GL_LINEAR)
                gl.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
                gl.glBindTexture(GL_TEXTURE_2D, 0)
                self._program.release()
                self.drawn += 1 if self._owed else 0
            gl.glFlush()
        if self.message:
            painter = QPainter(self)
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            painter.end()
        self._settle()

    def picture(self):
        """What arrived from the target, pixel for pixel, as an image; None
        before the first picture. Read back from the GPU."""
        if self._libraries is None or self._program is None or not self.isValid():
            return None
        self.makeCurrent()
        try:
            self._take_waiting()
            if self._texture is None:
                return None
            gl = self._libraries.gl
            texture, _, width, height, top_first, blue_first = self._texture
            before = ctypes.c_int()
            gl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, ctypes.byref(before))
            reader = ctypes.c_uint()
            gl.glGenFramebuffers(1, ctypes.byref(reader))
            gl.glBindFramebuffer(GL_FRAMEBUFFER, reader)
            gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0)
            data = None
            if gl.glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE:
                data = ctypes.create_string_buffer(width * height * 4)
                gl.glPixelStorei(GL_PACK_ALIGNMENT, 4)
                gl.glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, data)
            gl.glBindFramebuffer(GL_FRAMEBUFFER, before.value)
            gl.glDeleteFramebuffers(1, ctypes.byref(reader))
        finally:
            self.doneCurrent()
        if data is None:
            return None
        # The texture's first row is the buffer's first.
        image = QImage(data.raw, width, height, width * 4, QImage.Format.Format_RGBX8888)
        if blue_first:
            image = image.rgbSwapped()
        return (image if top_first else image.mirrored(False, True)).convertToFormat(QImage.Format.Format_RGB32)


def _close(descriptor):
    try:
        os.close(descriptor)
    except OSError:
        pass


def probe():
    """Whether this host's Qt makes an EGL context that takes GPU buffers:
    {"available": ..., "reason": ...}."""
    from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext
    prepare()
    application = QGuiApplication(sys.argv[:1])
    surface = QOffscreenSurface()
    surface.create()
    context = QOpenGLContext()
    if not context.create() or not context.makeCurrent(surface):
        return {"available": False, "reason": "Qt could not make an OpenGL ES context on this host"}
    try:
        libraries = _Libraries()
        libraries.require_import()
        name = libraries.context_name()
        if not context.isOpenGLES() or context.format().majorVersion() < 3:
            raise Refused("Qt's OpenGL context is not an OpenGL ES 3 one (%s)" % name)
        return {"available": True, "reason": "Qt's OpenGL ES context takes GPU buffers (%s)" % name}
    except Refused as error:
        return {"available": False, "reason": str(error)}
    finally:
        context.doneCurrent()
        del application


if __name__ == "__main__":
    if sys.argv[1:] != ["--probe"]:
        sys.exit(__doc__)
    print(json.dumps(probe()), flush=True)
