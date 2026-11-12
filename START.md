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

The launchers use `uvicorn server_bootstrap:create_app --factory`. This dedicated
process factory collects import temporaries and freezes the permanent startup
object graph before lifespan or requests begin, reducing full-GC publication
pauses. Later session and job objects remain normally collectible. Direct app
imports remain inert; use this factory for manually started servers too. Changes
to `server_bootstrap.py` take effect on the next normal server start.

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

Native VR is also available from that computer's printed Tailscale URL. It still
launches SteamVR and the native viewer on the NADOC host whose URL is open, not on
another paired workspace host. Other Tailscale origins remain unable to call the
host-local VR bridge, and the launcher admits only this computer's own Tailscale
address to the native companion endpoints.

On the Vive workstation, the `jojo` account's saved Ubuntu session is X11 because
GNOME 46 Wayland does not expose the `wp_drm_lease_device_v1` protocol SteamVR
needs to lease the headset connector. Normal sign-in uses that saved session; no
login-screen session choice is required. If an OS update resets the saved session
to generic `ubuntu`, restore `Session=ubuntu-xorg` and `SessionType=x11` through
AccountsService, sign out and back in, then start NADOC. Headless ScryWrite
validation remains available in either session.

For a new hosting computer, follow [internet-sharing prerequisites](docs/sharing_host_setup.md).
The editor server starts its public viewer connection and DNS/HTTPS checks in the
background, before a design is shared. **Enable link** activates guest access once
that connection is ready. Ending a presentation keeps the connection available. No separate setup button or Node command is required;
`node scripts/setup_sharing.mjs --check --browser` is an optional diagnostic.

**File → Sharing…** creates a temporary guest-viewer invitation from localhost or
this host's configured private Tailscale editor URL. Guests use a browser and the
invitation password; they do not need Tailscale. On a fresh checkout, the first
hosting request builds the guest viewer automatically. Hosting selects a free
supported HTTPS port (443, 8443, then 10000), preserving existing private services.

Both computers must be paired once from **Help → Tailscale Workspace Setup**.
Saved Tailscale HTTP/IP peers are upgraded automatically to HTTPS MagicDNS when
the updated remote server is detected. If an unusually configured legacy peer
does not upgrade, remove it and pair the computers again.

## Test scratch on different machines

No hostname or Archive disk is required for ordinary tests. The history-preview
launcher defaults to the OS temporary directory, checks at least 1 GiB free and
actual write access, then allocates a unique disposable directory. It redirects
workspace saves, profiles, downloads and caches there; cleanup follows process
shutdown on both success and failure. Use the project Python environment:

```bash
just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage
just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py
```

The first command checks storage without launching services/browser. The second
runs only the two history cases; it is not full release qualification. No browser
installation/download is performed automatically.

For a different scratch location, set `NADOC_TEST_SCRATCH_ROOT` to an existing
absolute directory in your local shell/CI configuration. Do not commit a personal
path. Explicit unavailable destinations fail; they never silently fall back.
The previous `NADOC_HISTORY_E2E_OUTPUT_PARENT` is an alias; conflicting values refuse.

On the original space-constrained workstation, configure both root and required
mount (example only; verify the existing directory on that machine):

```bash
export NADOC_TEST_SCRATCH_ROOT=/media/jojo/Archive/NADOC_archive/runtime/development-artifacts
export NADOC_TEST_SCRATCH_MOUNT=/media/jojo/Archive
```

On this ample-space machine or CI, neither setting is necessary. A configured
mount must be mounted and contain the resolved scratch root on the same filesystem.
Do not create an unmounted path, alter user data, or move old artifacts implicitly.

Other test/native tools retain their own configuration: set `TMPDIR` (and Windows
`TEMP`/`TMP`) or the tool's explicit scratch option before starting them. The new
variables are consumed by the history launcher, not automatically by every legacy
script. Its free-space check is not a continuous quota; budget large campaigns
separately. Shell resource guards retain their current platform support; portable
storage/process APIs do not imply Windows/macOS end-to-end qualification.

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

### Shared design repository

For an independent Git-synchronized folder selectable in the Library, initialize
the first machine from the NADOC checkout:

```bash
python scripts/setup_shared_design_workspace.py
```

This creates `workspace/Shared Designs` (or beneath `NADOC_WORKSPACE`) without
changing existing designs, committing, or connecting a remote. It refuses an
existing folder. Follow its [README](scripts/shared_design_workspace/README.md)
to connect a private remote and clone into the same workspace-relative location
on the second machine. The folder is an ordinary Library entry, not a separate
server tab or an automatic background synchronization service.

The outer repository continues to ignore `workspace/`; the inner repository has
its own Git history. Keep portable native parts/assemblies, construction process,
required inputs and compact reports there. Simulation jobs remain local. A clean
`git pull --ff-only` transfers saved inputs; receiving-engine preparation and
provenance checks still determine whether a design is usable for simulation.

### Application code

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
