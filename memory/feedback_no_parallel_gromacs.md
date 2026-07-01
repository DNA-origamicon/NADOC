---
name: Never run GROMACS jobs in parallel; always leave 4 threads free (Compy5000)
description: Serial GROMACS only; cap ntomp at 28 (32 total − 4 reserved) on this 32-thread machine
type: feedback
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---
⚠️ CRITICAL — Compy5000 has 32 threads. ALWAYS use `-ntomp 28` (never 32) so 4 threads remain free for user tasks. This applies to every mdrun call in every run script, MDP template, and ad-hoc command on this machine.

Never launch multiple `gmx mdrun` calls in parallel (e.g. via `&` or simultaneous Bash calls).

**Why:** User explicitly requires ≥4 threads free at all times for interactive work. Parallel GROMACS runs also compete for CPU/GPU and are slower than serial.

**How to apply:**
- All `gmx mdrun` calls: `-ntmpi 1 -ntomp 28` (not 32)
- EM: `-nb gpu` only (no `-pme gpu` for steep integrator)
- NVT/NPT/production: `-nb gpu -pme gpu -bonded gpu`
- Run serially, never in parallel
- When generating run.sh templates in md_setup.py or any script, hardcode `-ntomp 28`
