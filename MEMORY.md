# NADOC Memory — moved

**The memory index lives at [`memory/MEMORY.md`](memory/MEMORY.md).** Read that one.

This file used to be a second, competing index. It listed only two entries, and it was the
*sole* pointer to them — which is exactly why both drifted out of the real index and went
unmaintained. Both are now indexed properly in `memory/MEMORY.md`:

- `memory/project_periodic_md.md` (renamed from `periodic_md.md`) — periodic unit-cell MD:
  21 bp honeycomb repeats, wrap bonds across axial PBC, explicit solvent, NAMD pressure/box
  handling. Next-milestone plan: `docs/periodic_md_restraint_ramp_plan.md`.
- `memory/architecture_decisions.md` — binding cross-cutting laws (DTP-PMD-1/2).

Kept as a redirect so nothing linking to `MEMORY.md` at the repo root dead-ends.
Safe to delete once you're confident nothing references it.
