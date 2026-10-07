"""Read-only workflow checklist, separate from scientific qualification.

Uses the existing topology and sequence contracts. It never infers intended
pairing coverage, repairs a route, assigns bases, or runs a simulation.
"""

from __future__ import annotations

from backend.core.models import Design, StrandType
from backend.core.sequences import strand_sequence_length
from backend.core.topology_integrity import (
    domain_order_errors, junction_errors, occupancy_errors,
)
from backend.core.validator import validate_design


LIMITATIONS = [
    "Routing checks the authored strand paths and recorded junctions; it cannot infer missing intended connections.",
    "Unpaired scaffold bases are allowed. Staple coverage and folding yield are not certified.",
    "A completed simulation records workflow progress, not convergence or experimental validation.",
]


def _step(identifier, label, complete, detail, *, applicable=True, issues=None, action=None):
    return {
        "id": identifier, "label": label, "complete": bool(complete),
        "applicable": applicable, "detail": detail,
        "action": action or identifier, "issues": (issues or [])[:20],
    }


def _sequence_issues(design, strands):
    from backend.core.hairpin_dimer import linker_strand_sequence

    issues = []
    for strand in strands:
        expected = strand_sequence_length(design, strand)
        sequence = strand.sequence or ""
        if strand.strand_type == StrandType.LINKER:
            sequence = linker_strand_sequence(design, strand)
        assigned = sum(base in "ACGT" for base in sequence.upper())
        if expected == 0 or len(sequence) != expected or assigned != expected:
            issues.append(f"{strand.name or strand.id}: {assigned}/{expected} bases assigned (A/C/G/T).")
    # Terminal sequence extensions are ordered with their strand, but are not
    # characters in Strand.sequence. Include them without double-counting domains.
    ids = {strand.id for strand in strands}
    for extension in design.extensions:
        if extension.strand_id in ids and extension.sequence:
            if any(base not in "ACGT" for base in extension.sequence.upper()):
                issues.append(f"{extension.label or extension.id}: terminal extension has unassigned bases.")
    return issues


def standard_readiness(design: Design | None) -> dict:
    """Evaluate standard steps for active DNA; references never create obligations."""
    empty = {
        "available": False, "design_id": None, "steps": [],
        "completed_steps": 0, "total_steps": 0,
        "state": "incomplete", "limitations": list(LIMITATIONS),
    }
    if design is None:
        return empty
    active = design.without_reference_geometry()
    if not active.helices and not active.strands:
        return empty
    scaffolds = [s for s in active.strands if s.is_scaffold]
    oligos = [s for s in active.strands if not s.is_scaffold]
    staples = [s for s in oligos if s.strand_type == StrandType.STAPLE]
    native_ids = {h.id for h in active.helices if h.native_residues}
    native_only = bool(active.strands) and all(
        s.domains and all(d.helix_id in native_ids for d in s.domains)
        for s in active.strands
    )
    scaffold_applicable = not native_only or bool(scaffolds)
    # Validate the original object: the simulation projection intentionally prunes
    # dangling records, which must not hide integrity problems in the editor.
    report = validate_design(design)
    topology_issues = [result.message for result in report.results if not result.ok]
    route_issues = domain_order_errors(design) + occupancy_errors(design) + junction_errors(design)
    # This is the validator's existing check, not a new inference about routing.
    route_issues.extend(message for message in topology_issues if (
        "nicked at crossover" in message or "Improper crossover" in message
        or "domain helix references unknown" in message
    ))
    for strand in active.strands:
        if not strand.domains:
            route_issues.append(f"Strand {strand.name or strand.id!r} has no routed domains.")
    scaffold_issues = _sequence_issues(active, scaffolds)
    oligo_issues = _sequence_issues(active, oligos)
    scaffold_routed = bool(scaffolds) and all(s.domains for s in scaffolds) and not route_issues
    staple_routed = bool(staples) and all(s.domains for s in staples) and not route_issues
    if native_only:
        staple_routed = bool(oligos) and all(s.domains for s in oligos) and not route_issues
    steps = [
        _step("scaffold_routing", "Scaffold routing", scaffold_routed or not scaffold_applicable,
              (f"{len(scaffolds)} scaffold path(s); recorded backbone connections checked."
               if scaffolds else "Native oligo structure needs no scaffold." if native_only else "Route a scaffold path."),
              applicable=scaffold_applicable, issues=route_issues,
              action="validation" if route_issues else "scaffold_routing"),
        _step("staple_routing", "Oligo routing" if native_only else "Staple routing", staple_routed,
              (f"{len(oligos) if native_only else len(staples)} authored oligo path(s); unpaired scaffold is allowed."
               if staples or native_only else "Create staple paths; linker strands alone do not satisfy this step."),
              issues=route_issues, action="validation" if route_issues else "staple_routing"),
        _step("scaffold_sequence", "Scaffold sequence", bool(scaffolds) and not scaffold_issues or not scaffold_applicable,
              "Native oligo structure needs no scaffold sequence." if not scaffold_applicable else
              f"{len(scaffolds)} scaffold sequence(s) checked for complete A/C/G/T coverage.",
              applicable=scaffold_applicable, issues=scaffold_issues),
        _step("staple_sequences", "Oligo sequences" if native_only else "Staple / linker sequences",
              bool(oligos) and not oligo_issues,
              f"{len(oligos)} oligo sequence(s), including overhangs, linkers and terminal extensions.",
              issues=oligo_issues),
        _step("topology", "Design validation", report.passed and bool(active.strands) and not route_issues,
              "Existing design-integrity checks passed." if report.passed and active.strands and not route_issues else
              "Review unresolved design-integrity findings.",
              action="validation", issues=list(dict.fromkeys(topology_issues + route_issues))),
    ]
    return finish_readiness({**empty, "available": True, "design_id": design.id, "steps": steps})


def finish_readiness(report: dict, simulation: dict | None = None) -> dict:
    """Derive the display state from standard steps and positive simulation evidence."""
    simulation = simulation or {
        "complete": False, "action": "simulation",
        "detail": "Complete a Fine run (mrDNA, CanDo or SNUPI) or Production run (oxDNA, NAMD or LAMMPS) for this design.",
    }
    applicable = [step for step in report["steps"] if step.get("applicable", True)]
    completed = sum(step["complete"] for step in applicable)
    ready = bool(applicable) and completed == len(applicable)
    return {
        **report, "completed_steps": completed, "total_steps": len(applicable),
        "state": ("ready" if simulation["complete"] else "simulation_recommended") if ready else "incomplete",
        "simulation": simulation,
    }
