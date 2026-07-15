---
name: feedback_runpod_downloads_to_archive
description: Everything downloaded from RunPod (trajectories, checkpoints) must land on the archive media, not the system disk. The main drive is space-constrained.
type: feedback
---

**Anything fetched from RunPod goes on the archive media `/media/jojo/Archive`, never the
system disk `/` (`/dev/sda2`).** The main drive is small and runs near-full (measured
2026-07-14: 218 G, ~92% used, ~16 G free); the archive is 7.3 T with terabytes free.

**Why:** a 1.9 M-atom production DCD is ~700 MB; a full ladder + production is multi-GB. One
run misdirected to `/` would fill it overnight and wedge the machine. This is RunPod-runbook
bug #7 (a production child that dropped `archive_path` and sent its trajectory to the 20 G
system disk) as a standing operational rule.

**How to apply:**
- Every MD job that will run on RunPod is created `archived=True` with
  `archive_path=/media/jojo/Archive/nadoc_jobs/<job_id>`, so `job_dir()` resolves to the
  archive from the first byte — prep, staging, fetch, and any production child all land
  there. `prep_24hb.py` / `prep_3x6x400.py` already do this; keep it.
- After any fetch, verify the landing path starts with `/media/jojo/Archive`
  (`MdJob.load(id).job_dir(...)`), and that nothing large appeared under `/` or `~`.
- **Local test scratch is also on the system disk** (`/tmp` → `/dev/sda2`). Big local NAMD
  tests (HMR PSFs are ~180 MB each; checkpoints ~30 MB) accumulate there — clean up finished
  experiments' artifacts rather than let them sit at 92% full.
- Fetch is billed GPU time and re-downloads whole files (a resume re-pulls the entire DCD,
  not just new frames). Prefer fetching the final checkpoint (~140 MB); DCDs persist on the
  network volume and can be pulled once at the end. See [[REFERENCE_RUNPOD_RUNBOOK]] §1/§6.
