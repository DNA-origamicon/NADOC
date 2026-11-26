---
name: Review every new UI against NADOC style
description: Mandatory visual review of colors, typography, spacing, controls and visibility before delivering new UI.
type: feedback
status: active
authority: canonical
---

# Review every new UI against NADOC style

User instruction, November 25, 2026: every new UI must be reviewed for proper
coloring, font, spacing, visibility, and overall match with existing NADOC style.
Apply this to buttons, number/text boxes, dialogs, and all other new surfaces;
do not wait for the user to request a styling correction.

Reuse the shared tokens in `frontend/src/styles/tokens.css`, component classes
in `components.css`, and established UI primitives. Avoid bespoke hardcoded
palettes and unstyled browser controls. Review primary/secondary/destructive
buttons, readable input values and labels, focus/hover/disabled/error states,
consistent typography and spacing, alignment, contrast, and viewport fit.

Inspect the rendered UI in every host where it appears (including 3D and cadnano
for shared dialogs), at normal viewing size and a constrained viewport. A unit
test pass alone does not establish visual consistency or visibility. Correct
mismatches before delivery and report any unverified visual boundary explicitly.
