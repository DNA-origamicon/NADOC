---
name: Restore the proven VR path before experimenting
description: Mandatory first read for Vive, SteamVR, Tailscale VR launch, and left-eye dummy troubleshooting; avoid repeating the September 2026 recovery detour.
type: feedback
---

# VR recovery: preserve the established system

On 2026-09-08 the user confirmed the restored `24hb_0xT` physical-headset left-eye
window worked, then explicitly requested safeguards against repeating this session's
"wild goose chase." Recover that implementation, not a new substitute. Confirmation
covers the displayed model/live mirror, not all controller/editing workflows or
future reboot persistence.

## Read and inspect before changing anything

Read [the workstation recovery record](project_steamvr_drm_lease_fix.md),
[the physical mirror contract](../docs/scrywrite_desktop_mirror.md), and, for a
stationary dummy, [existing scene framing](../docs/scrywrite_scene_framing.md).
Inspect current code, process environment, fresh launch logs, and the actual browser
document/host. These are workstation-specific observations, not settings to force
onto every Tailscale host.

The proven stack is NADOC's custom Linux C++ OpenXR companion + SteamVR on NVIDIA
direct mode, with automatically selected GDM X11 on this workstation. ScryWrite
provides existing troubleshooting/framing, not a replacement runtime. August 17/28
successful runs also used X11. Do not invent an X11-free historical runtime, or
dismiss the user's working-history report: recover evidence of what changed.

## Diagnose the failing layer, in order

1. **403 is authorization, not leasing.** Check the browser's Tailscale URL, serving
   backend PID/version, and `NADOC_PUBLIC_URL` / `NADOC_TAILSCALE_IP`. Preserve the
   exact-origin/self-address gate; never allow the whole tailnet or disable it.
   Workspace sync does not redirect VR: the active URL's host needs the headset.
   Launch through the loaded document's browser or exact document header, not
   headerless default state. Verify a source fix is actually loaded by the worker.
2. **Setup dialogs do not prove missing installation.** Check existing launcher
   `cap_sys_nice`, `/usr/sbin` and `/sbin` on PATH, and Conda `LD_LIBRARY_PATH` first.
   Inspect processes/dialogs instead of repeatedly clicking launch. Correct one
   evidenced cause, retry once. For an environment correction, gracefully restart
   Steam itself when safe: an old client retains its environment despite new URLs.
3. **Lease failure needs display AND GPU evidence.** Inspect login session, Vive
   connector/EDID/non-desktop state, and Steam's inherited GPU override. Here Vive
   is on RTX 3080 Ti; `DRI_PRIME=pci-0000_0a_00_0` incorrectly selected AMD. Preserve
   the recorded user-local Steam desktop-entry correction. Process presence or USB
   tracking does not prove acquisition: require fresh compositor `Acquired xlib
   display!`, `Direct mode: enabled`, and successful startup.
4. **Low desktop resolution is separate.** Never reintroduce `AllowHMD "yes"`:
   it made Vive the primary desktop. Preserve Dell layout, EDID-specific guard,
   and NVIDIA's default HMD exclusion. Verify the saved automatic session rather
   than making the user choose Ubuntu on Xorg every login. Session changes/reboots
   require evidence and coordination, not speculation. Xwayland cannot bypass
   the physical display owner's missing lease support.
5. **Slow export is not a failed runtime.** This 24HB snapshot took 59.4 s and
   click-to-first-frame 69.7 s. Inspect export growth/progress before retrying.
6. **Submitted but black can mean the dummy faces away.** Inspect tracking/source,
   pixels, and design coverage. Reuse `--place-scene-in-view on --scene-view mirror
   --scene-orientation front --scene-distance 1.30 --scene-scale 2.0`, plus
   `--mirror-eye left --reference-grid off`. Existing framing waits for 15 stable
   poses and moves presentation into the real eye view, not the headset pose or
   saved design. Normal browser launch does not pass these framing flags. Preserve
   its exact scene/visualization before stopping it for a standalone framed launch;
   do not substitute the default triangle/chiral fixture for the current document.
   `/tmp` exports and old document IDs are ephemeral; regenerate from current state.

## Guardrails and completion evidence

- Use existing `presentSpectatorMirror`, `just vr-hmd-mirror`, or `just scrywrite-frame`.
  Browser screenshots, software projections, scripted actor cameras, and synthetic
  feeds are not the requested physical eye view. Do not develop a replacement.
- `SUBMITTED` is the actual undistorted application eye, not lens-warped compositor
  output or proof of panel scanout. `SPECTATOR FALLBACK` is not submitted-eye evidence.
  `SYNCHRONIZED` alone is not failure; inspect runtime rendering/source rather than
  treating an unworn headset as a broken installation.
- Verify visible model pixels, tracking, advancing frames, and fresh compositor
  evidence, then record user confirmation. Status booleans alone are insufficient.
  Leave one intended viewer, not multiple setup/viewer windows.
- Distinguish browser-managed live editing from a standalone snapshot mirror.
  Explicitly disclose lack of subsequent browser-edit sync for the latter; do not
  silently substitute a snapshot when live editing is requested.
- If the method really is missing, audit VR git history/merges, then relevant
  `~/.codex/session_index.jsonl` and session transcripts for system-only fixes before
  proposing replacement code, runtime reinstall, or another display method. Record
  evidence justifying any deviation from the proven path first.
- Do not restart a user-confirmed working session just to update memory. Still open:
  another login/reboot has not tested the final root-config/Steam-launcher persistence.
