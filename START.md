# NADOC — Quick Start

## Every session

Two terminals in WSL2, from `/home/joshua/NADOC`:

```bash
# Terminal 1 — backend
export PATH="$HOME/.local/bin:$PATH"
just dev

# Terminal 2 — frontend
export PATH="$HOME/.local/bin:$PATH"
just frontend
```

Then open in browser: **http://172.24.31.208:5173**

---

## If that IP doesn't work

The WSL2 IP changes on reboot. Get the current one:

```bash
ip addr show eth0 | grep 'inet '
```

---

## Permanent fix (localhost:5173 forever)

Create `C:\Users\joshua\.wslconfig` with:

```ini
[wsl2]
networkingMode=mirrored
```

Then in PowerShell: `wsl --shutdown`, reopen terminals.
After that, use **http://localhost:5173** instead.

Requires Windows 11 22H2 or later.
