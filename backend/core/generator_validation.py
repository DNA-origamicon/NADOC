"""Screen every generated core with CanDo; prepare optional detailed validation jobs.

These jobs validate a snapshot, never silently rewrite the generated geometry.
A launched job is not a converged result or experimental calibration.
"""

import json


def check_generated_structure(design, helix_ids):
    """Screen the new duplex core before commit; existing disconnected parts are out of scope.

    CanDo pins every disconnected component, so a successful solve alone cannot
    establish connectivity. Check the mesh explicitly before solving. This is an
    elastic screening test, not a prediction of folding or bond dissociation.
    """
    import numpy as np
    from threadpoolctl import threadpool_limits
    from backend.physics.fem_solver import build_fem_mesh, _mesh_component_labels, predict_shape

    helix_ids = set(helix_ids)
    mesh = build_fem_mesh(design)
    indices = [i for i, node in enumerate(mesh.nodes) if node.helix_id in helix_ids]
    represented = {mesh.nodes[i].helix_id for i in indices}
    if not indices or represented != helix_ids:
        raise ValueError("CanDo validation failed: generated helices are missing paired duplex regions.")
    _, labels = _mesh_component_labels(mesh)
    components = len(set(int(labels[i]) for i in indices))
    if components != 1:
        raise ValueError(
            f"CanDo validation failed: the generated duplex core has {components} disconnected components."
        )
    # Sparse FEM/NMA is slower with a large BLAS pool on ordinary origami meshes.
    with threadpool_limits(limits=1, user_api="blas"):
        result = predict_shape(design, nonlinear=False, with_rmsf=True, with_thermal_fluctuations=False)
    rmsf = np.asarray([r["rmsf_nm"] for r in result.get("rmsf", []) if r["helix_id"] in helix_ids])
    positions = np.asarray([p["backbone_position"] for p in result.get("positions", []) if p["helix_id"] in helix_ids])
    if len(rmsf) != len(indices) or not positions.size or not np.isfinite(rmsf).all() or not np.isfinite(positions).all() or np.any(rmsf < 0):
        raise ValueError("CanDo validation failed: no finite shape and flexibility result for the generated core.")
    maximum = float(rmsf.max())
    if maximum == 0:
        raise ValueError("CanDo validation failed: normal-mode analysis returned no thermal fluctuations.")
    # A conspicuous review threshold, not an experimentally calibrated stability cutoff.
    warnings = []
    if maximum > 5.0:
        warnings.append("Predicted core RMSF exceeds the 5 nm screening threshold; inspect flexibility before using this design.")
    return dict(
        engine="cando", solver="linear", status="warning" if warnings else "passed",
        connected_components=components, n_nodes=len(indices),
        max_rmsf_nm=maximum, mean_rmsf_nm=float(rmsf.mean()), warnings=warnings,
        qualification="Connected, finite elastic duplex-core response. This does not validate folding, strand dissociation, or gold/linker dynamics.",
    )


def prepare_validation(design, level, workspace, *, doc_id=None):
    from backend.core.oxdna_staleness import (
        oxdna_design_fingerprint,
        effective_feature_log_position,
    )
    from backend.physics.oxdna_interface import _strand_nucleotide_order
    from backend.core.project_revisions import record_simulation_revision

    common = dict(
        design_name=f"{design.metadata.name or 'Generated design'} — {level}",
        n_nucleotides=len(_strand_nucleotide_order(design)),
        design_fingerprint=oxdna_design_fingerprint(design),
        feature_log_position=effective_feature_log_position(design),
    )
    if level in ("fem-linear", "fem-nonlinear"):
        from backend.core.cando_job import new_cando_job
        from backend.core.cando_runner import prepare_cando_job, start_job

        job = new_cando_job(
            **common,
            nonlinear=level == "fem-nonlinear",
            with_rmsf=True,
            with_thermal_fluctuations=True,
            doc_id=doc_id,
        )
        prepare_cando_job(design, job, workspace)
        kind = "cando"
        launch = lambda: start_job(job, workspace)
        qualification = "Routed duplex equilibrium and normal-mode fluctuations. FEM does not model gold-core/linker dynamics; inspect shape and flexibility in Simulations."
    elif level == "oxdna":
        from backend.core.oxdna_job import new_oxdna_job
        from backend.core.oxdna_protocol import (
            build_relaxation_stages,
            build_production_stage,
            assign_stage_seeds,
        )
        from backend.core.oxdna_runner import prepare_oxdna_job, start_job
        from backend.core.design_geometry import _geometry_for_design
        from backend.physics.oxdna_mobile_gold import (
            has_mobile_gold,
            find_mobile_gold_oxdna,
            configure_mobile_gold_stages,
        )

        if not has_mobile_gold(design) or not find_mobile_gold_oxdna():
            raise ValueError(
                "Particle validation requires conjugated gold and a local DNA2GOLD-capable oxDNA engine."
            )
        specs = build_relaxation_stages()
        specs.append(build_production_stage(steps=5_000_000, steps_per_frame=10_000))
        configure_mobile_gold_stages(specs)
        specs = assign_stage_seeds(specs, 1729)
        job = new_oxdna_job(
            **common,
            stages=[s.to_status() for s in specs],
            random_seed=1729,
            run_config=dict(
                kind="generator_validation",
                mechanics=level,
                production_steps=5_000_000,
                salt_concentration=0.5,
                seed=1729,
            ),
        )
        prepare_oxdna_job(design, _geometry_for_design(design), job, workspace, specs)
        kind = "oxdna"
        launch = lambda: start_job(job, workspace, specs)
        qualification = "Relaxation, equilibration and 5,000,000 production steps with mobile gold. A single pilot trajectory is not a convergence guarantee or calibrated experimental prediction."
    else:
        return None
    provenance = record_simulation_revision(workspace, design, kind, job.job_id)
    job.project_id, job.design_revision_id = (
        provenance.project_id,
        provenance.revision_id,
    )
    job.save(workspace)
    info = dict(
        engine=kind, job_id=job.job_id, status="queued", qualification=qualification
    )
    (job.job_dir(workspace) / "generator_validation.json").write_text(
        json.dumps(info, indent=2)
    )
    return info, launch
