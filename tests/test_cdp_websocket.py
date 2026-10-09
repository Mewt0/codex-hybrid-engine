"""Tests for the stdlib WebSocket client's frame handling.

RFC6455 lets one WebSocket *message* span several frames. The CDP client used
to return the first fragment as if it were the whole message, which surfaced
much later as a bare `json.JSONDecodeError` — an exception no caller catches.
These tests pin the framing behaviour down with a socket pair, no browser.
"""

from __future__ import annotations

import socket
import struct

import pytest

from hybrid.browser_bridge.cdp import ChromePage, CdpError, WebSocket


def frame(opcode: int, payload: bytes = b"", fin: bool = True) -> bytes:
    """Build an unmasked server->client frame."""
    header = bytearray([(0x80 if fin else 0x00) | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    return bytes(header) + payload


def text_frame(text: str, fin: bool = True) -> bytes:
    return frame(0x1, text.encode("utf-8"), fin=fin)


def continuation_frame(text: str, fin: bool = True) -> bytes:
    return frame(0x0, text.encode("utf-8"), fin=fin)


class Wire:
    """A WebSocket wired to a socket pair instead of a real TCP connection."""

    def __init__(self) -> None:
        local, self.peer = socket.socketpair()
        self.ws = WebSocket.__new__(WebSocket)
        self.ws.sock = local
        self.ws.timeout = 5.0
        self.ws._desynchronised = False

    def send(self, data: bytes) -> None:
        self.peer.sendall(data)

    def close(self) -> None:
        for sock in (self.ws.sock, self.peer):
            try:
                sock.close()
            except OSError:
                pass


@pytest.fixture()
def wire():
    connection = Wire()
    yield connection
    connection.close()


def test_single_frame_message(wire):
    wire.send(text_frame('{"id":1}'))
    assert wire.ws.recv_text() == '{"id":1}'


def test_fragmented_message_is_reassembled(wire):
    """The bug: only the first fragment was returned."""
    payload = "x" * 200
    wire.send(text_frame(payload[:60], fin=False))
    wire.send(continuation_frame(payload[60:120], fin=False))
    wire.send(continuation_frame(payload[120:], fin=True))
    assert wire.ws.recv_text() == payload


def test_fragmented_json_reply_stays_parseable(wire):
    import json

    message = json.dumps({"id": 7, "result": {"value": "y" * 300}})
    wire.send(text_frame(message[:80], fin=False))
    wire.send(continuation_frame(message[80:], fin=True))
    assert json.loads(wire.ws.recv_text())["id"] == 7


def test_ping_is_answered_and_does_not_swallow_the_message(wire):
    wire.send(frame(0x9, b"ping"))
    wire.send(text_frame("after-ping"))
    assert wire.ws.recv_text() == "after-ping"
    # The pong came back on the same socket and echoes the ping payload (RFC6455).
    pong = wire.peer.recv(64)
    assert pong[0] == 0x8A
    assert pong[1] & 0x80, "client frames must be masked"
    length = pong[1] & 0x7F
    mask = pong[2:6]
    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(pong[6 : 6 + length]))
    assert payload == b"ping"


def test_continuation_without_a_start_frame_is_an_error(wire):
    wire.send(continuation_frame("orphan", fin=True))
    with pytest.raises(CdpError, match="without a start frame"):
        wire.ws.recv_text()


def test_unknown_opcode_is_an_error(wire):
    wire.send(frame(0x2, b"binary"))  # opcode 2 = binary, not used by CDP
    with pytest.raises(CdpError, match="Unsupported WebSocket opcode"):
        wire.ws.recv_text()


def test_closed_connection_is_reported(wire):
    wire.send(frame(0x8, b""))
    with pytest.raises(CdpError, match="closed by peer"):
        wire.ws.recv_text()


def test_malformed_json_never_escapes_as_json_error(wire):
    page = ChromePage(port=1)
    page.ws = wire.ws
    wire.send(text_frame("{not json"))
    with pytest.raises(CdpError, match="malformed DevTools frame"):
        page.call("Runtime.evaluate", timeout=2.0)
    # The stream is no longer trustworthy, so the next call is refused.
    with pytest.raises(CdpError, match="lost its frame boundary"):
        page.call("Runtime.evaluate", timeout=2.0)


def test_partial_frame_timeout_marks_the_socket_unusable(wire):
    page = ChromePage(port=1)
    page.ws = wire.ws
    wire.send(b"\x81")  # a frame header cut in half, then silence
    with pytest.raises(CdpError, match="timed out"):
        page.call("Runtime.evaluate", timeout=0.6)
    assert wire.ws._desynchronised is True
    with pytest.raises(CdpError, match="lost its frame boundary"):
        page.call("Runtime.evaluate", timeout=0.6)
