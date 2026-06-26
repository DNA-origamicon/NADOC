---
name: Helical phase constants — locked, no changes without approval
description: Phase constants (_PHASE_FORWARD, _PHASE_REVERSE, _SQ_PHASE_FORWARD, _SQ_PHASE_REVERSE) must never be changed without explicit user approval
type: feedback
originSessionId: b8a5dca6-8e5d-4d81-b1a6-8bc73570a376
---
Never change the helical phase offset constants in cadnano.py, scadnano.py, or any other importer/lattice file without explicit approval and request from the user.

Affected constants:
- `_PHASE_FORWARD` / `_PHASE_REVERSE` (HC, both importers)
- `_SQ_PHASE_FORWARD` / `_SQ_PHASE_REVERSE` (SQ, both importers)
- Any equivalent in `lattice.py` (`_lattice_phase_offset` etc.)

**Why:** Phase constants affect every downstream system simultaneously: 3D crossover arc routing, atomistic template alignment, FEM pre-stress, XPBD constraints, and visual display. A change that appears to fix one metric (e.g. crossover arc backbone distances) silently breaks many others. The values are the result of deliberate multi-system calibration decisions the user owns.

**How to apply:** If analysis suggests a phase is "wrong" (e.g. crossover distances are large), do NOT propose or implement a phase change. Document the observation, note it as an open question, and wait for the user to explicitly authorise a change. This rule applies even if the geometric argument for changing a phase seems airtight.
