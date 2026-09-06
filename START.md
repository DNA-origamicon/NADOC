# NADOC — Quick Start

**First time here?** Follow [INSTALL.md](INSTALL.md) — it walks you through
everything from scratch (Windows/WSL2, macOS, or Linux).

---

## Run it (one command)

From the `NADOC` folder:

```bash
./start.sh
```

Then open **http://localhost:5173** in your browser. Press **Ctrl-C** in the
terminal to stop.

Backend Python edits reload automatically when using `./start.sh`, including
Tailscale mode. Only `backend/` and `scripts/` are watched; workspace saves do not
trigger restarts. Open designs recover through the session cache. Use
`NADOC_RELOAD=0 ./start.sh` to disable backend reload. Frontend edits continue to
reload through Vite.

## Use NADOC across the two Tailscale computers

Run this on each computer whose workspace should be available:

```bash
./start.sh --tailscale
```

NADOC itself remains bound to localhost. The launcher publishes it privately
through Tailscale Serve using a URL like:

```text
https://computer-name.your-tailnet.ts.net:5173
```

Open the URL printed by the launcher for the computer you want to use as the
active host. The welcome Library always keeps **This computer** available. A
paired computer appears as a separate server tab and is refreshed automatically;
it can be offline without affecting local work and becomes selectable shortly
after its own NADOC server starts.

Both computers must be paired once from **Help → Tailscale Workspace Setup**.
Saved Tailscale HTTP/IP peers are upgraded automatically to HTTPS MagicDNS when
the updated remote server is detected. If an unusually configured legacy peer
does not upgrade, remove it and pair the computers again.

## Run it (two terminals, if you prefer separate logs)

```bash
just dev        # terminal 1 — backend  (port 8000)
just frontend   # terminal 2 — frontend (port 5173)
```

---

## Windows/WSL2: if `localhost:5173` doesn't load

Older WSL2 doesn't forward `localhost`. First try the permanent mirrored-networking
fix below. If that is unavailable and you must use the WSL virtual-machine address,
start NADOC with the explicit trusted-LAN opt-in:

```bash
./start.sh --lan
ip addr show eth0 | grep 'inet '
```

Open `http://<that-number>:5173`.

`--lan` exposes NADOC's file, process, simulation, and cloud-control APIs to other
devices that can reach that address. NADOC has no multi-user authentication, so use
this mode only on a trusted private network and stop it when finished. Normal
`./start.sh`, `just dev`, and `just frontend` bind to loopback only.

**Permanent fix (Windows 11):** create `C:\Users\<you>\.wslconfig` with

```ini
[wsl2]
networkingMode=mirrored
```

then run `wsl --shutdown` in PowerShell and reopen Ubuntu. `localhost` works
from then on.

## Moving between the two development computers

This is a human-operated synchronization procedure, not an automatic agent action.

Before starting work, first make sure no other session has uncommitted changes, then run:

```bash
git status
git pull --rebase origin master
```

When intentionally publishing completed work:

```bash
git status
git push origin master
```

If the tree is dirty or a push is rejected, stop and reconcile deliberately. Do not use
`git stash`, destructive restore/reset commands, or force-push in the shared worktree.
