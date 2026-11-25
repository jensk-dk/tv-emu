"""A client of QEMU's D-Bus display that follows a display: on a host where
QEMU's VNC server is slow, the launcher's window gets a VM's display with it.

QEMU's VNC server looks at the display every 30 ms and waits longer after each
look that found nothing new; a display that changed 35 times a second reached
a client 15 to 20 times a second, whatever the client asked for. Over D-Bus
(QEMU's "-display dbus,p2p=yes") QEMU sends each picture when the target shows
it. Nothing of D-Bus has to be installed: the connection is a private socket
pair that QEMU is handed over its machine protocol, and this module speaks
the little of the D-Bus wire format that the display needs.

    client = Client(qmp_path, on_size, on_update, on_state)
    client.start()          # a thread; it connects, and connects again
    ...
    client.close()

The interface is that of emulator/rfb.py's Client, so that a viewer takes
either: `qmp_path` is the socket of a QEMU machine protocol server kept for
this client, the callbacks run on the client's thread, and after on_update the
client waits for `shown()` before it hands over the next picture. QEMU does
not wait: pictures that arrive while the viewer draws are taken in, and the
viewer gets the newest when it is done.

A display that the host's GPU renders (QEMU's "-display dbus,p2p=yes,gl=on",
on Linux) comes as the GPU's own buffer and not as pixels: QEMU sends a file
descriptor of it (ScanoutDMABUF), and then says for each picture that the
buffer has changed (UpdateDMABUF). A client with `on_buffer` gets those:
on_buffer(buffer) with the descriptor, which is then the viewer's to close,
and on_update(x, y, width, height, None) for each picture. QEMU holds the
target's drawing until an UpdateDMABUF is answered, so the client answers
when the viewer has drawn (`shown()`), or after BUFFER_WAIT seconds.
"""
import array
import collections
import json
import os
import socket
import struct
import threading
import time

CONSOLE = b"/org/qemu/Display1/Console_0"
# Pixman's names for four bytes a pixel as blue, green, red, unused or alpha
# (on a little-endian host), which is what the viewer draws.
PIXEL_FORMATS = (0x20020888, 0x20028888)
METHOD_CALL, METHOD_RETURN, ERROR = 1, 2, 3
NO_REPLY_EXPECTED = 1
# Header fields: path, interface, member, error name, reply serial, signature, file descriptors.
PATH, INTERFACE, MEMBER, ERROR_NAME, REPLY_SERIAL, SIGNATURE, UNIX_FDS = 1, 2, 3, 4, 5, 8, 9
# What QEMU's end of the picture socket may hold unsent. A socket of this kind
# takes 8 KB at a time on macOS unless told otherwise.
SEND_BUFFER = 8 << 20
# How long the target's drawing is held for a viewer that does not draw (a
# window that is hidden draws nothing).
BUFFER_WAIT = 0.1
# A buffer whose layout the GPU driver has not named (DRM_FORMAT_MOD_INVALID).
NO_MODIFIER = 0x00ffffffffffffff


class Closed(Exception):
    """QEMU ended the connection, refused it, or the client was closed."""


def _pad(length, alignment):
    return (-length) % alignment


def _field(code, signature, value):
    out = bytes([code, len(signature)]) + signature + b"\0"
    if signature in (b"s", b"o"):
        out += b"\0" * _pad(len(out), 4) + struct.pack("<I", len(value)) + value + b"\0"
    elif signature == b"g":
        out += bytes([len(value)]) + value + b"\0"
    else:                                                   # b"u"
        out += b"\0" * _pad(len(out), 4) + struct.pack("<I", value)
    return out


def _message(kind, serial, fields, body=b"", flags=0):
    array = b""
    for field in fields:
        array += b"\0" * _pad(len(array), 8) + field
    head = struct.pack("<cBBBIII", b"l", kind, flags, 1, len(body), serial, len(array)) + array
    return head + b"\0" * _pad(len(head), 8) + body


def _receive(connection, count, into=None):
    data = bytearray(count) if into is None else into
    view = memoryview(data)
    got = 0
    while got < count:
        read = connection.recv_into(view[got:count], count - got)
        if not read:
            raise Closed()
        got += read
    return data


def _header(connection):
    """The next message's (kind, flags, serial, fields, body length); its body
    is still to be read."""
    endian, kind, flags, _, body, serial, fields_length = struct.unpack("<cBBBIII", bytes(_receive(connection, 16)))
    if endian != b"l":
        raise Closed()
    array = bytes(_receive(connection, fields_length + _pad(16 + fields_length, 8)))[:fields_length]
    fields = {}
    at = 0
    while at < fields_length:
        at += _pad(at, 8)
        code, length = array[at], array[at + 1]
        signature = array[at + 2:at + 2 + length]
        at += 3 + length
        if signature in (b"s", b"o"):
            at += _pad(at, 4)
            size = struct.unpack_from("<I", array, at)[0]
            fields[code] = array[at + 4:at + 4 + size]
            at += 5 + size
        elif signature == b"g":
            size = array[at]
            fields[code] = array[at + 1:at + 1 + size]
            at += 2 + size
        elif signature == b"u":
            at += _pad(at, 4)
            fields[code] = struct.unpack_from("<I", array, at)[0]
            at += 4
        else:
            raise Closed()
    return kind, flags, serial, fields, body


class _WithDescriptors:
    """A socket whose reads keep the file descriptors that come with the
    bytes, in `descriptors`, in the order they came."""

    def __init__(self, connection):
        self._connection = connection
        self.descriptors = collections.deque()

    def recv_into(self, view, count):
        read, ancillary, _, _ = self._connection.recvmsg_into([view[:count]], socket.CMSG_SPACE(16 * 4))
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                found = array.array("i")
                found.frombytes(data[:len(data) - len(data) % found.itemsize])
                self.descriptors.extend(found)
        return read

    def recv(self, count):
        data = bytearray(count)
        return bytes(data[:self.recv_into(memoryview(data), count)])

    def discard(self):
        while self.descriptors:
            try:
                os.close(self.descriptors.popleft())
            except OSError:
                pass

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _authenticate(connection):
    """D-Bus's opening lines, as the user this program runs as."""
    def line():
        text = b""
        while not text.endswith(b"\r\n"):
            byte = connection.recv(1)
            if not byte:
                raise Closed()
            text += byte
        return text
    connection.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
    if not line().startswith(b"OK"):
        raise Closed()
    connection.sendall(b"NEGOTIATE_UNIX_FD\r\n")
    line()
    connection.sendall(b"BEGIN\r\n")


def _hand_to_qemu(qmp_path, descriptor):
    """Give QEMU one end of a socket pair as a client of its D-Bus display."""
    control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        control.settimeout(10)
        control.connect(qmp_path)
        lines = control.makefile("rb")

        def command(name, arguments=None, descriptors=()):
            data = (json.dumps({"execute": name, "arguments": arguments or {}}) + "\n").encode()
            if descriptors:
                socket.send_fds(control, [data], list(descriptors))
            else:
                control.sendall(data)
            while True:
                text = lines.readline()
                if not text:
                    raise Closed()
                answer = json.loads(text)
                if "error" in answer:
                    raise Closed()
                if "return" in answer:
                    return answer

        if not lines.readline():                            # the greeting
            raise Closed()
        command("qmp_capabilities")
        command("getfd", {"fdname": "emu-display"}, [descriptor])
        command("add_client", {"protocol": "@dbus-display", "fdname": "emu-display"})
    finally:
        control.close()


class Client(threading.Thread):
    def __init__(self, address, on_size, on_update, on_state=None, on_buffer=None):
        super().__init__(daemon=True)
        self.address = address
        self.on_size = on_size
        self.on_update = on_update
        self.on_state = on_state or (lambda text: None)
        self.on_buffer = on_buffer
        self.connected = False
        self.size = None
        self.updates = 0
        self._connections = []
        self._closing = False
        self._shown = threading.Event()
        self._shown.set()
        self._frame = None          # the display as last heard of, four bytes a pixel
        self._fresh = False         # the viewer has not been given it yet
        self._given = False         # the viewer may still be drawing from it

    def shown(self):
        """The viewer has drawn the last update; the next may be handed over."""
        self._shown.set()

    def close(self):
        self._closing = True
        self._shown.set()
        for connection in list(self._connections):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # ------------------------------------------------------------------

    def run(self):
        waited = False
        while not self._closing:
            self._connections = []
            try:
                self._follow()
            except (OSError, Closed, struct.error, ValueError):
                pass
            finally:
                was_connected = self.connected
                self.connected = False
                for connection in self._connections:
                    try:
                        connection.close()
                    except OSError:
                        pass
            if not self._closing:
                if was_connected or not waited:
                    self.on_state("the target's display is off" if was_connected else "waiting for the target's display")
                    waited = True
                time.sleep(0.2)

    def _pair(self):
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self._connections.append(ours)
        return ours, theirs

    def _follow(self):
        # One connection to ask for the pictures, and a second, which QEMU
        # gets through the first, that it sends them on.
        control, for_qemu = self._pair()
        try:
            _hand_to_qemu(self.address, for_qemu.fileno())
        finally:
            for_qemu.close()
        control.settimeout(10)
        _authenticate(control)
        pictures, for_qemu = self._pair()
        try:
            try:
                for_qemu.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER)
            except OSError:
                pass
            call = _message(METHOD_CALL, 1,
                            [_field(PATH, b"o", CONSOLE), _field(INTERFACE, b"s", b"org.qemu.Display1.Console"),
                             _field(MEMBER, b"s", b"RegisterListener"), _field(SIGNATURE, b"g", b"h"),
                             _field(UNIX_FDS, b"u", 1)], struct.pack("<I", 0))
            socket.send_fds(control, [call], [for_qemu.fileno()])
        finally:
            for_qemu.close()
        kind, _, _, _, body = _header(control)
        _receive(control, body)
        if kind != METHOD_RETURN:
            raise Closed()
        pictures.settimeout(10)
        if self.on_buffer is not None and hasattr(pictures, "recvmsg_into"):
            pictures = _WithDescriptors(pictures)
        _authenticate(pictures)
        self.connected = True
        self.on_state("")
        self._shown.set()
        serial = 1
        # A short wait, so that a picture which came while the viewer drew is
        # handed over when it is done, also when no other follows.
        pictures.settimeout(0.02)
        while not self._closing:
            try:
                kind, flags, call_serial, fields, body = _header(pictures)
            except socket.timeout:
                self._hand_over()
                continue
            pictures.settimeout(10)
            self._take(pictures, fields.get(MEMBER), body)
            if kind == METHOD_CALL and not flags & NO_REPLY_EXPECTED:
                serial += 1
                pictures.sendall(_message(METHOD_RETURN, serial, [_field(REPLY_SERIAL, b"u", call_serial)]))
            self._hand_over()
            pictures.settimeout(0.02)

    def _take(self, connection, member, body):
        """Read one message's body: a whole picture (Scanout), a part of one
        (Update), or something this client has no use for."""
        if member == b"Scanout" and body >= 20:
            width, height, stride, pixel_format, length = struct.unpack("<IIIII", bytes(_receive(connection, 20)))
            self._picture(connection, 0, 0, width, height, stride, pixel_format, length, whole=True)
            _receive(connection, body - 20 - length)
        elif member == b"ScanoutDMABUF" and body >= 36 and getattr(connection, "descriptors", None):
            # The descriptor's place among those of the message (always the
            # first), then the buffer's layout.
            _, width, height, stride, fourcc, modifier, y0_top = struct.unpack(
                "<IIIIIxxxxQI", bytes(_receive(connection, 36)))
            _receive(connection, body - 36)
            descriptor = connection.descriptors.popleft()
            self._frame, self._fresh = None, False
            self._set_size(width, height)
            self.on_buffer({"descriptor": descriptor, "width": width, "height": height, "stride": stride,
                            "format": fourcc, "modifier": modifier,
                            # QEMU's "y0_top" is set for a buffer whose first row is the bottom one:
                            # its own windows turn the picture over when it is not set.
                            "top_first": not y0_top})
        elif member == b"UpdateDMABUF" and body >= 16:
            x, y, width, height = struct.unpack("<iiii", bytes(_receive(connection, 16)))
            _receive(connection, body - 16)
            if self.on_buffer is not None:
                self._shown.clear()
                self.updates += 1
                self.on_update(x, y, width, height, None)
                self._shown.wait(BUFFER_WAIT)
                self._shown.set()
        elif member == b"Update" and body >= 28:
            x, y, width, height, stride, pixel_format, length = struct.unpack(
                "<iiiiIII", bytes(_receive(connection, 28)))
            self._picture(connection, x, y, width, height, stride, pixel_format, length, whole=False)
            _receive(connection, body - 28 - length)
        elif body:
            _receive(connection, body)
        if hasattr(connection, "discard"):
            connection.discard()            # descriptors of a message this client has no use for

    def _picture(self, connection, x, y, width, height, stride, pixel_format, length, whole):
        usable = pixel_format in PIXEL_FORMATS and width > 0 and height > 0 and stride >= width * 4 \
            and length >= stride * (height - 1) + width * 4
        if whole and usable and stride == width * 4:
            # Straight into a buffer of its own, which becomes the display.
            frame = bytearray(width * height * 4)
            _receive(connection, width * height * 4, frame)
            _receive(connection, length - width * height * 4)
            self._set_size(width, height)
            self._frame, self._fresh, self._given = frame, True, False
            return
        data = _receive(connection, length)
        if not usable:
            return
        if whole:
            self._set_size(width, height)
            self._frame, self._given = bytearray(width * height * 4), False
        if self._frame is None or self.size is None:
            return
        full_width, full_height = self.size
        if x < 0 or y < 0 or x + width > full_width or y + height > full_height:
            return
        if self._given:
            # The viewer may still draw from the buffer it was given.
            self._frame, self._given = bytearray(self._frame), False
        target = memoryview(self._frame)
        source = memoryview(data)
        for row in range(height):
            start = ((y + row) * full_width + x) * 4
            target[start:start + width * 4] = source[row * stride:row * stride + width * 4]
        self._fresh = True

    def _set_size(self, width, height):
        if self.size != (width, height):
            self.size = (width, height)
            self.on_size(width, height)

    def _hand_over(self):
        if self._fresh and self._shown.is_set() and self._frame is not None and self.size is not None:
            self._shown.clear()
            self._fresh, self._given = False, True
            self.updates += 1
            self.on_update(0, 0, self.size[0], self.size[1], self._frame)
