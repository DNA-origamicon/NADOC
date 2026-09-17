#!/usr/bin/env python3
"""Dependency-free MCP stdio bridge for NADOC's opt-in Linux viewer endpoint.

JSON-RPC remains available while the viewer is offline. Commands are never retried:
if delivery is uncertain, observe the session/sequence before deciding what to do.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import stat
import tempfile
from pathlib import Path
import socket
import sys
import time

PROTOCOL = "2025-11-25"
MAX_MESSAGE = 65536
MAX_REPLY = 1024 * 1024


def schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {},
            "required": required or [], "additionalProperties": False}


SESSION = {"session": {"type": "string", "maxLength": 80},
           "expected_sequence": {"type": "integer", "minimum": 0}}
HAND = {"type": "integer", "minimum": 0, "maximum": 1}
VECTOR = {"type": "array", "items": {"type": "number", "minimum": -100, "maximum": 100},
          "minItems": 3, "maxItems": 3}


def tool(name, description, properties=None, required=None, read=False):
    return {"name": "scrywrite_" + name, "description": description,
            "inputSchema": schema(properties, required),
            "annotations": {"readOnlyHint": read, "destructiveHint": not read,
                            "idempotentHint": read, "openWorldHint": False}}


def action(name, description, properties=None):
    properties = {**SESSION, **(properties or {})}
    return tool(name, description, properties, list(properties))


TOOLS = [
    tool("observe", "Inspect live session, frame, controls, owner identity, browser acknowledgement and Extrude draft. Works after viewer restarts. Offline is an explicit error.", read=True),
    action("pose", "Set one test hand pose in OpenXR LOCAL meters, quaternion XYZW. Does not move the physical head. Held buttons expire after two seconds without a control command; neutral poses remain available.",
           {"hand": HAND, "position": VECTOR,
            "orientation": {**VECTOR, "minItems": 4, "maxItems": 4}}),
    action("button", "Set menu, trigger, grip or trackpad state. Uses production input handling on subsequent focused frames. Always release held buttons.",
           {"hand": HAND, "button": {"enum": ["menu", "trigger", "grip", "trackpad"]}, "pressed": {"type": "boolean"}}),
    action("aim_menu", "Aim a valid test hand at a discovered menu label; observe hover after a frame to independently verify the production hit test.",
           {"hand": HAND, "label": {"type": "string", "minLength": 1, "maxLength": 128}}),
    action("aim_lattice", "Aim at a visible Extrude cell. Does not select it; use trigger and verify cells/hover. Painted footprint currently cannot commit.",
           {"hand": HAND, "row": {"type": "integer", "minimum": -100000, "maximum": 100000},
            "column": {"type": "integer", "minimum": -100000, "maximum": 100000}}),
    action("aim_border", "Aim at a panel border for a production grip-drag. Moves the ray orientation, not the hand position.",
           {"hand": HAND, "panel": {"enum": ["menu", "lattice"]},
            "edge": {"enum": ["left", "right", "top", "bottom"]}}),
    action("activate", "Semantic test entry to the production radial tool activation. Requires a valid right hand. This bypasses radial acquisition; it does not prove radial UI usability.",
           {"tool": {"enum": ["extrude", "move_rotate", "twist", "bend"]}}),
    action("release", "Neutralize all scripted hands and held buttons; available even when unfocused."),
    action("capture", "Capture the next submitted stereo app frame: PNGs, window depth, render classes, per-pixel uint32 object IDs and objects.json mapping primitive identities/owner tokens, plus semantic/transaction metadata. IDs are stable within the viewer session; zero denotes background/UI; glow creates no IDs. Returns left-eye image. No compositor acknowledgement; requires rendering."),
    tool("wait", "Wait for an observed frame/state predicate in this session. Does not renew held inputs. Runtime frames are not deterministic virtual steps.",
         {"session": SESSION["session"], "field": {"enum": ["frame", "hover", "menu", "status", "tool", "execution_feedback_sequence", "extrude.hover", "extrude.cells", "extrude.open"]},
          "value": {}, "comparison": {"enum": ["equals", "at_least"]},
          "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 10000}},
         ["session", "field", "value"], read=True),
]
BY_NAME = {item["name"]: item for item in TOOLS}


def validate(value, spec):
    """Validate the deliberately small schema vocabulary used by this server."""
    kind = spec.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("expected object")
        props = spec["properties"]
        if set(value) - set(props) or set(spec["required"]) - set(value):
            raise ValueError("missing or unknown arguments")
        for key, child in value.items():
            validate(child, props[key])
    elif kind == "array":
        if not isinstance(value, list) or not spec["minItems"] <= len(value) <= spec["maxItems"]:
            raise ValueError("invalid vector length")
        for child in value:
            validate(child, spec["items"])
    elif kind == "string":
        if not isinstance(value, str) or not spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", 1000):
            raise ValueError("invalid string")
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("control/non-ASCII characters are not allowed")
    elif kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("expected finite number")
        if kind == "integer" and not isinstance(value, int):
            raise ValueError("expected integer")
        if not spec.get("minimum", -math.inf) <= value <= spec.get("maximum", math.inf):
            raise ValueError("number out of range")
    elif kind == "boolean" and not isinstance(value, bool):
        raise ValueError("expected boolean")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError("unsupported value")


class Bridge:
    def __init__(self, socket_path=None, trace=None, state_path=None):
        self._socket_path = str(socket_path) if socket_path else None
        self.state_path = Path(state_path) if state_path else Path(tempfile.gettempdir()) / f"nadoc-vr-{os.getuid()}.json"
        self.trace = trace

    @property
    def socket_path(self):
        if self._socket_path:
            return self._socket_path
        info = self.state_path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("viewer state must be an owned private regular file")
        if info.st_size > MAX_MESSAGE:
            raise ValueError("viewer state too large")
        state = json.loads(self.state_path.read_text())
        endpoint = state.get("scrywrite_socket")
        if state.get("scrywrite_live") not in ("inspect", "transactions") or not isinstance(endpoint, str) or not Path(endpoint).is_absolute():
            raise ValueError("no agent-enabled viewer; launch NADOC with scrywrite=inspect or transactions")
        return endpoint

    def request(self, command):
        payload = (command + "\n").encode("ascii")
        if len(payload) > 4096:
            raise ValueError("command too large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            endpoint = self.socket_path
            parent = Path(endpoint).parent.lstat()
            if not Path(endpoint).is_absolute() or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
                raise ValueError("viewer socket must be in an owned private directory")
            connection.connect(endpoint)
            connection.sendall(payload)
            data = bytearray()
            while not data.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    raise ConnectionError("viewer disconnected; delivery may be uncertain, observe before retrying")
                data.extend(chunk)
                if len(data) > MAX_REPLY:
                    raise ValueError("viewer reply too large")
        result = json.loads(data)
        if self.trace:
            with open(self.trace, "a", encoding="utf-8") as output:
                output.write(json.dumps({"time_ns": time.monotonic_ns(), "command": command, "state": result}) + "\n")
        return result

    def wait(self, session, predicate, timeout_ms=5000):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            state = self.request("observe")
            if state.get("session") != session:
                raise ValueError("viewer session changed")
            if predicate(state):
                return state
            if time.monotonic() >= deadline:
                raise TimeoutError("state predicate timed out; last state: " + json.dumps(state))
            time.sleep(0.02)

    def call(self, name, args):
        if name not in BY_NAME:
            raise ValueError("unknown tool")
        validate(args, BY_NAME[name]["inputSchema"])
        operation = name.removeprefix("scrywrite_")
        if operation == "observe":
            return self.request("observe")
        if operation == "wait":
            def matches(state):
                value = state
                for part in args["field"].split("."):
                    value = value[part]
                if args.get("comparison", "equals") == "at_least":
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(args["value"], bool) or not isinstance(args["value"], (int, float)):
                        raise ValueError("at_least requires numeric values")
                    return value >= args["value"]
                return value == args["value"]
            return self.wait(args["session"], matches, args.get("timeout_ms", 5000))
        session = args["session"]
        if not session or any(c not in "0123456789-" for c in session):
            raise ValueError("invalid session token")
        command = operation
        if operation == "pose":
            if not 0.99 <= math.sqrt(sum(v*v for v in args["orientation"])) <= 1.01:
                raise ValueError("orientation must be normalized XYZW")
            command += " " + " ".join(map(str, [args["hand"], *args["position"], *args["orientation"]]))
        elif operation == "button":
            command += f" {args['hand']} {args['button']} {int(args['pressed'])}"
        elif operation == "aim_menu":
            command = f"aim {args['hand']} {args['label']}"
        elif operation == "aim_lattice":
            command += f" {args['hand']} {args['row']} {args['column']}"
        elif operation == "aim_border":
            command += f" {args['hand']} {args['panel']} {args['edge']}"
        elif operation == "activate":
            command += " " + args["tool"]
        sequence = args["expected_sequence"] + 1
        result = self.request(f"{session} {sequence} {command}")
        if "error" in result:
            return result
        if operation == "capture":
            def captured(state):
                capture = state.get("capture") or {}
                if capture.get("command_sequence") != sequence:
                    raise ValueError("capture superseded by another command")
                return capture.get("status") in ("complete", "failed")
            result = self.wait(session, captured)
        return result


def tool_result(result, *, capture=False):
    failed = "error" in result or (capture and (result.get("capture") or {}).get("status") == "failed")
    return {"content": [{"type": "text", "text": json.dumps(result)}],
            "structuredContent": result, "isError": failed}


def dispatch(bridge, message):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in message:
        return None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    method, params = message["method"], message.get("params", {})
    try:
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {"protocolVersion": requested if requested in (PROTOCOL, "2025-06-18", "2025-03-26", "2024-11-05") else PROTOCOL,
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "nadoc-scrywrite", "version": "1.0.0"},
                      "instructions": "Observe first. Use returned session and command_sequence as expected_sequence for actions. Acknowledged input is not a browser commit. Wait on state and verify committed_feature_id. Never retry uncertain mutations blindly."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                name = params.get("name")
                state = bridge.call(name, params.get("arguments", {}))
                result = tool_result(state, capture=name == "scrywrite_capture")
                if name == "scrywrite_capture" and (state.get("capture") or {}).get("status") == "complete":
                    directory = Path(state["capture"]["directory"])
                    if directory.parent != Path(bridge.socket_path).parent:
                        raise ValueError("capture outside session directory")
                    image = directory / "left.png"
                    if image.stat().st_size <= 8 * 1024 * 1024:
                        result["content"].append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(image.read_bytes()).decode("ascii")})
            except (OSError, ValueError, TypeError, KeyError) as error:
                result = tool_result({"error": type(error).__name__, "detail": str(error)})
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
            return response
        response["result"] = result
    except (ValueError, TypeError) as error:
        response["error"] = {"code": -32602, "message": str(error)}
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--socket", help="Pin an absolute private Unix socket path")
    endpoint.add_argument("--state", help="Follow a private backend state file (default: /tmp/nadoc-vr-<uid>.json)")
    parser.add_argument("--trace", help="Optional JSONL command/observation trace")
    args = parser.parse_args()
    bridge = Bridge(args.socket, args.trace, args.state)
    while True:
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line:
            return
        if len(line) > MAX_MESSAGE:
            # Stop rather than interpreting the remainder of an oversized request.
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Request too large"}}), flush=True)
            return
        try:
            message = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            response = dispatch(bridge, message)
        except (ValueError, UnicodeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
