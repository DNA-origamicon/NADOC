"""Named relaxation presets — pick a published protocol instead of hand-matching settings.

Four tiers, from the protocol survey in
``experiments/exp47_protocol_delta/PROTOCOL_PRESETS.md``:

* ``fast_shape``  — ENRG-MD vacuum relax (Aksimentiev tutorial step 2).  No solvent at
  all: the ENM plus inter-helical P-P repulsion bonds stand in for explicit water.
  Seconds to minutes at any size.  **Not yet runnable** — see ``available``.
* ``implicit_gbis`` — NAMD GBIS continuum solvent.  The only no-explicit-water option
  that runs today; cannot go GPU-resident.
* ``standard``    — the Aksimentiev explicit-MgCl2 relax (tutorial step 3).  Mg(H2O)6 +
  CUFIX, full water box, ENM ladder k = 0.5 -> 0.1 -> 0.01 -> 0.  This is the default.
* ``full_physics`` — solvent-first staged release, after Roodhuizen et al. (ACS Nano 13,
  10798) and Joshi et al. (Methods Mol Biol 2639): hold the solute, let the environment
  equilibrate, then release in stages and run long.

The preset only supplies DEFAULTS.  Anything the user sets explicitly wins — a preset is a
starting point, not a lock.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FAST_SHAPE = "fast_shape"
IMPLICIT_GBIS = "implicit_gbis"
STANDARD = "standard"
FULL_PHYSICS = "full_physics"
DEFAULT_PRESET = STANDARD

#: Every preset names the engine protocol it runs on.  This is the whole point of the
#: merge: protocol is DERIVED from the preset, so the two can no longer disagree.  The
#: panel used to carry a second "Protocol" dropdown, which meant you could ask for
#: "Standard (Aksimentiev)" — explicit MgCl2, Mg(H2O)6, CUFIX — while separately
#: selecting implicit solvent, and nothing caught it.
EXPLICIT_PROTOCOL = "equilibrium_aware_namd"
IMPLICIT_PROTOCOL = "implicit_gbis_namd"
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
            "No solvent. Relaxes the idealised lattice into its real shape using an "
            "elastic network plus inter-helical repulsion. Seconds to minutes at any "
            "size; gives a structure, not thermodynamics."
        ),
        defaults={"protocol": EXPLICIT_PROTOCOL, "water_shell_nm": 0.0},
        available=False,
        unavailable_reason=(
            "Needs the vacuum ENRG-MD pipeline, which NADOC does not have yet: a "
            "DNA-only package (no gmx solvate / autoionize) and the inter-helical "
            "phosphate-phosphate repulsion restraints. The tutorial's own extrabonds "
            "file gives those as k = 1 kcal/mol/A^2 at a 31 A rest length, so the "
            "parameters are known; the placement rule and the no-solvent package path "
            "are what remain."
        ),
        reference="Aksimentiev origami tutorial step 2 (ENRG-MD, in vacuo)",
    ),
    IMPLICIT_GBIS: RelaxPreset(
        id=IMPLICIT_GBIS,
        label="Implicit Solvent (GBIS)",
        summary=(
            "No explicit water — the solvent is a continuum. Fits a small GPU and needs "
            "no box sizing at all. Note it cannot run GPU-resident, so on this hardware "
            "it is slower per step than the explicit path despite the far smaller system; "
            "it is the only no-water option until the vacuum tier lands."
        ),
        defaults={"protocol": IMPLICIT_PROTOCOL},
        reference="NAMD GBIS implicit solvent",
        requires_cpu_namd=True,
    ),
    STANDARD: RelaxPreset(
        id=STANDARD,
        label="Standard (Aksimentiev)",
        summary=(
            "Explicit MgCl2 with Mg(H2O)6 and CUFIX, full water box, ENM ladder "
            "k = 0.5 / 0.1 / 0.01 / 0. The published origami relaxation, and what most "
            "work should use."
        ),
        defaults={
            "protocol": EXPLICIT_PROTOCOL,
            "water_shell_nm": 0.0,     # full box; the carve is a memory fallback only
            "padding_nm": 1.2,
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
            "water_shell_nm": 0.0,
            "padding_nm": 1.5,
            "early_stop_relax": False,   # never truncate a stage you intend to publish
        },
        reference=("Roodhuizen et al., ACS Nano 13, 10798 (2019); "
                   "Joshi, Li & Aksimentiev, Methods Mol Biol 2639 (2023)"),
    ),
}

#: Presentation order for the dropdown — cheapest first.
PRESET_ORDER = (FAST_SHAPE, IMPLICIT_GBIS, STANDARD, FULL_PHYSICS)


def get_preset(preset_id: "str | None") -> RelaxPreset:
    """Look up a preset, falling back to the default for unknown/empty ids."""
    return PRESETS.get((preset_id or "").strip() or DEFAULT_PRESET,
                       PRESETS[DEFAULT_PRESET])


def apply_preset(preset_id: "str | None", requested: dict,
                 explicit: "set[str] | None" = None) -> dict:
    """Merge a preset's defaults under ``requested``.

    ``explicit`` names the fields the caller actually set; those are never overridden.
    Fields absent from ``explicit`` take the preset's value when it has one.  Returns a
    new dict — the input is not mutated.
    """
    preset = get_preset(preset_id)
    explicit = explicit or set()
    out = dict(requested)
    for key, value in preset.defaults.items():
        if key not in explicit:
            out[key] = value
    return out


def protocol_for(preset_id: "str | None") -> str:
    """The engine protocol a preset runs on.  Derived, never separately selectable."""
    return get_preset(preset_id).defaults.get("protocol", EXPLICIT_PROTOCOL)


def preset_availability(preset: RelaxPreset) -> tuple[bool, str]:
    """Is this preset runnable *on this machine* right now?

    Static unavailability (a pipeline NADOC does not have) is joined here with RUNTIME
    unavailability (a toolchain this host does not have).  GBIS is the second kind: it
    is unsupported on the NAMD 3 CUDA nonbonded kernel, so it needs a multicore build,
    and a host with only the CUDA build cannot run it at all.  Discovering that after
    solvation — which is what happened — wastes a prep and reads like a bug.
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
            "protocol": p.defaults.get("protocol", EXPLICIT_PROTOCOL),
            "is_default": p.id == DEFAULT_PRESET,
        })
    return out
