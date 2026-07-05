# exp41 (G4) — 1×N single-layer: the twist-degeneracy special case

Hypothesis: a single row of helices is colinear in cross-section → twist ill-defined → the code needs
a degeneracy guard + bend-only fallback.

## Findings — hypothesis REFUTED (a robustness win)
| section | rank (sv1,sv2) | colinear | twist measure | autorefine twist | marks |
|---|---|:--:|--:|--:|--:|
| 1×4 | (5.0, 0.0) | yes | 67.9° | 67.9 → **1.5°** | 20 |
| 1×6 | (9.4, 0.0) | yes | 68.8° | 68.8 → **1.5°** | 30 |
| 1×8 | (14.6, 0.0) | yes | 69.2° | 69.2 → **1.5°** | 40 |
| 2×4 | (7.1, 3.2) | no  | 40.5° | 40.5 → **0.8°** | 40 |

- The 1×N cross-section IS rank-1 colinear (sv₂ = 0), BUT `measure_bundle_twist` does NOT break — it
  returns a sensible value by tracking the row-line's rotation, which IS the ribbon's helicoid twist
  (a genuine physical DOF for a single-layer sheet). Accumulated per-slab steps are small → no aliasing.
- The current square autorefine (twist objective) **works correctly on 1×N**: twist 68°→1.5° with
  skips, converged, no crash, no sign-confusion. Marks placed off crossovers/ends.
- 2×N (rank 2) is fully non-degenerate — twist 40.5°→0.8°.

## Conclusion
**No twist-degeneracy guard is needed** — the pipeline handles single-layer ribbons correctly; the
generalization is simpler than planned. One documented caveat (untested, not a blocker): a perfectly
symmetric colinear ribbon has a mirror symmetry, so for a design with an INTENDED NON-ZERO twist the
measured sign could be frame-arbitrary. Nulling twist to 0 (the common case) is unaffected. Thin
ribbons also carry large bend (1×4 bend 10.7°) — bend-target designs on 1×N are future work.
