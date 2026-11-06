# Staple temperature view

The view-strip button beside Length cycles **off → domain Tm → total staple
Tfold → off** in both the 3D and cadnano editors. This is a read-only, transient
heatmap of the active part: Full/Beads in 3D and the path canvas in cadnano. It
never writes sequence, routing, geometry, or feature history. Length and temperature heatmaps are mutually exclusive. Colors default to a
20–90 °C blue-to-red scale; the legend reports the actual numeric range
(including values beyond the color limits) and number of unavailable estimates.
The legend provides lower/upper °C inputs, draggable bounds (also adjustable with
arrow keys), and Reset full range, following the flex-map controls. Values outside
the selected interval saturate at the endpoint colors. Reset uses the active
mode’s estimated data minimum/maximum; it is disabled when no estimates exist.
Bounds are transient, independent per editor, and retained across mode/off toggles.
Changing the window only recolors cached estimates; it never changes the reported
physical temperatures or recomputes thermodynamics. Reversed numeric bounds are
ordered, blank/nonfinite entries are rejected, and a positive interval is enforced.
Gray is unavailable, not a low temperature. Scaffold/reference strands retain
their existing colors. The original colors return when the overlay is disabled.

## Conditions and interpretation

Both calculations assume **10 mM free Mg²⁺, 200 nM free staple**, staple excess,
no added monovalent salt/Tris and no chelator. MgCl₂ supplies the specified Mg²⁺.
Scaffold concentration was not specified: the dilute-scaffold approximation
uses 200 nM directly rather than silently assuming an equimolar duplex or a
particular scaffold concentration. EDTA or a specified buffer would require a
free-ion correction. Temperatures are equilibrium estimates, not predictions of
annealing kinetics, folding order, hysteresis, or whole-origami melting.

Domain Tm uses SantaLucia & Hicks (2004), Table 1 (initiation, terminal AT,
and nearest-neighbor terms), with the excess-staple concentration term R ln C.
The Owczarzy (2008) Eq. 16 Mg-dominated correction acts on **inverse Kelvin**.
No symmetry correction is applied: these are staple–scaffold duplexes, not
free self-complementary oligos. Domains require an assigned ACGT sequence of at
least two bases and scaffold coverage; a known scaffold mismatch is unavailable.

Total Tfold implements the model from **Design principles for accurate folding
of DNA origami**, PNAS (2024), as specified in pyOrigamiBreak: sum independent
duplex enthalpies and salt-corrected entropies, add one binding concentration
entropy per staple and one loop-closure entropy between consecutive binding
domain centers, then calculate ΔH/ΔS − 273.15. There is no artificial nearest-
neighbor stack across a crossover. Its Dunn (2015) salt entropy correction is
0.368(N−1) ln(3.3√[Mg²⁺]) cal mol⁻¹ K⁻¹ for the specified zero-Tris conditions;
this differs from the domain-mode Owczarzy correction. A one-domain total
therefore need not equal its domain Tm.

Loop closure uses ssDNA contour length 0.6 nm/nt and persistence length 0.9 nm,
the worm-like-chain mean-square end distance, and the Gaussian effective local
concentration from pyOrigamiBreak. Loop distance is the shortest contour distance
between domain centers on **each staple’s own circular scaffold**, as explicitly
chosen by the user on November 5, 2026, including secondary scaffolds. Every
active scaffold has its own contour length and sequence-start origin. Domain
centers are unwrapped across that scaffold’s nick before averaging. Reordering
scaffolds does not change the estimates; reference scaffolds are excluded. Loop/skip copies and scaffold
junction inserts contribute to contour indexing via the existing sequence
projection. Partner-copy ordering matches `strand_partner_bases`.

## Limits

The literature offers multiple models, not a universal consensus whole-staple
Tm. The user selected this origami-specific Tfold model. It does not include
inter-staple coaxial stacking, competing secondary structure, off-target binding,
heat-capacity corrections, or a folding-state-dependent scaffold loop network.

Terminal unpaired overhang domains are excluded from whole-staple binding energy.
Circular staples, internal unpaired domains, binder domains, staple junction
insertions, missing/mismatched sequences, discontinuous scaffold coverage and
staples bridging distinct scaffold molecules have no total estimate. Staples
confined to any one active scaffold receive the same calculation. A bridge
between molecules is not treated as intramolecular loop closure; that would
require an additional intermolecular binding model and scaffold concentrations.
Ambiguous overlapping scaffold occupancy is unavailable rather than resolved
by document order.
Terminal extension energetics are not modeled. Unknown values are never filled
with default GC content or a concatenated-duplex approximation.

The 3D heatmap addresses nucleotide entries in Full/Beads part views. Cylinders,
atomistic/surface and simulation representations report the availability message.
The native VR button panel does not offer this desktop temperature control;
its quantitative legend is not part of that panel.
Assembly mode also reports that message: this calculation is defined for the
individual circular scaffolds of a part, not an assembly-wide scaffold or
polymerized staple. It does not infer new assembly connectivity or flatten a
polymerized assembly to manufacture a temperature prediction.

## Cadnano editor

The same button beside Length uses the editor's independent `viewTools` state.
The model, adjustable Celsius scale, legend markup, conditions and unknown-value
counts are shared with the 3D view. Domain bodies and end caps get their own
estimates; total mode colors the entire staple, including its connecting arcs.
In domain mode a crossover uses its endpoint domain's color; unpaired connectors
and tails without a domain estimate are gray. Selection highlighting retains
priority. Off returns to the ordinary component palette; Length and temperature
remain mutually exclusive. Immutable-design caching avoids recalculating
thermodynamics on pan/zoom, and edits/history changes invalidate estimates.
Periodic mirror passes and the zoom-scope lens use the same drawing path.

## Sources and validation

- [SantaLucia & Hicks 2004](https://doi.org/10.1146/annurev.biophys.32.110601.141800)
- [Owczarzy et al. 2008](https://doi.org/10.1021/bi702363u)
- [Dunn et al. 2015](https://doi.org/10.1038/nature14860)
- [PNAS 2024](https://doi.org/10.1073/pnas.2406769121)
- [Authors' model implementation](https://github.com/douglaslab/pyOrigamiBreak/blob/main/autobreak/utilities.py)

The implementation follows the published equations, not an uncritical port:
`sequence_to_Tm` in the inspected upstream utilities passes a Celsius value to
an inverse-temperature function; NADOC explicitly uses Kelvin.

Numerical reference: Biopython `Tm_NN`, `DNA_NN4`, `dnac1=200`, `dnac2=0`,
`Na=0`, `Mg=10`, `saltcorr=7` gives **71.82146192 °C** for
CGTTCCAAAGATGTGGGCATGAGCTTAC. NADOC gives **71.81975608 °C**; the 0.001706 °C
difference is from gas-constant rounding (Biopython 1.987 versus
8.31447/4.184 cal mol⁻¹ K⁻¹).

Tests: `scene/staple_temperature.test.js`, `ui/staple_temperature_view.test.js`,
`ui/view_tool_buttons.test.js`, and the read-only browser exercise
`e2e/staple_temperature.spec.js` using existing parts read-only. The default is
`Examples/U6hb.nadoc`; `NADOC_TEMPERATURE_DESIGN` and
`NADOC_TEMPERATURE_EXPECT_SCAFFOLDS` select a larger multi-scaffold check.
VoltronCoreArmV2 yields 405 total estimates (182 and 223 on its respective
scaffolds), versus 182 before multi-scaffold support; 1,503 domain estimates
are unchanged. Tests cover independent contour lengths, scaffold reordering,
secondary-scaffold nick wraparound, mixed-scaffold rejection and ambiguous occupancy.

Validation on November 5, 2026, including cadnano: 10,108 frontend tests passed
(1 skipped), 23 smoke checks passed, and both read-only browser exercises passed
(3D mesh colors and cadnano canvas pixel restoration), now also verified on
VoltronCoreArmV2 with both scaffolds covered. Lint passed. The source files
are unchanged, and temporary test artifacts were removed. Human
mixed-spacing readability review remains tracked as MV-58.
