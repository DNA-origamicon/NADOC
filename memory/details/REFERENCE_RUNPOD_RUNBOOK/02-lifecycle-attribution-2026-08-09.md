# Lifecycle attribution (2026-08-09) — supporting detail

[Topic head](../../REFERENCE_RUNPOD_RUNBOOK.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Lifecycle attribution (2026-08-09)

NADOC appends every app-managed creation and termination transition to
`workspace/.runpod_lifecycle.jsonl` (mode `0600`). A termination is recorded *before* the
DELETE request and then as succeeded, already absent, or failed. Records include pod id,
job id when known, reason, provider deadline, and timestamp. This ledger survives the pod,
whose provider lifecycle fields disappear from the API after deletion.

When a recorded pod is absent from RunPod, NADOC now pauses the job, retains its last pod
id, and writes `pod_observed_missing` with one of three attributions:

- `nadoc_delete`: a matching `terminate_requested` record exists, including its reason;
- `external_or_unknown` with creation coverage: NADOC observed creation but issued no
  DELETE, so provider/host or account-side action is the likely cause;
- `external_or_unknown` without creation coverage: legacy pod, therefore inconclusive.

Disappearance no longer automatically rents another pod. Checkpoints remain on the network
volume and Resume requires fresh user authority, preventing an infrastructure loop from
spending the full budget once per replacement.

This happened: a transient DNS blip (`Temporary failure in name resolution`) on a routine
poll killed the launcher. `_request` now retries transient/5xx/429 (never 4xx). And the pod
id is now **persisted the instant it exists** — it wasn't, so the orphan could not even be
*named*, let alone reaped.

**Finish every run with `reap.py` and confirm `0 pods`.** Anything on the account is billing.

---

## 5. The failure catalogue — 11 bugs, 9 silent

| # | bug | how it presented | fix |
|---|---|---|---|
| 1 | `early_stop_relax` was a **no-op** on runpod | flag settable; nothing read it | port slurm's bridge emitters |
| 2 | Tier B may not skip k<0.1 — **half the ladder** | "early-stop is on" | Tier A mandatory |
| 3 | **`fast=True` silently disabled early-stop** | accelerator ran, always answered HOLD | `_output_freq` from chunk length |
| 4 | `cell_shrink` retry re-read the **ORIGINAL** box | "self-healing, bounded retry" = *fails 4×* | `remote_resume_conf.py` |
| 5 | **late** cell-shrink starves a resumed chunk of frames | as #3, different trigger | recompute cadence from REMAINING steps |
| 6 | `GPU_TYPES` held **community** prices in a secure-only world | estimates ~2.2× low | live-checked secure prices |
| 7 | production child dropped `archive_path` | trajectory → 20 GB system disk | inherit from parent |
| 8 | DNS blip **orphaned a billing pod** | pod unnameable, unkillable | retry + persist pod id |
| 9 | **the spend ledger FROZE** while a GPU billed | total stuck at $0.95; true $1.35 | collapse rows per pod |
| 10 | supervisor saved the job **before** deciding its status | finished ladder recorded as "running" | save AFTER deciding |
| 11 | `reap.py` didn't close the ledger | a destroyed pod accrued forever | close on reap |

**Only #4 announced itself.** Every other one was code that passed its tests and was
documented as working.

**Patterns to carry forward:**
- **Any step-denominated cadence is a latent bug the moment the timestep becomes a
  variable.** (#3, #5 — the same bug twice, from different triggers.)
- **A safety net can have the same hole as the thing it protects.** The spend ledger existed
  *because* the kill-switch had no memory — then it under-reported. **A ledger that
  under-reports is worse than no ledger, because it is trusted.** (#9)
- **A documented "self-healing"/"fail-safe" behaviour is worthless until something has
  watched it heal.** (#2, #3, #4)
- **Persist state the instant it exists, not when convenient.** (#8, #10)

---
