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
