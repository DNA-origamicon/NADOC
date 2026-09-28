# Native VR style and trackpad focus — 2026-09-27

Research and asset references are recorded in [the UI standard](../vr_ui_style.md).
The implementation adds shared sidebar style tokens, soft light text, an inset
hover/focus border, brief accepted-click feedback and haptics. Detailed native
menus also show a focus border. No external assets or SDKs were installed.

Menu-open trackpad clicks now control that hand's menu. Top/bottom moves focus,
left/right switches sidebar tabs (or steps detailed controls), and trigger
activates. Center-click explicitly returns to pointing. Alternatively, move off
the target present at the last trackpad click and hold a ray over one target for
450 ms. Both sidebars participate in resting-ray protection. A held trigger
blocks handoff. Gray controls stay focusable and inert. The radial Tools shortcut
remains available with the right menu closed, matching the user's choice.

During review, the older Tools panel was found to activate an unsupported gray
Move/Rotate entry. It now rejects that activation and exports its disabled state;
its witness examples expect Inspect to remain active. Tool choices that require
settings remain available through the existing configuration path.

The new ScryWrite `trackpad_axis` operation supplies direction to an ordinary
trackpad click; it does not directly change menu state. Native focus and pointer
input use the production activation paths.

## Verification

Initial steady-fast testing passed before the four-profile runs. Subsequent
iterations added opposite-panel resting-ray protection, preservation of focus
when the other menu toggles, suppression of physical touch scrolling during
focus navigation, and the detailed-menu disabled guard. Evidence from each run
is retained under `.development-artifacts/vr-ui-focus/`.

Final evidence: [verified](../../.development-artifacts/vr-ui-focus/verified/).
The focus runner checks both hands, gray controls, paging without pointing,
explicit center exit, noisy pointer handoff, resting-ray protection, detailed
Tools activation and independent menu ownership. Stereo pixel checks verify text,
disabled styling, selection styling and the amber focus cue. The desktop check
compares the actual owned X11 client to the submitted-eye mirror.

This is focused interaction coverage, not another exhaustive 851-control tour.
The previous full catalog audit remains [separate](vr_sidebars_20260927.md).
Physical headset comfort, haptic strength and the preferred dwell duration still
require a hand-driven check; they are recorded in `manual_validation_debt.md`.
Continuous trajectory dragging and desktop mouse pointing are not converted into
stepwise controls. The existing detailed panels retain their controller-relative
placement and can appear tilted in diagnostic captures.

Reproduce:

```sh
just vr-menu-tour --focus-checks --validate --hold 0 --exit
```

Final results: all four presets passed every focus check. Each pointer handoff
needed one additional reach (two attempts); no motion parameters or thresholds
were changed. The actual desktop comparison matched 99.04% of tested feature
pixels, above the existing 95% threshold. Native CTest: 37/37; focused live-bridge
Python tests: 20/20; pixel-oracle negative tests: 3/3. Ruff, catalog drift and diff
whitespace checks passed. All owned viewers exited and temporary sockets were
removed; review artifacts remain under `.development-artifacts/vr-ui-focus/`.
