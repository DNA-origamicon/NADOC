"""Small authenticated sidecar for the final-output recorder; standard library only.

The client never controls hands, restarts a viewer, retries uncertain commands,
or writes a journal during the capture interval. Pixel and journal verdicts are
separate: a journal failure cannot erase successfully recorded pixel evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct
import time


class PoseJournalClient:
    def __init__(self, context, viewer_pid):
        self.context = dict(context)
        self.viewer_pid = int(viewer_pid)
        self.session = context.get("session")
        self.endpoint = Path(context["socket"])
        if (self.viewer_pid <= 0 or not self.endpoint.is_absolute()
                or not isinstance(self.session, str) or not self.session
                or any(c not in "0123456789-" for c in self.session)):
            raise ValueError("Pose journal requires an identified viewer session and absolute socket")
        self.request = None

    def exchange(self, command):
        parent = self.endpoint.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ValueError("Pose journal socket must have an owned private directory")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(self.endpoint))
            peer_pid, peer_uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if peer_pid != self.viewer_pid or peer_uid != os.getuid():
                raise RuntimeError("Pose journal viewer process identity changed")
            connection.sendall((command + "\n").encode("ascii"))
            data = bytearray()
            while not data.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    raise ConnectionError("Pose journal command delivery uncertain; not retried")
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    raise ValueError("Pose journal reply exceeds bound")
        result = json.loads(data)
        if result.get("session") != self.session:
            raise RuntimeError("Pose journal viewer session changed")
        if "error" in result:
            raise RuntimeError("Pose journal command rejected: " + str(result["error"]))
        return result

    def command(self, verb, *arguments):
        before = self.exchange("observe")
        sequence = before["command_sequence"] + 1
        after = self.exchange(f"{self.session} {sequence} pose_journal {verb} " + " ".join(map(str, arguments)))
        if after.get("command_sequence") != sequence:
            raise RuntimeError("Pose journal command sequence changed")
        status = after.get("pose_journal")
        if not isinstance(status, dict):
            raise RuntimeError("Viewer did not expose pose journal status")
        return status

    def arm(self, request):
        self.request = request
        return self.command("arm", request, 30)

    def window(self, started):
        if started["request"] != self.request:
            raise ValueError("Pose journal window belongs to another capture")
        return self.command("window", self.request, started["start_ns"], started["end_ns"])

    def finish(self, started):
        # Only invoked after compositor completion. Bound the additional tail
        # wait independently of metadata or pixel saving duration.
        remaining = (started["end_ns"] + 100_000_000 - time.monotonic_ns()) / 1e9
        if remaining > .25:
            raise RuntimeError("Compositor completed before its declared capture interval")
        if remaining > 0:
            time.sleep(remaining + .01)
        status = self.command("flush", self.request)
        deadline = time.monotonic() + 5
        while status.get("phase") in ("saving", "writing") and time.monotonic() < deadline:
            time.sleep(.025)
            status = self.exchange("observe").get("pose_journal", {})
        if str(status.get("request")) != str(self.request) or status.get("phase") != "saved":
            raise RuntimeError("Pose journal did not save: " + json.dumps(status))
        return status

    def cancel(self):
        return self.command("cancel", self.request)
