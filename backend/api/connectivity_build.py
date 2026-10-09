"""Route a reviewed connectivity tree without moving its nanoparticles.

Terminal duplex space is reserved for axial, blunt-end handles. Chemical
attachment and graft-site fitting are deliberately not implied by this preview.
"""

from functools import lru_cache
import json
import numpy as np

from backend.core.models import Design
from backend.core.two_np_generator import RodCandidate, GeneratorSettings


@lru_cache(maxsize=4)
def _prepare(serialized_source, serialized_settings):
    from backend.api import state
    from backend.api.headless_build import (
        scratch_session,
        full_autostaple,
        full_sequence,
    )
    from backend.core.connectivity_generator import compile_connectivity
    from backend.core.branched_generator import branch_seed, route_branches
    from backend.core.generated_sweep import encode_sweep
    from backend.core.curved_branches import validate_fork_junctions
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.generator_validation import check_generated_structure
    from backend.core.validator import validate_design

    source = Design.model_validate_json(serialized_source)
    from backend.core.two_np_generator import gold_particles

    gold_particles(source, tuple(range(2, 9)))
    settings = GeneratorSettings.model_validate_json(serialized_settings)
    failures = []
    # Retain the reviewed topology and section; give short terminal arms enough
    # room for the assumed duplex. Search geometry, never relax safety checks.
    for junction_bp in (28, 42):
        for retreat in (0, 5, 10, 15, 17.5, 20, 25):
            try:
                summary = compile_connectivity(
                    source,
                    settings.connectivity_plan,
                    settings.duplex_bp,
                    retreat,
                    junction_bp,
                )
                seed = branch_seed(source.lattice_type, summary)
                if summary["branch_windows"]:
                    routed, _ = route_branches(seed, summary)
                else:
                    from backend.core.seamed_router import auto_scaffold_seamed

                    routed, routing = auto_scaffold_seamed(seed)
                    if not routing.valid or len(routed.scaffolds()) != 1:
                        raise ValueError(
                            "The terminal bundle could not route as one scaffold."
                        )
                routed = encode_sweep(routed)
                initial_used = physical_scaffold_nt(routed)
                budget = (
                    (7249 if initial_used <= 7249 else 8064)
                    if settings.branch_scaffold_size == "auto"
                    else int(settings.branch_scaffold_size)
                )
                if initial_used > budget:
                    raise ValueError(
                        "The routed paths exceed the selected scaffold budget."
                    )
                scaffold = "M13mp18" if budget == 7249 else "p8064"
                with scratch_session(source.lattice_type):
                    state.set_design(routed)
                    stapled = encode_sweep(full_autostaple(scaffold))
                    state.set_design(stapled)
                    complete = full_sequence(scaffold).model_copy(deep=True)
                used = physical_scaffold_nt(complete)
                if used > budget:
                    raise ValueError(
                        "Curvature corrections exceed the scaffold budget."
                    )
                validate_fork_junctions(complete)
                validation = validate_design(complete)
                if not validation.passed:
                    raise ValueError(str(validation))
                from backend.core.design_geometry import fitting_geometry

                geometry = fitting_geometry(complete)
                positions = np.asarray(
                    [
                        n[k]
                        for n in geometry
                        for k in ("backbone_position", "base_position")
                    ]
                )
                for particle in source.nanoparticles:
                    if (
                        particle.kind == "gold_nanosphere"
                        and np.min(
                            np.linalg.norm(
                                positions - particle.pose.to_array()[:3, 3], axis=1
                            )
                        )
                        < particle.diameter_nm / 2
                    ):
                        raise ValueError(
                            "Generated DNA intersects a gold nanoparticle."
                        )
                screen = check_generated_structure(
                    complete, [h.id for h in complete.helices]
                )
                summary.update(
                    scaffold_size=budget,
                    scaffold_name=scaffold,
                    scaffold_used_nt=used,
                    unused_scaffold_nt=budget - used,
                    sizing_validation=screen,
                    junction_bp=junction_bp,
                    attachment_mode="blunt-end-assumed",
                    connections_per_particle=settings.connections_per_particle,
                )
                return complete.model_dump_json(), summary, len(failures) + 1
            except ValueError as exc:
                failures.append(str(exc))
    raise ValueError(
        "No routable geometry for this connectivity candidate and bundle size. "
        "Try another candidate or a smaller bundle. Last check: " + failures[-1]
    )


def plan_connectivity(source, settings):
    # Include particle properties but exclude unrelated history from cache keys.
    geometry_source = Design(
        lattice_type=source.lattice_type, nanoparticles=source.nanoparticles
    )
    encoded, summary, evaluated = _prepare(
        geometry_source.model_dump_json(), settings.model_dump_json()
    )
    summary = json.loads(json.dumps(summary))
    public = {
        k: v
        for k, v in summary.items()
        if not k.startswith(("connectivity_", "branch_"))
        and k not in ("cells", "base_frame")
    }
    centers = [
        p.pose.to_array()[:3, 3]
        for p in source.nanoparticles
        if p.kind == "gold_nanosphere"
    ]
    report = dict(
        selected=public,
        alternatives=[public],
        settings=settings.model_dump(mode="json"),
        search={"structural_candidates": 1, "geometry_candidates": evaluated},
        center_distance_nm=max(np.linalg.norm(a - b) for a in centers for b in centers),
        reason="Reviewed bundle-tree topology compiled to one scaffold with staple-supported shared junctions.",
        qualification=f"Junctions shifted {summary['junction_retreat_nm']:g} nm toward the root to accommodate routing and blunt-end duplex space. Uniform sections are preserved; unused scaffold is not padded. Blunt-end attachments are assumed, not chemically fitted or bound.",
        attachment_status="Blunt-end duplex space reserved. NP graft sites and overhang binding remain unassigned.",
    )
    return RodCandidate(Design.model_validate_json(encoded), summary), report


def materialize_connectivity(source, candidate, settings, history=None):
    core = candidate.design.model_copy(deep=True)
    if history:
        history.record(
            Design(lattice_type=source.lattice_type),
            core,
            "bundle-create",
            "Generate routed connectivity origami",
            {
                "attachment_mode": "blunt-end-assumed",
                "junction_retreat_nm": candidate.summary["junction_retreat_nm"],
            },
            "connectivity-core",
        )
    ports = []
    for terminal in candidate.summary["connectivity_terminals"]:
        cells = {
            tuple(c) for c in candidate.summary["connectivity_faces"][terminal["group"]]
        }
        ports.append(
            {
                **terminal,
                "helix_ids": [h.id for h in core.helices if h.grid_pos in cells],
                "duplex_bp": settings.duplex_bp,
                "connections": settings.connections_per_particle,
                "status": "assumed; overhangs and NP binding not assigned",
            }
        )
    return core, dict(
        generated_helix_ids=[h.id for h in core.helices],
        connections=[],
        attachment_residuals_nm=[],
        blunt_end_ports=ports,
        attachment_mode="blunt-end-assumed",
    )
