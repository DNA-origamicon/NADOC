# NICK-ARTIFACT TEST — REFUTED: the +51° is NOT a nick artifact (2026-06-28) — supporting detail

[Topic head](../../project_skip_twist_curvature_sweep.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## NICK-ARTIFACT TEST — REFUTED: the +51° is NOT a nick artifact (2026-06-28)

Counting audit first CONFIRMED there's no definitional mismatch: period-48 places EXACTLY the
literature density — 18 helices × 411 bp at the canonical **10.667 bp/turn** SQ pitch, **150 skips =
1 per 48 bp per helix, staggered** (offsets (i·48)//18). oxDNA genuinely converges to period ~24 = 2×.
Pitch arithmetic: period-48 corrects design 10.667→10.44 bp/turn (≈B-DNA); oxDNA's null (period 24)
→ 10.22 bp/turn — INCONSISTENT with oxDNA2's own intrinsic duplex pitch 10.55 (which alone would need
FEWER skips, null ~period 90). So the excess skip demand is NOT duplex-pitch physics.

Hypothesis tested: oxDNA2's residual +1.3°/step NICK overtwist over the design's 112 mid-helix nicks
accumulates into the spurious +51°. Test (`experiments/exp31.../ligation_test.py`): ligate all 112
co-linear nicks (152→40 strands, geometry + sequence byte-identical — only the nick backbone bonds
change), re-run same 8M-prod CUDA protocol. **RESULT: twist +51.4° → +61.9° (went UP ~20%, curv
1.72→1.28). REFUTED.** Removing nicks did not reduce the twist. Mechanism (now understood): a nick is
a single-backbone break = a point of TORSIONAL COMPLIANCE (relief valve); the nicked structure bleeds
some twist strain off by local swiveling, so ligating STIFFENS the backbone → MORE coherent global
twist, LESS bending. So oxDNA nicks net-RELIEVE global twist, not inflate it — the +1.3°/step is a
local geometric offset, dominated mechanically by the added compliance. → LESSONS-worthy: the "nick
overtwist inflates the bundle twist" intuition is backwards. Artifacts: `results/ligation/
ligation_twist_compare.png` + `ligation_summary.json`.

**CONSEQUENCE:** the +51° is robust real-structure mechanics in oxDNA, NOT a removable preprocessing
artifact. The cheap "ligate-before-measure" fix is OFF the table. Remaining possibilities: (a) real SQ
twist the 48-bp convention underestimates (oxDNA right, convention coarse — publishable), or (b) the
baked-in force-field pitch (10.55) / weave-supertwist artifact (not removable by preprocessing). BOTH
point to the ALL-ATOM MD tiebreaker (exp33 `md_twist_validation`) on the period-48 structure as the
decisive next step — NOT an engine rewrite. If atomistic also shows large residual → oxDNA right; if
~0 → force-field calibration (not "our own oxDNA").
