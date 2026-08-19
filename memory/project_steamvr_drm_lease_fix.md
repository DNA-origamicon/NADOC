---
name: project_steamvr_drm_lease_fix
description: "SteamVR CannotDRMLeaseDisplay on this workstation — root cause, the fix, and where it now lives in code"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1b7b3467-7fea-49a3-9a58-e4599fce864f
  modified: 2026-08-19T01:36:43.966Z
---

On Joshua's Vive workstation, SteamVR's compositor fails `xrCreateSession` with
`CannotDRMLeaseDisplay` (log shows "Failed to acquire xlib display" / "VR requires direct mode")
whenever the Vive's `HDMI-0` output is live as an ordinary GNOME/X desktop monitor. The Vive's EDID
does not self-report as non-desktop, so X won't release the connector for SteamVR's DRM lease even
though tracking (lighthouse/basestations/controllers) works fine over USB independently.

**Fix:** `xrandr --output HDMI-0 --set non-desktop 1 --off`. This is **session-local** — it resets
on every connector re-link (headset standby/wake, replug, X logout), so running it once by hand does
not stick across a new session or the next day.

**Why:** discovered by reading a prior Codex CLI session transcript at
`~/.codex/sessions/2026/08/17/rollout-2026-08-17T17-20-27-01a01206-....jsonl` (found via
`~/.codex/session_index.jsonl`, thread "Assess seamless VR support") — Codex diagnosed and applied
this exact command live but explicitly flagged it as session-only. It reappeared the next day
because the property never persisted, not because of any hardware change or repo regression.

**How to apply:** as of 2026-08-18 this is baked into `backend/api/routes_vr.py` —
`_detach_hmd_from_desktop()` runs unconditionally at the top of `_start_steamvr()`, before the
already-running early-return. This matters: an earlier version gated it behind "SteamVR not already
running," which meant it silently never fired whenever SteamVR was already up from a prior, possibly
failed attempt — exactly the case that needed it. See
[[project_native_vr]] (repo `memory/project_native_vr.md`, "Workstation VR runtime gotcha" section)
for the full writeup kept with the codebase.

**Also watch for:** `just dev` runs uvicorn with `--reload-dir backend`, which is supposed to hot
-reload on edits to this file. Observed once not to fire — the worker process kept its original PID
a full day after the edit landed. Before trusting a code fix here is live, check
`ps -o pid,lstart -p <uvicorn worker pid>` against the file's mtime, not just that the edit was
saved.

**The launch env is a two-sided constraint (learned the hard way, 2026-08-18).** Sanitizing the
environment to drop conda's `LD_LIBRARY_PATH` (needed — it shadows SteamVR's bundled Qt5 and kills
`vrmonitor`) by hardcoding `PATH=/usr/local/bin:/usr/bin:/bin` *introduced a new bug*: Valve's
`vrsetup.sh` runs `command -v getcap` (it lives in `/usr/sbin`), and without it raises a **blocking
zenity dialog** that stalls the whole launch until a human clicks it. Keep `/usr/sbin` and `/sbin` on
PATH. Both constraints are locked by tests in `tests/test_vr_routes.py`.

**Steam caches its environment.** `steam steam://rungameid/250820` against an already-running client
just hands it the URL — the old client keeps its old env, so an env fix appears not to work. Fully
kill Steam before retesting, and verify with
`tr '\0' '\n' < /proc/$(pgrep -f steam-runtime-launcher-service)/environ | grep ^PATH=`.

**`SYNCHRONIZED` is healthy, not stuck.** The viewer sits in `XR_SESSION_STATE_SYNCHRONIZED` while
the headset isn't being worn; it only reaches `VISIBLE`/`FOCUSED` when someone puts it on (Vive
proximity sensor). The genuine failure signature is `STOPPING`/`EXITING` within seconds of start.

**Don't conflate with:** a genuinely disconnected `HDMI-0` (`xrandr --query` shows no mode line at
all, not just "not part of the desktop") — that's the headset being idle/asleep or a cable/link
problem, and no xrandr property fixes a connector with no live signal. Check `xrandr --query | grep
-A1 HDMI-0` first to tell the two apart before assuming this fix regressed.

**General lesson:** when the user says "this exact thing was fixed before, go find how," and it's
not in `git log` or `bash_history`, check `~/.codex/session_index.jsonl` and
`~/.codex/sessions/**/*.jsonl` for prior Codex CLI sessions on this machine — they're a real record
of system-level fixes (not just repo edits) that never get committed anywhere else.
