"""Own one loopback server on an OS-assigned port, with a per-launch capability.

The Electron host passes the capability only in request headers. Validation uses
an isolated workspace and disables lifespan (no simulation recovery/autoconnect).
Normal launches retain the existing application lifespan and session persistence.
"""

import argparse
import hmac
import json
import os
from pathlib import Path
import socket

import uvicorn


class LocalCapability:
    def __init__(self, app, token):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            if not hmac.compare_digest(headers.get(b"x-nadoc-desktop", b""), self.token):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send({"type": "http.response.start", "status": 403, "headers": []})
                    await send({"type": "http.response.body", "body": b"Desktop session required"})
                return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--validation", action="store_true")
    args = parser.parse_args()
    token = os.environ.pop("NADOC_DESKTOP_TOKEN", "")
    if len(token) < 32:
        parser.error("Missing desktop session capability")
    args.workspace.mkdir(parents=True, exist_ok=True)
    os.environ["NADOC_WORKSPACE"] = str(args.workspace.resolve())
    if args.validation:
        os.environ["NADOC_DISABLE_SESSION_CACHE"] = "1"
    # Import only after workspace selection. Many routes bind it during import.
    from backend.api.main import app

    @app.get("/api/desktop/ready", include_in_schema=False)
    def ready():
        from backend.core.domain_assignment import native_domains_available
        return {"ready": True, "workspace": str(args.workspace.resolve()), "validation": args.validation,
                "native_domain_acceleration": native_domains_available()}

    # The production static mount is a catch-all. Put the host endpoint before it.
    app.router.routes.insert(0, app.router.routes.pop())

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    print(json.dumps({"event": "desktop-listening", "port": port}), flush=True)
    config = uvicorn.Config(LocalCapability(app, token), host="127.0.0.1", port=port,
                            lifespan="off" if args.validation else "on",
                            timeout_graceful_shutdown=15, log_level="info")
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()
