---
type: feedback
status: active
authority: canonical
---

# Keep development artifacts out of the user workspace

User instruction (2026-09-15): delete development/test artifacts after use, or,
when they serve a continuing purpose, retain them without cluttering the main
user workspace.

- Default development simulations, benchmarks, review designs and scratch jobs to
  an isolated experiment workspace such as `experiments/<topic>/ws/` (gitignored),
  or a temporary directory with failure-safe cleanup. Do not default to `workspace/`
  or its live job catalog for development verification.
- Keep reproducible scripts and compact evidence in the appropriate experiment or
  documentation directory. Retain large outputs only for a stated purpose, such
  as an unresolved failure investigation; document their location and purpose.
- Before finishing, remove disposable outputs, including failed and duplicate
  attempts. Verify that test-created parts and job folders no longer clutter the
  user workspace. Preserve user-authored files and unrelated sessions' artifacts.
- When moving retained evidence, update current documentation and script defaults.
  Historical input/log paths may remain unchanged as provenance; label them as
  historical rather than implying relocated job packages are directly runnable.

Mobile-gold validation evidence is retained in `experiments/mobile_gold/ws/` to
investigate pairing loss. Compact results live in `docs/validation/`; the cleanup
manifest in the isolated workspace records moved and deleted paths.
