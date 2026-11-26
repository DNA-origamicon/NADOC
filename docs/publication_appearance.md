# Source figure appearance in reconstructed designs

The publication compiler preserves two independent presentation observations:

- Staple color comes from the actual PDF route stroke (converted to RGB hex).
  When a route is recovered only from the table, its nominal table color is
  mapped to the figure palette only when all observed examples of that table
  color agree. Otherwise the original table color is retained as an explicit
  fallback. No color evidence is used to assert a molecular route.
- Helix rows follow the top-to-bottom row centers in the orientation-normalized
  figure. The ordinary `helix-reorder` command freezes existing visible labels
  before changing display order. Lattice cells, polarity and molecular positions
  are unchanged. Auxiliary tracks sharing a source row retain a stable order.

Color assignments are recorded with the final staple sequence/metadata commands,
so precursor splitting and crossover joining cannot replace them with automatic
palette colors. Appearance evidence is included in the reconstruction report;
saved-design comparison checks every color and the complete helix order.

## D009

Figure S6, supplement PDF page 6, orders the helices as:
45–34 descending, 16–21 ascending, 0–15 ascending, 33–22 descending.
All 187 drawn staple colors are preserved. The seven sequence-inferred staples
use the uniquely observed figure palette for their table colors.

The marks on helices 30 and 42 at base 119 are **39-base insertions**, not
skips: native `loop_skips` stores `delta: +39` on both. The source figure has a
loop symbol and visible “39” at each location. The algorithm detected the glyph
positions and recovered the two insertion lengths by bounded flanking-sequence
search; visual inspection of the printed labels independently confirms them.
See the source crops in `workspace/Shared Designs/.provenance/D009/`.

Validation: 23 focused backend tests passed. The running-app check opened D009
from the welcome screen and used the normal Origami Editor button; all 194
colors, 46 row labels/order, and both +39 insertion records matched. Saved
browser output passed independent replay and source comparison. Temporary
workspace/configuration cleanup passed; no main.js changes were needed.
