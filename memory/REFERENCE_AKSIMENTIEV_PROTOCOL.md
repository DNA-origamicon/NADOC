---
name: reference-aksimentiev-protocol
description: "The canonical Aksimentiev DNA-origami NAMD protocol, read from the tutorial's own scripts, plus the exact NADOC delta. Read before changing solvation, the ENM ladder, or barostat settings."
metadata:
  node_type: memory
  type: reference
---

# Aksimentiev DNA-origami NAMD protocol — ground truth + NADOC delta

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Verified 2026-07-29 by reading the tutorial's **own scripts**, not the prose:
`origamitutorial.tar.gz` (108 MB; streamed and only the `*.namd/*.sh/*.tcl/*.pl` kept)
from <https://bionano.physics.illinois.edu/tutorials/practical-guide-dna-origami-simulations-using-namd>,
plus the Methods-in-Molecular-Biology chapter PDF (`origamiprotocols_0.pdf`).
Reference system = `hextube`, a cadnano hexagonal tube.

## Mg census correction (2026-10-07)

Direct census of the official tutorial archive's step2/hextube.psf and
step3/hextube_MGHH_WI.psf gives DNA charge -865 e (880 nt), 516 MGH and 167 CLA.
That is 433 neutralising Mg plus 83 additional MgCl2 units and one odd-charge
chloride. The tutorial does not mandate 12.5 mM; its chosen count depends on the
system. Retained source scripts, PSFs and census are under
`.development-artifacts/mg_recipe_audit_20261007/`.

NADOC previously used max(neutralising Mg, requested bulk Mg), so its newer dense
origami boxes received effectively neutralising Mg alone. This is superseded:
`ion_counts` now adds ceil(|Q|/2) counterions AND the requested MgCl2 formula units;
Cl balances Mg excess and any requested NaCl. New charge audits record
`concentration_convention: added_salt_after_neutralization`. Historical packages
are unchanged and their salt notes retain the legacy convention. Mg hexahydrate,
Mg-O restraints, near-backbone seeding and CHARMM36/CUFIX remain in place.
Nominal added-salt concentration is distinct from total Mg/box volume and from
measured free Mg; the current solvent-volume convention is unchanged.

The archived 24HB 0xT has 6,644 Na / 103 MGH / 206 Cl, whereas 1xT has
3,491 MGH / no Na / no Cl and 2xT has 3,660 MGH / no Na / no Cl. Thus salt
protocol is confounded with extra bases. At the recorded 1xT preparation volume,
12.5 mM added MgCl2 adds 84 Mg and 168 Cl to the neutralising census.
Publication comparisons should use matched 0/1/2xT salt/protocol, comparable
periodic-image separation, independent replicas and convergence diagnostics.
Correcting only 0xT to the new convention does not make old 1/2xT salt-matched.
No production simulations were launched by this audit.

<a id="the-pipeline"></a>
- [The pipeline](details/REFERENCE_AKSIMENTIEV_PROTOCOL/01-the-pipeline.md#the-pipeline)

- [The pipeline — continued detail](details/REFERENCE_AKSIMENTIEV_PROTOCOL/01-the-pipeline.md)

## Three notes that bear directly on NADOC failures

1. **Underfilled box → vacuum bubbles.** VMD `solvate` "usually underestimates the number
   of water molecules needed", so the box shrinks under 1 atm — that shrink IS their
   equilibration monitor. Their sanctioned fix (Note 4): *"run your simulation in NPT with
   the DNA position fixed, allowing the box size to fluctuate until it reaches a value
   appropriate for the amount of water molecules in the system"* — explicitly preferred
   over resolvating. If the bubble is big enough that its removal destabilises the run,
   **increase `langevinPistonPeriod`/`Decay` by ×10**, then revert once the box is stable.
2. **NVT for applied fields.** *"The NVT ensemble is also recommended if you are running a
   simulation that includes externally applied forces or electric fields. Running these
   types of simulations in NPT guarantees this error will eventually occur."* → applies to
   [[project_oxdna_efield]] / any NAMD E-field run.
3. **The k=0 stage length is the user's problem.** *"one may need to modify the protocol,
   in particular the duration of a free equilibration simulation (k=0)."* Their 4.8 ns is
   for a *relaxed structure*, not an equilibrium ensemble — everything NADOC does beyond
   that (200 ns free runs for pose/stiffness extraction) is outside the reference envelope,
   so the box rules have to be extended with it. See [[crossover-catenation]] §2026-07-29.

<a id="nadoc-delta--closed-2026-07-30-recipe-version-2"></a>
- [NADOC delta — CLOSED 2026-07-30 (recipe version 2)](details/REFERENCE_AKSIMENTIEV_PROTOCOL/02-nadoc-delta--closed-2026-07-30-recipe-version-2.md#nadoc-delta--closed-2026-07-30-recipe-version-2)

<a id="what-was-wrong-and-what-it-is-now"></a>
- [What was wrong, and what it is now](details/REFERENCE_AKSIMENTIEV_PROTOCOL/02-nadoc-delta--closed-2026-07-30-recipe-version-2.md#what-was-wrong-and-what-it-is-now)

<a id="deliberate-documented-deviations-kept"></a>
- [Deliberate, documented deviations (kept)](details/REFERENCE_AKSIMENTIEV_PROTOCOL/02-nadoc-delta--closed-2026-07-30-recipe-version-2.md#deliberate-documented-deviations-kept)

<a id="-their-electrostatics-are-strictly-better-here--measured-2026-07-29"></a>
- [✅ Their electrostatics are strictly better here — MEASURED (2026-07-29)](details/REFERENCE_AKSIMENTIEV_PROTOCOL/02-nadoc-delta--closed-2026-07-30-recipe-version-2.md#-their-electrostatics-are-strictly-better-here--measured-2026-07-29)

<a id="literature-comparability-audit-2026-08-03--the-full-list"></a>
- [Literature-comparability audit (2026-08-03) — the full list](details/REFERENCE_AKSIMENTIEV_PROTOCOL/02-nadoc-delta--closed-2026-07-30-recipe-version-2.md#literature-comparability-audit-2026-08-03--the-full-list)

<a id="relax-presets-shipped-2026-07-29--backendcoremd_presetspy"></a>
- [Relax presets shipped (2026-07-29) — `backend/core/md_presets.py`](details/REFERENCE_AKSIMENTIEV_PROTOCOL/03-relax-presets-shipped-2026-07-29--backendcoremd_presetspy.md#relax-presets-shipped-2026-07-29--backendcoremd_presetspy)

- [Relax presets shipped (2026-07-29) — `backend/core/md_presets.py` — continued detail](details/REFERENCE_AKSIMENTIEV_PROTOCOL/03-relax-presets-shipped-2026-07-29--backendcoremd_presetspy.md)

<a id="other-defaults-flipped-2026-07-29"></a>
- [Other defaults flipped (2026-07-29)](details/REFERENCE_AKSIMENTIEV_PROTOCOL/03-relax-presets-shipped-2026-07-29--backendcoremd_presetspy.md#other-defaults-flipped-2026-07-29)

<a id="what-of-this-is-now-implemented-2026-07-29"></a>
- [What of this is now implemented (2026-07-29)](details/REFERENCE_AKSIMENTIEV_PROTOCOL/03-relax-presets-shipped-2026-07-29--backendcoremd_presetspy.md#what-of-this-is-now-implemented-2026-07-29)

<a id="the-settle-stage-restrains-it-does-not-use-fixedatoms-2026-08-04"></a>
- [The settle stage restrains, it does not use `fixedAtoms` (2026-08-04)](details/REFERENCE_AKSIMENTIEV_PROTOCOL/04-the-settle-stage-restrains-it-does-not-use-fixedatoms-2026-08-04.md#the-settle-stage-restrains-it-does-not-use-fixedatoms-2026-08-04)
