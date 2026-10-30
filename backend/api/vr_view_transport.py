"""Bounded, byte-preserving local display transport; no filesystem writes."""
import errno
import os
import socket
import struct

MAX_BYTES = 256 * 1024 * 1024


def address(event_path):
    # FNV-1a is shared with view_snapshot_inbox.hpp; paths distinguish sessions.
    value = 14695981039346656037
    for byte in os.fsencode(event_path):
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f'\0nadoc-view-{os.getuid()}-{value:016x}'


def send_snapshot(event_path, data, *, display=True, capabilities=None):
    """Return False only for an older/unavailable listener. Never retry partial sends."""
    if os.environ.get('NADOC_VR_VIEW_IPC') == '0':
        return False
    if not (48 if display else 1) <= len(data) <= MAX_BYTES:
        raise ValueError('Invalid display packet size')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        try:
            client.connect(address(event_path))
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ECONNREFUSED):
                return False
            raise
        _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise PermissionError('Display receiver belongs to another user')
        client.sendall(struct.pack('<I', len(data)))
        client.sendall(data)
        if client.recv(1) != b'\x01':
            raise ConnectionError('Display receiver did not acknowledge the complete packet')
        if capabilities is not None:
            capability = client.recv(1)
            capabilities['transform_updates'] = bool(capability) and capability[0] >= 7
            capabilities['compressed_panels'] = bool(capability) and capability[0] >= 11
            capabilities['atlas_patches'] = bool(capability) and capability[0] >= 8
    return True
