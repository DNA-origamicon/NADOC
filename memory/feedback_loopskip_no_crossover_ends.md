---
name: feedback_loopskip_no_crossover_ends
description: Auto-generated loops/skips must NOT sit on crossovers or strand ends; manual placement stays allowed.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 00bc527a-d02d-43fe-bfa1-8752f16a0358
---

Automatically-generated loops/skips must **never** be placed on a **crossover
location** or a **strand end** (5′/3′ terminus / nick / helix-end u-turn). A
deletion on a crossover removes the base the strand-jump depends on; a mark on a
terminus is similarly non-physical. Downstream tools (e.g. CanDo) can crash, skip,
or silently mishandle such files.

**Why:** discovered while building the CanDo validation battery ([[project_cando_fem]]).
The twist designs placed uniform skips at bp {0,42,84,126,168} on every helix; because
honeycomb crossovers are periodic too, ~20/30 skips landed on crossovers — and bp 0 is a
terminal u-turn end crossover. Deleting the base a scaffold u-turn sits on is exactly the
kind of thing that breaks a caDNAno→CanDo run.

**How to apply:**
- Any AUTO placement (twist/bend realization `twist_loop_skips` / `bend_loop_skips` /
  `apply_loop_skips_from_deformations`, `sq_lattice_periodic_skips`, headless battery
  generators) must exclude, per helix, every crossover bp AND every strand domain
  endpoint (nicks + termini), plus a small helix-end margin. Twist magnitude is set by the
  per-helix mark COUNT (position-independent), so uniform marks are free to move to
  crossover/end-free interior bps. Bends preserve each helix's net count; relocate only the
  offending marks to the nearest free interior bp (preserves the gradient → the end-to-end
  bend angle).
- **Manual** placement (`POST /design/loop-skip/insert`, the context-menu tool) stays
  UNRESTRICTED — the user may deliberately place a mark anywhere.
- The core realization functions do NOT yet enforce this (flagged follow-up). Until they
  do, battery regeneration uses an explicit off-crossover/off-end placement pass.
