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

Older WSL2 doesn't forward `localhost`. Get the current address instead:

```bash
ip addr show eth0 | grep 'inet '
```

Open `http://<that-number>:5173`.

**Permanent fix (Windows 11):** create `C:\Users\<you>\.wslconfig` with

```ini
[wsl2]
networkingMode=mirrored
```

then run `wsl --shutdown` in PowerShell and reopen Ubuntu. `localhost` works
from then on.
