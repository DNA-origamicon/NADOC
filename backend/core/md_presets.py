"""Named relaxation presets — pick a published protocol instead of hand-matching settings.

Four tiers, from the protocol survey in
``experiments/exp47_protocol_delta/PROTOCOL_PRESETS.md``:

* ``fast_shape``  — ENRG-MD vacuum relax (Aksimentiev tutorial §3.2).  RETIRED
  2026-07-30: NADOC derives physical geometry, so there is no lattice to unfold, and the
  repulsion surrogate scores zero bonds on a dense honeycomb.  See ``available``.
* ``implicit_gbis`` — NAMD GBIS continuum solvent.  The only no-explicit-water option
  that runs today; cannot go GPU-resident.
* ``standard``    — the Aksimentiev explicit-MgCl2 relax (tutorial §3.3): Mg(H2O)6 +
  CUFIX in a full water box, ENM ladder k = 0.5 -> 0.1 -> 0.01 -> 0, origami neutralised
  by magnesium rather than sodium.  Their §3.2 vacuum pre-step is deliberately NOT run —
  it unfolds caDNAno's abstract lattice, and NADOC geometry is already physical.  Default.
* ``full_physics`` — solvent-first staged release, after Roodhuizen et al. (ACS Nano 13,
  10798) and Joshi et al. (Methods Mol Biol 2639): hold the solute, let the environment
  equilibrate, then release in stages and run long.

Two more tiers exist for the Job Wizard, which asks the question that actually decides a
run: *are you reproducing the literature, or getting an answer about your design?*

* ``literature``   — the published protocol with nothing traded away for speed. No early
  stopping, no hydrogen-mass repartitioning, and the paper's own 2 fs integrator.
* ``design_speed`` — every measured accelerator on.  The right choice while iterating on
  a design; not the one whose numbers go in a paper.

The preset supplies DEFAULTS: anything the user sets explicitly wins, so a preset is a
starting point rather than a cage. ``protocol`` is the exception because a preset owns
its engine choice by definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FAST_SHAPE = "fast_shape"
IMPLICIT_GBIS = "implicit_gbis"
STANDARD = "standard"
FULL_PHYSICS = "full_physics"
LITERATURE = "literature"
DESIGN_SPEED = "design_speed"
HIGH_ASPECT_RATIO = "high_aspect_ratio"
DEFAULT_PRESET = STANDARD

#: Every preset names the engine protocol it runs on.  This is the whole point of the
#: merge: protocol is DERIVED from the preset, so the two can no longer disagree.  The
#: panel used to carry a second "Protocol" dropdown, which meant you could ask for
#: "Standard (Aksimentiev)" — explicit MgCl2, Mg(H2O)6, CUFIX — while separately
#: selecting implicit solvent, and nothing caught it.
EXPLICIT_PROTOCOL = "equilibrium_aware_namd"
IMPLICIT_PROTOCOL = "implicit_gbis_namd"
#: In-vacuo ENRG-MD shape relaxation (tutorial §3.2).  Shipped and then RETIRED on
#: 2026-07-30: it exists to unfold caDNAno's abstract lattice, which NADOC never has.
#: The protocol id stays valid so an existing job still resolves; the builder
#: (backend/core/namd_vacuum.py) is dormant, not deleted.
VACUUM_PROTOCOL = "vacuum_enrgmd_namd"
#: Accepted by the API for existing jobs and scripted callers, but no longer offered in
#: the menu: it is `equilibrium_aware_namd` with the topology gate turned OFF
#: (``prepare_equilibrium_aware_namd`` is a wrapper that adds require_full_topology=True),
#: which is a validation choice, not a protocol.
RETIRED_FROM_MENU = ("mgh_slow_release",)


@dataclass(frozen=True)
class RelaxPreset:
    id: str
    label: str
    summary: str
    #: Request-field defaults this preset applies when the user has not set them.
    defaults: dict = field(default_factory=dict)
    #: Fields this preset owns absolutely, applied even when explicitly set. Reserved for
    #: choices whose override would make the preset name false.
    locked: frozenset = frozenset()
    #: False when the pipeline it needs does not exist yet — the UI shows it disabled
    #: with ``unavailable_reason`` rather than pretending it will run.
    available: bool = True
    unavailable_reason: str = ""
    #: Free-text provenance, shown in the panel and echoed into the job record.
    reference: str = ""
    #: True when the preset can only run on a NON-CUDA (multicore) NAMD build.  Checked
    #: at catalogue time so the menu greys it out on a machine that lacks one, instead
    #: of accepting the job, paying for solvation, and failing at the first segment.
    requires_cpu_namd: bool = False


PRESETS: dict[str, RelaxPreset] = {
    FAST_SHAPE: RelaxPreset(
        id=FAST_SHAPE,
        label="Fast Shape Check (Vacuum)",
        summary=(
            "No solvent. Relaxes an abstract lattice into a real shape using an elastic "
            "network plus inter-helical repulsion. Retired: NADOC designs already carry "
            "derived, physical geometry, so there is no lattice here to unfold."
        ),
        defaults={"protocol": VACUUM_PROTOCOL},
        available=False,
        unavailable_reason=(
            "Not needed, and measurably harmful on dense lattices. The tutorial's §3.2 "
            "exists to turn caDNAno's abstract parallel-helix lattice into a structure; "
            "NADOC derives geometry from topology + B-DNA constants + deformations, so "
            "every design already has physical positions (measured: a 90-degree design's "
            "ideal build already holds ~98.5 degrees of per-helix bend). Worse, the "
            "interhelical repulsion surrogate needs a >22 nt crossover-free span and "
            "honeycomb crossovers recur every 21 nt, so a dense bundle gets ZERO of them "
            "and relaxes with no interhelical force term — bundles swelled 5.6-10%, away "
            "from the Mg-screened equilibrium. See experiments/exp50_vacuum_on_curved."
        ),
        reference="Yoo, Li, Slone, Maffeo & Aksimentiev, Methods Mol Biol 1811 (2018) "
        "§3.2 (ENRG-MD, in vacuo) — not applicable to NADOC geometry",
    ),
    IMPLICIT_GBIS: RelaxPreset(
        id=IMPLICIT_GBIS,
        label="Implicit Solvent (GBIS)",
        summary=(
            "No explicit water — the solvent is an approximate dielectric continuum, so "
            "there is no solvent box to size. NAMD does not support GBIS in GPU-resident "
            "mode; NADOC currently runs this protocol with the multicore CPU build."
        ),
        defaults={"protocol": IMPLICIT_PROTOCOL},
        reference="NAMD GBIS implicit solvent",
        requires_cpu_namd=True,
    ),
    STANDARD: RelaxPreset(
        id=STANDARD,
        label="Standard (Aksimentiev)",
        summary=(
            "The published origami relaxation: explicit MgCl2 with Mg(H2O)6 and CUFIX "
            "in a full water box, ENM ladder k = 0.5 / 0.1 / 0.01 / 0, with the origami "
            "neutralised by magnesium rather than sodium. Starts from NADOC's derived "
            "geometry — no pre-ladder shape step, because there is no abstract lattice "
            "to unfold. What most work should use."
        ),
        defaults={
            "protocol": EXPLICIT_PROTOCOL,
            "box_mode": "rotation",
            # The tutorial's own recipe is the DNA bbox ± 20 Å.  NADOC shipped 1.2 nm,
            # 40 % tighter.  namd_solvate.resolve_padding_nm trims this back down when
            # the resulting complete cell would not fit the selected hardware.
            "padding_nm": 2.0,
            "early_stop_relax": True,
        },
        reference="Yoo, Li, Slone, Maffeo & Aksimentiev, Methods Mol Biol 1811 (2018)",
    ),
    FULL_PHYSICS: RelaxPreset(
        id=FULL_PHYSICS,
        label="Slow (full physics)",
        summary=(
            "Solvent-first staged release: hold the solute, equilibrate the water and "
            "ions around it, then release the restraints in stages and run long. Days "
            "rather than hours, and it needs a rotation-sized box — the setting to pick "
            "when the numbers are going in a paper."
        ),
        defaults={
            "protocol": EXPLICIT_PROTOCOL,
            "box_mode": "rotation",
            # Wider than Standard's (now-faithful) 2.0 nm: this is the tier whose
            # numbers go in a paper, so give the solute more room to tumble than the
            # reference strictly needs.
            "padding_nm": 2.5,
            "early_stop_relax": False,  # never truncate a stage you intend to publish
        },
        reference=(
            "Roodhuizen et al., ACS Nano 13, 10798 (2019); "
            "Joshi, Li & Aksimentiev, Methods Mol Biol 2639 (2023)"
        ),
    ),
    DESIGN_SPEED: RelaxPreset(
        id=DESIGN_SPEED,
        label="Optimised for the design (fast)",
        summary=(
            "Every measured accelerator on: hydrogen-mass repartitioning with a 4 fs "
            "timestep, GPU-resident integration, a stage that stops as soon as it has "
            "settled, and the cheap bounding-box cell a restrained ladder does not need "
            "to rotate in. Same chemistry as the published protocol — only integrator and "
            "scheduling knobs move. Use it while you are still changing the design; "
            "switch to Literature for numbers you intend to publish."
        ),
        defaults={
            "protocol": EXPLICIT_PROTOCOL,
            "box_mode": "bbox",
            "padding_nm": 1.2,
            "salt_mode": "screening",
            "early_stop_relax": True,
            "fast": True,
        },
        reference=(
            "NADOC measured defaults: exp47 electrostatics (+39 % throughput, "
            "structurally indistinguishable), exp49 integrator probe, the "
            "GPU-resident size crossover, bounding-box cell sizing under 20 ns"
        ),
    ),
    HIGH_ASPECT_RATIO: RelaxPreset(
        id=HIGH_ASPECT_RATIO,
        label="High aspect ratio (rods)",
        summary=(
            "For long, thin filaments. Uses extra NPT patch-grid margin and a 1 fs "
            "flexible-bond settle start, then returns to the normal accelerated ladder. "
            "Choose it for rod-like boxes; it is deliberately not selected automatically."
        ),
        defaults={
            "protocol": EXPLICIT_PROTOCOL,
            "box_mode": "bbox",
            "padding_nm": 1.2,
            "salt_mode": "screening",
            "early_stop_relax": True,
            "fast": True,
        },
        reference=(
            "NADOC high-aspect recovery: bounded margin 10 and a soft first dynamics "
            "stage; the later ENM ladder retains its normal timestep"
        ),
    ),
    LITERATURE: RelaxPreset(
        id=LITERATURE,
        label="Match the literature (Aksimentiev)",
        summary=(
            "The published protocol with nothing traded for speed. Full periodic water "
            "box, every stage run to its full length, standard hydrogen masses, and the paper's "
            "2 fs relaxation integrator rather than NADOC's 4 fs fast path. Slower, and "
            "reproducible against the reference."
        ),
        defaults={
            "protocol": EXPLICIT_PROTOCOL,
            "box_mode": "rotation",
            # The tutorial's own recipe is the DNA bounding box +/- 20 A.
            "padding_nm": 2.0,
            # Mg(H2O)6 neutralises, no sodium — the published ionic condition.
            "salt_mode": "screening",
            # The tutorial's literal figure.  Still a floor: minimisation has to scale
            # with the system, and the reference's own Note 2 attributes rigid-bond
            # failures to insufficient minimisation.
            "minimize_steps": 4_800,
            "early_stop_relax": False,
            "fast": False,
        },
        reference=(
            "Yoo, Li, Slone, Maffeo & Aksimentiev, Methods Mol Biol 1811 (2018) "
            "§3.3 — explicit MgCl2, Mg(H2O)6 + CUFIX, ENM ladder "
            "k = 0.5 / 0.1 / 0.01 / 0, 4.8 ns per stage at 2 fs"
        ),
    ),
}

#: Presentation order for the dropdown — cheapest first.
PRESET_ORDER = (
    FAST_SHAPE,
    IMPLICIT_GBIS,
    DESIGN_SPEED,
    HIGH_ASPECT_RATIO,
    STANDARD,
    LITERATURE,
    FULL_PHYSICS,
)


def get_preset(preset_id: "str | None") -> RelaxPreset:
    """Look up a preset, falling back to the default for unknown/empty ids."""
    return PRESETS.get(
        (preset_id or "").strip() or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET]
    )


def apply_preset(
    preset_id: "str | None", requested: dict, explicit: "set[str] | None" = None
) -> dict:
    """Merge a preset's defaults under ``requested``.

    ``explicit`` names the fields the caller actually set; those are never overridden —
    EXCEPT the preset's ``locked`` fields, which it owns outright (see RelaxPreset.locked).
    Fields absent from ``explicit`` take the preset's value when it has one.  Returns a
    new dict — the input is not mutated.
    """
    preset = get_preset(preset_id)
    explicit = explicit or set()
    out = dict(requested)
    for key, value in preset.defaults.items():
        if key not in explicit or key in preset.locked:
            out[key] = value
    return out


def protocol_for(preset_id: "str | None") -> str:
    """The engine protocol a preset runs on.  Derived, never separately selectable."""
    return get_preset(preset_id).defaults.get("protocol", EXPLICIT_PROTOCOL)


def preset_availability(preset: RelaxPreset) -> tuple[bool, str]:
    """Is this preset runnable *on this machine* right now?

    Static unavailability (a pipeline NADOC does not have) is joined here with RUNTIME
    unavailability (a toolchain this host does not have). GBIS currently uses NADOC's
    multicore path, so a host with only a CUDA build cannot run that preset.
    """
    if not preset.available:
        return False, preset.unavailable_reason
    if preset.requires_cpu_namd:
        try:
            from backend.core.namd_runner import find_namd  # noqa: PLC0415

            find_namd(prefer_cpu=True)
        except Exception as exc:  # noqa: BLE001 — any resolution failure means "no"
            return False, str(exc)
    return True, ""


def preset_catalogue() -> list[dict]:
    """Serialisable list for the frontend dropdown, cheapest first.

    ``available`` reflects this HOST, not just this build — see ``preset_availability``.
    """
    out = []
    for p in (PRESETS[i] for i in PRESET_ORDER):
        ok, why = preset_availability(p)
        out.append(
            {
                "id": p.id,
                "label": p.label,
                "summary": p.summary,
                "available": ok,
                "unavailable_reason": why,
                "reference": p.reference,
                "defaults": dict(p.defaults),
                "locked": sorted(p.locked),
                "protocol": p.defaults.get("protocol", EXPLICIT_PROTOCOL),
                "is_default": p.id == DEFAULT_PRESET,
            }
        )
    return out
