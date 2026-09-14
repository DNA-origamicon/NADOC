#!/usr/bin/env python3
"""Inspect the photoproduct pipeline or register a new fail-closed request."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

# Allow ``uv run python scripts/photoproduct_workflow.py`` from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.photoproduct_registry import (
    REGISTRY_PATH,
    attach_photoproduct_asset,
    photoproduct_capabilities,
    photoproduct_registry,
    record_photoproduct_gate_review,
    record_photoproduct_metric_gate,
    request_photoproduct,
)
from backend.core.photoproduct_toolchain import photoproduct_toolchain_status
from backend.core.photoproduct_storage import validate_photoproduct_storage_root
from backend.parameterization.photoproduct_models import (
    audit_dna_boundary_model_replicates,
    build_charge_model,
    build_dna_boundary_model_candidate,
    build_flexibly_relaxed_dna_boundary_seed,
    build_grafted_dna_boundary_model_candidate,
    materialize_quantitatively_screened_dna_boundary_model,
    materialize_quantitatively_screened_grafted_dna_boundary_model,
    materialize_reviewed_dna_boundary_model,
)
from backend.parameterization.charmm_reference import (
    build_atom_type_candidate_plan,
    extract_initial_charge_guess,
)
from backend.parameterization.photoproduct_fit import (
    audit_parameter_workbook,
    build_parameter_workbook,
)
from backend.parameterization.photoproduct_candidate_assembly import (
    assemble_quantitative_parameter_workbook,
)
from backend.parameterization.photoproduct_candidate_engine import (
    run_candidate_engine_smoke,
    run_candidate_solution_smoke,
)
from backend.parameterization.photoproduct_candidate_context import (
    build_candidate_context_topology,
    build_duplex_context,
    build_reciprocal_crossover_1xt_context,
    run_candidate_context_precondition,
    run_candidate_context_solution_smoke,
)
from backend.parameterization.photoproduct_esp import audit_esp_job, generate_esp_job
from backend.parameterization.photoproduct_equivalence import (
    audit_endpoint_exchange_equivalence,
    build_equivalent_hessian_reference,
)
from backend.parameterization.photoproduct_hessian import build_hessian_target_bundle
from backend.parameterization.photoproduct_boundary_fit import (
    build_boundary_fit_input_campaign,
)
from backend.parameterization.photoproduct_boundary_nonbonded import (
    build_boundary_nonbonded_specification,
)
from backend.parameterization.photoproduct_boundary_charge_fit import (
    fit_boundary_charge_campaign,
    fit_boundary_charges,
)
from backend.parameterization.photoproduct_boundary_bonded_fit import (
    fit_boundary_bonded_response,
)
from backend.parameterization.photoproduct_qm_release import (
    build_boundary_qm_release_audits,
)
from backend.parameterization.photoproduct_coupled_conformer import (
    apply_coupled_conformer_review_decisions,
    audit_fixed_geometry_hessian_result,
    audit_reviewed_coupled_conformer_plan,
    build_coupled_conformer_review_index,
    build_coupled_conformer_review_decision_template,
    build_coupled_conformer_review_template,
    build_coupled_conformer_review_visualization,
    build_fixed_geometry_hessian_target_bundle,
    generate_fixed_geometry_hessian_job,
    materialize_quantitatively_screened_coupled_conformer_plan,
    materialize_visual_coupled_conformer_review,
)
from backend.parameterization.photoproduct_conformer_candidates import (
    build_coupled_conformer_candidates,
    build_coupled_conformer_mode_source,
)
from backend.parameterization.photoproduct_conformer_screen import (
    compare_periodicity_rank_screens,
    screen_coupled_conformer_fit_rank,
)
from backend.parameterization.photoproduct_distributed_hessian import (
    assemble_distributed_hessian,
    checkpoint_distributed_hessian_pairs,
    materialize_frequency_job_provenance,
    prepare_distributed_hessian,
    reconcile_equivalent_distributed_hessian_pairs,
    run_distributed_hessian_task,
)
from backend.parameterization.photoproduct_distributed_response import (
    assemble_distributed_fixed_geometry_hessian,
    prepare_distributed_fixed_geometry_hessian,
)
from backend.parameterization.photoproduct_definition_review import (
    audit_tt_cpd_definition_review,
    build_minimum_backed_definition_candidate,
    build_tt_cpd_definition_review_packet,
    materialize_visual_definition_review,
)
from backend.parameterization.photoproduct_help_trajectory import (
    build_photoproduct_help_trajectory,
)
from backend.parameterization.photoproduct_improper_convention import (
    audit_namd_improper_convention,
)
from backend.parameterization.photoproduct_nonbonded_fit import (
    fit_nonbonded_hypotheses,
)
from backend.parameterization.photoproduct_nonbonded_transfer import (
    audit_joint_nonbonded_candidate,
    audit_nonbonded_transfer,
    fit_joint_nonbonded_transfer,
)
from backend.parameterization.photoproduct_namd_smoke import (
    audit_photoproduct_namd_smoke,
    prepare_photoproduct_namd_smoke,
)
from backend.parameterization.photoproduct_openmm_skeleton import (
    build_openmm_candidate_skeleton,
)
from backend.parameterization.photoproduct_openmm_fit_basis import (
    build_openmm_linear_fit_basis,
)
from backend.parameterization.photoproduct_openmm_linear_response import (
    build_openmm_linear_response,
)
from backend.parameterization.photoproduct_geometry_refinement import (
    audit_geometry_refinement,
    build_geometry_refined_charmm_transform,
    refine_selected_response_fit_geometry,
)
from backend.parameterization.photoproduct_relative_energy import (
    audit_refined_relative_energies,
)
from backend.parameterization.photoproduct_fit_identifiability import (
    audit_openmm_fit_identifiability,
)
from backend.parameterization.photoproduct_response_campaign import (
    build_openmm_response_campaign,
)
from backend.parameterization.photoproduct_response_fit import (
    build_charmm_bonded_transform_candidate,
    build_response_fit_selection_template,
    build_response_fit_specification_template,
    compare_response_fit_evaluations,
    evaluate_reviewed_response_fit,
    extract_reviewed_response_fit_candidate,
    materialize_quantitative_response_fit_specification,
    select_quantitative_response_fit_candidate,
)
from backend.parameterization.photoproduct_parameter_coverage import (
    audit_model_graph_parameter_coverage,
    audit_photoproduct_parameter_coverage,
)
from backend.parameterization.photoproduct_charge_fit import build_charge_target_bundle
from backend.parameterization.photoproduct_bonded_fit_plan import build_bonded_fit_plan
from backend.parameterization.photoproduct_bonded_refit import (
    promote_bonded_fit_terms,
)
from backend.parameterization.photoproduct_charmm_export import (
    export_charmm_candidate_assets,
)
from backend.parameterization.photoproduct_qm import (
    audit_electrostatic_properties,
    audit_water_scf_calibration,
    audit_water_interaction_series,
    audit_frequency_result,
    audit_optimized_model,
    build_qm_job_series,
    generate_geometry_retry_job,
    generate_psi4_job,
    generate_water_interaction_job,
    generate_torsion_scan_job,
    reconcile_psi4_run,
    run_psi4_job,
    run_psi4_series,
)
from backend.parameterization.photoproduct_references import fetch_reference_bundle
from backend.parameterization.photoproduct_templates import (
    build_candidate_coordinate_template,
)
from backend.parameterization.photoproduct_stereo_candidates import (
    audit_tt_cpd_stereo_candidates,
    build_tt_cpd_chemical_definition_candidate,
    build_tt_cpd_stereo_candidates,
)
from backend.parameterization.photoproduct_stereo_independent import (
    audit_tt_cpd_stereo_with_openbabel,
)
from backend.parameterization.photoproduct_terms import write_term_inventory
from backend.parameterization.photoproduct_water import build_water_probe_series


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=REGISTRY_PATH, help="Registry JSON path."
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=(
            Path(os.environ["NADOC_PHOTOPRODUCT_STORAGE_ROOT"])
            if os.environ.get("NADOC_PHOTOPRODUCT_STORAGE_ROOT")
            else None
        ),
        help=(
            "Require generated output, cache, and scratch paths to resolve under this "
            "durable root. May also be set with NADOC_PHOTOPRODUCT_STORAGE_ROOT."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List registered products and their next gate.")
    sub.add_parser("doctor", help="Report local simulation/QM tools and install gates.")
    fetch = sub.add_parser(
        "fetch-references", help="Download and hash-check reviewed structural inputs."
    )
    fetch.add_argument("--product", default="TT-CPD")
    fetch.add_argument("--stereochemistry", default="cis-syn")
    fetch.add_argument("--cache-dir", type=Path, required=True)
    model = sub.add_parser(
        "build-charge-model", help="Construct a reviewed QM charge model compound."
    )
    model.add_argument("--product", default="TT-CPD")
    model.add_argument("--stereochemistry", default="cis-syn")
    model.add_argument("--reference-dir", type=Path, required=True)
    model.add_argument("--output-dir", type=Path, required=True)
    boundary_model = sub.add_parser(
        "build-dna-boundary-model-candidate",
        help="Build a review-only 1N4E cis-syn d(TpT) boundary model.",
    )
    boundary_model.add_argument("--reference-dir", type=Path, required=True)
    boundary_model.add_argument("--output-dir", type=Path, required=True)
    boundary_model.add_argument("--chain", default="B")
    boundary_model.add_argument("--endpoint-resid", action="append", required=True)
    boundary_model.add_argument("--pdb-model", default="1")
    grafted_boundary = sub.add_parser(
        "build-grafted-dna-boundary-model-candidate",
        help=(
            "Rigidly graft an audited product minimum onto a d(TpT) boundary using "
            "a proper rotation; emits a non-releasing screen candidate."
        ),
    )
    grafted_boundary.add_argument("--reference-manifest", type=Path, required=True)
    grafted_boundary.add_argument("--mode-source", type=Path, required=True)
    grafted_boundary.add_argument("--chemical-definition", type=Path, required=True)
    grafted_boundary.add_argument("--output-dir", type=Path, required=True)
    boundary_audit = sub.add_parser(
        "audit-dna-boundary-replicates",
        help="Compare two or more hash-linked 1N4E boundary candidates without reflection.",
    )
    boundary_audit.add_argument("--manifest", action="append", type=Path, required=True)
    boundary_audit.add_argument("--output", type=Path, required=True)
    stereo_candidates = sub.add_parser(
        "build-tt-cpd-stereo-candidates",
        help="Build all eight review-only ordered TT-CPD model candidates.",
    )
    stereo_candidates.add_argument("--reference-dir", type=Path, required=True)
    stereo_candidates.add_argument("--output-dir", type=Path, required=True)
    stereo_audit = sub.add_parser(
        "audit-tt-cpd-stereo-candidates",
        help="Audit hashes, graphs, charges, and CIP labels for all eight candidates.",
    )
    stereo_audit.add_argument("--series-manifest", type=Path, required=True)
    stereo_audit.add_argument("--output", type=Path, required=True)
    openbabel_audit = sub.add_parser(
        "audit-tt-cpd-stereo-openbabel",
        help="Cross-check all eight candidate stereographs with independent Open Babel.",
    )
    openbabel_audit.add_argument("--series-manifest", type=Path, required=True)
    openbabel_audit.add_argument("--candidate-audit", type=Path, required=True)
    openbabel_audit.add_argument("--openbabel", type=Path, required=True)
    openbabel_audit.add_argument("--output", type=Path, required=True)
    definition_candidate = sub.add_parser(
        "build-tt-cpd-definition-candidate",
        help="Build a gate-neutral chemical-definition review artifact for one TT-CPD.",
    )
    definition_candidate.add_argument("--product-id", required=True)
    definition_candidate.add_argument("--candidate-manifest", type=Path, required=True)
    definition_candidate.add_argument("--candidate-audit", type=Path, required=True)
    definition_candidate.add_argument("--independent-audit", type=Path, required=True)
    definition_candidate.add_argument("--output", type=Path, required=True)
    definition_review = sub.add_parser(
        "build-tt-cpd-definition-review-packet",
        help="Collate all seven noncanonical candidates for independent human review.",
    )
    definition_review.add_argument(
        "--definition-candidate", type=Path, action="append", required=True
    )
    definition_review.add_argument("--candidate-audit", type=Path, required=True)
    definition_review.add_argument("--independent-audit", type=Path, required=True)
    definition_review.add_argument(
        "--frequency-audit", type=Path, action="append", default=[]
    )
    definition_review.add_argument(
        "--equivalent-hessian-reference", type=Path, action="append", default=[]
    )
    definition_review.add_argument("--output-dir", type=Path, required=True)
    review_audit = sub.add_parser(
        "audit-tt-cpd-definition-review",
        help=(
            "Revalidate completed human decisions and released-schema definitions "
            "without advancing registry gates."
        ),
    )
    review_audit.add_argument("--packet", type=Path, required=True)
    review_audit.add_argument(
        "--reviewed-definition",
        action="append",
        default=[],
        metavar="PRODUCT_ID=PATH",
        help="Required once for every APPROVE decision.",
    )
    review_audit.add_argument(
        "--decision-evidence",
        action="append",
        default=[],
        metavar="PRODUCT_ID=PATH",
        help="Required once for every REJECT or REVISE decision.",
    )
    review_audit.add_argument("--output", type=Path, required=True)
    visual_review = sub.add_parser(
        "ingest-visual-definition-review",
        help=(
            "Materialize current exact-geometry UI decisions into gate-neutral "
            "reviewed definitions and a formal ingestion audit."
        ),
    )
    visual_review.add_argument("--packet", type=Path, required=True)
    visual_review.add_argument("--visual-decisions", type=Path, required=True)
    visual_review.add_argument("--source-asset-template", type=Path, required=True)
    visual_review.add_argument(
        "--structural-reference-manifest", type=Path, required=True
    )
    visual_review.add_argument("--output-dir", type=Path, required=True)
    boundary_review = sub.add_parser(
        "ingest-visual-boundary-review",
        help=(
            "Bind a current approved UI decision to one DNA-boundary candidate "
            "before any QM execution."
        ),
    )
    boundary_review.add_argument("--candidate-manifest", type=Path, required=True)
    boundary_review.add_argument("--visual-decisions", type=Path, required=True)
    boundary_review.add_argument("--output", type=Path, required=True)
    boundary_screen = sub.add_parser(
        "screen-dna-boundary-model",
        help=(
            "Apply exact graph, charge, chirality, and independent-replicate metrics "
            "to authorize boundary-model QM evidence generation only."
        ),
    )
    boundary_screen.add_argument("--candidate-manifest", type=Path, required=True)
    boundary_screen.add_argument("--replicate-audit", type=Path, required=True)
    boundary_screen.add_argument("--policy", type=Path)
    boundary_screen.add_argument("--output", type=Path, required=True)
    grafted_boundary_screen = sub.add_parser(
        "screen-grafted-dna-boundary-model",
        help=(
            "Apply exact-graph, proper-rotation, clash, chirality, and replicate "
            "QM-input checks to a grafted product boundary."
        ),
    )
    grafted_boundary_screen.add_argument(
        "--candidate-manifest", type=Path, required=True
    )
    grafted_boundary_screen.add_argument("--replicate-audit", type=Path, required=True)
    grafted_boundary_screen.add_argument("--policy", type=Path)
    grafted_boundary_screen.add_argument("--output", type=Path, required=True)
    flexible_boundary_seed = sub.add_parser(
        "build-flexibly-relaxed-dna-boundary-seed",
        help="Relax a rigid graft around a fixed product core for QM input only.",
    )
    flexible_boundary_seed.add_argument(
        "--rigid-graft-manifest", type=Path, required=True
    )
    flexible_boundary_seed.add_argument("--output-dir", type=Path, required=True)
    flexible_boundary_seed.add_argument("--policy", type=Path)
    flexible_boundary_seed.add_argument("--maximum-iterations", type=int, default=4000)
    conformer_visual_review = sub.add_parser(
        "ingest-visual-conformer-review",
        help=(
            "Translate complete current UI conformer decisions into audited, "
            "gate-neutral reviewed plans."
        ),
    )
    conformer_visual_review.add_argument("--review-index", type=Path, required=True)
    conformer_visual_review.add_argument("--visual-decisions", type=Path, required=True)
    conformer_visual_review.add_argument("--output-dir", type=Path, required=True)
    conformer_visual_review.add_argument(
        "--product-id",
        action="append",
        default=[],
        help="Limit ingestion to one or more products; omit for all indexed products.",
    )
    minimum_definition = sub.add_parser(
        "build-minimum-backed-definition-candidate",
        help=(
            "Replace initial ring coordinates with a direct or equivalence-audited "
            "QM minimum while retaining review-only status."
        ),
    )
    minimum_definition.add_argument("--definition-candidate", type=Path, required=True)
    minimum_definition.add_argument("--minimum-evidence", type=Path, required=True)
    minimum_definition.add_argument("--optimized-xyz", type=Path)
    minimum_definition.add_argument("--optimized-model-audit", type=Path)
    minimum_definition.add_argument("--frequency-job-manifest", type=Path)
    minimum_definition.add_argument("--output", type=Path, required=True)
    generate = sub.add_parser(
        "generate-qm-job", help="Generate a hashed Psi4 job from a model XYZ."
    )
    generate.add_argument("--product-id", required=True)
    generate.add_argument("--model-id", required=True)
    generate.add_argument("--xyz", type=Path, required=True)
    generate.add_argument("--atom-map", type=Path)
    generate.add_argument("--model-manifest", type=Path)
    generate.add_argument("--parent-manifest", type=Path)
    generate.add_argument(
        "--kind",
        choices=(
            "geometry_optimization",
            "frequency",
            "electrostatic_properties",
            "conformer_single_point",
        ),
        required=True,
    )
    generate.add_argument("--charge", type=int, required=True)
    generate.add_argument("--multiplicity", type=int, default=1)
    generate.add_argument("--memory-gib", type=int, default=8)
    generate.add_argument("--threads", type=int, default=8)
    generate.add_argument("--output-dir", type=Path, required=True)
    retry = sub.add_parser(
        "retry-geometry-job",
        help="Continue a hash-valid optimizer iteration-limit failure without loosening convergence.",
    )
    retry.add_argument("--failed-job-dir", type=Path, required=True)
    retry.add_argument("--maximum-iterations", type=int, default=100)
    retry.add_argument("--output-dir", type=Path, required=True)
    water = sub.add_parser(
        "generate-water-job",
        help="Generate one reviewed fixed-geometry water-interaction target.",
    )
    water.add_argument("--product-id", required=True)
    water.add_argument("--model-id", required=True)
    water.add_argument("--model-xyz", type=Path, required=True)
    water.add_argument("--water-xyz", type=Path, required=True)
    water.add_argument("--parent-manifest", type=Path, required=True)
    water.add_argument("--atom-map", type=Path, required=True)
    water.add_argument("--probe-id", required=True)
    water.add_argument("--target-atom", required=True)
    water.add_argument("--probe-atom", choices=("O", "H1", "H2"), required=True)
    water.add_argument("--charge", type=int, default=0)
    water.add_argument("--multiplicity", type=int, default=1)
    water.add_argument("--memory-gib", type=int, default=8)
    water.add_argument("--threads", type=int, default=8)
    water.add_argument("--scf-type", choices=("df", "direct"))
    water.add_argument("--calibration-role", choices=("candidate", "reference"))
    water.add_argument("--output-dir", type=Path, required=True)
    torsion = sub.add_parser(
        "generate-torsion-job",
        help="Generate one constrained-relaxation point from a reviewed scan plan.",
    )
    torsion.add_argument("--scan-plan", type=Path, required=True)
    torsion.add_argument("--point-id", required=True)
    torsion.add_argument("--xyz", type=Path, required=True)
    torsion.add_argument("--memory-gib", type=int, default=8)
    torsion.add_argument("--threads", type=int, default=8)
    torsion.add_argument("--output-dir", type=Path, required=True)
    conformer_source = sub.add_parser(
        "build-coupled-conformer-mode-source",
        help=(
            "Expose an audited minimum Hessian for conformer selection without "
            "creating parameter-fit targets."
        ),
    )
    source_evidence = conformer_source.add_mutually_exclusive_group(required=True)
    source_evidence.add_argument("--frequency-job-dir", type=Path)
    source_evidence.add_argument("--equivalent-hessian-reference", type=Path)
    conformer_source.add_argument("--model-graph", type=Path, required=True)
    conformer_source.add_argument("--atom-map", type=Path, required=True)
    conformer_source.add_argument(
        "--stereochemistry-evidence", type=Path, required=True
    )
    conformer_source.add_argument("--output", type=Path, required=True)
    conformer_candidates = sub.add_parser(
        "build-coupled-conformer-candidates",
        help="Propose gate-neutral coupled distortions from an audited minimum Hessian.",
    )
    candidate_source = conformer_candidates.add_mutually_exclusive_group(required=True)
    candidate_source.add_argument("--hessian-targets", type=Path)
    candidate_source.add_argument("--mode-source", type=Path)
    conformer_candidates.add_argument("--model-graph", type=Path, required=True)
    conformer_candidates.add_argument("--atom-map", type=Path, required=True)
    conformer_candidates.add_argument(
        "--stereochemistry-evidence", type=Path, required=True
    )
    conformer_candidates.add_argument("--active-atom", action="append", required=True)
    conformer_candidates.add_argument("--mode-pairs", type=int, default=4)
    conformer_candidates.add_argument(
        "--amplitude-angstrom", type=float, action="append", default=None
    )
    conformer_candidates.add_argument("--output-dir", type=Path, required=True)
    conformer_screen = sub.add_parser(
        "screen-coupled-conformer-rank",
        help="Estimate candidate fit-rank gains with OpenMM before expensive QM.",
    )
    conformer_screen.add_argument("--fit-basis-manifest", type=Path, required=True)
    conformer_screen.add_argument(
        "--baseline-response-manifest", type=Path, required=True
    )
    conformer_screen.add_argument("--candidate-manifest", type=Path, required=True)
    conformer_screen.add_argument("--candidate-id", action="append", default=None)
    conformer_screen.add_argument("--step-angstrom", type=float, default=1.0e-4)
    conformer_screen.add_argument("--relative-threshold", type=float, default=1.0e-8)
    conformer_screen.add_argument("--output-dir", type=Path, required=True)
    periodicity_compare = sub.add_parser(
        "compare-periodicity-rank-screens",
        help="Collate a gate-neutral torsion-complexity ladder for later QM validation.",
    )
    periodicity_compare.add_argument(
        "--rank-screen", type=Path, action="append", required=True
    )
    periodicity_compare.add_argument("--output", type=Path, required=True)
    conformer_review = sub.add_parser(
        "build-coupled-conformer-review",
        help="Measure coupled conformers and emit an explicit human-review packet.",
    )
    conformer_review.add_argument("--product-id", required=True)
    conformer_review.add_argument("--model-id", required=True)
    review_reference = conformer_review.add_mutually_exclusive_group(required=True)
    review_reference.add_argument("--optimized-audit", type=Path)
    review_reference.add_argument("--mode-source", type=Path)
    conformer_review.add_argument(
        "--reference-geometry",
        type=Path,
        help="Byte-identical relocated optimized XYZ when its declared path is stale.",
    )
    conformer_review.add_argument("--model-graph", type=Path, required=True)
    conformer_review.add_argument("--atom-map", type=Path, required=True)
    conformer_review.add_argument(
        "--stereochemistry-evidence", type=Path, required=True
    )
    review_candidates = conformer_review.add_mutually_exclusive_group(required=True)
    review_candidates.add_argument("--candidate-xyz", type=Path, action="append")
    review_candidates.add_argument("--candidate-manifest", type=Path)
    conformer_review.add_argument(
        "--candidate-selection-policy",
        choices=("top-two-modes-both-signs-largest-amplitude-v1",),
    )
    conformer_review.add_argument("--rank-screen", type=Path)
    conformer_review.add_argument("--output", type=Path, required=True)
    conformer_review_index = sub.add_parser(
        "build-coupled-conformer-review-index",
        help="Revalidate and summarize multiple pristine conformer-review plans.",
    )
    conformer_review_index.add_argument(
        "--review-plan", type=Path, action="append", required=True
    )
    conformer_review_index.add_argument("--output-dir", type=Path, required=True)
    conformer_review_visualization = sub.add_parser(
        "build-coupled-conformer-review-visualization",
        help="Build static multi-model PDBs for human review; never a trajectory.",
    )
    conformer_review_visualization.add_argument(
        "--review-index", type=Path, required=True
    )
    conformer_review_visualization.add_argument(
        "--output-dir", type=Path, required=True
    )
    conformer_review_decisions = sub.add_parser(
        "build-coupled-conformer-review-decisions",
        help="Create a concise human-decision overlay without editing source plans.",
    )
    conformer_review_decisions.add_argument("--review-index", type=Path, required=True)
    conformer_review_decisions.add_argument("--output", type=Path, required=True)
    conformer_review_apply = sub.add_parser(
        "apply-coupled-conformer-review-decisions",
        help="Revalidate a completed decision overlay and materialize reviewed plans.",
    )
    conformer_review_apply.add_argument("--decisions", type=Path, required=True)
    conformer_review_apply.add_argument("--output-dir", type=Path, required=True)
    conformer_review_audit = sub.add_parser(
        "audit-coupled-conformer-review",
        help="Revalidate a completed human conformer review and write a neutral receipt.",
    )
    conformer_review_audit.add_argument("--plan", type=Path, required=True)
    conformer_review_audit.add_argument("--output", type=Path, required=True)
    quantitative_conformer_screen = sub.add_parser(
        "screen-coupled-conformer-plan",
        help=(
            "Apply the hash-pinned quantitative QM-input policy to a pristine "
            "coupled-conformer plan; this authorizes evidence generation only."
        ),
    )
    quantitative_conformer_screen.add_argument("--plan", type=Path, required=True)
    quantitative_conformer_screen.add_argument("--policy", type=Path)
    quantitative_conformer_screen.add_argument("--output", type=Path, required=True)
    fixed_hessian = sub.add_parser(
        "generate-fixed-geometry-hessian",
        help="Generate gradient/full-Hessian QM input for one reviewed conformer.",
    )
    fixed_hessian.add_argument("--plan", type=Path, required=True)
    fixed_hessian.add_argument("--conformer-id", required=True)
    fixed_hessian.add_argument("--charge", type=int, required=True)
    fixed_hessian.add_argument("--multiplicity", type=int, default=1)
    fixed_hessian.add_argument("--memory-gib", type=int, default=8)
    fixed_hessian.add_argument("--threads", type=int, default=8)
    fixed_hessian.add_argument("--output-dir", type=Path, required=True)
    fixed_audit = sub.add_parser(
        "audit-fixed-geometry-hessian",
        help="Audit reviewed-coordinate QM gradient and full Cartesian Hessian outputs.",
    )
    fixed_audit.add_argument("--job-dir", type=Path, required=True)
    fixed_targets = sub.add_parser(
        "build-fixed-geometry-hessian-targets",
        help="Build a gate-neutral nonstationary force/Hessian target bundle.",
    )
    fixed_targets.add_argument("--job-dir", type=Path, required=True)
    fixed_targets.add_argument("--output", type=Path, required=True)
    water_audit = sub.add_parser(
        "audit-water-series",
        help="Audit a completed, bracketed CHARMM water-interaction distance series.",
    )
    water_audit.add_argument("--job-dir", type=Path, action="append", required=True)
    water_audit.add_argument("--output", type=Path, required=True)
    water_scf_audit = sub.add_parser(
        "audit-water-scf-calibration",
        help="Compare paired identical-geometry DF and DIRECT water targets.",
    )
    water_scf_audit.add_argument("--job-dir", type=Path, action="append", required=True)
    water_scf_audit.add_argument("--output", type=Path, required=True)
    water_series = sub.add_parser(
        "build-water-series",
        help="Generate dense TIP3P interaction jobs from a reviewed site plan.",
    )
    water_series.add_argument("--plan", type=Path, required=True)
    water_series.add_argument("--model-xyz", type=Path, required=True)
    water_series.add_argument("--parent-manifest", type=Path, required=True)
    water_series.add_argument("--memory-gib", type=int, default=4)
    water_series.add_argument("--threads", type=int, default=4)
    water_series.add_argument("--output-dir", type=Path, required=True)
    run = sub.add_parser(
        "run-qm-job", help="Run one generated Psi4 job without overwriting evidence."
    )
    run.add_argument("--job-dir", type=Path, required=True)
    run.add_argument("--psi4", type=Path, required=True)
    run.add_argument("--scratch-dir", type=Path, required=True)
    distributed_prepare = sub.add_parser(
        "prepare-distributed-hessian",
        help="Export a frequency job as immutable displaced-gradient QCSchema tasks.",
    )
    distributed_prepare.add_argument("--job-dir", type=Path, required=True)
    distributed_prepare.add_argument("--output-dir", type=Path, required=True)
    materialize_frequency = sub.add_parser(
        "materialize-frequency-job-provenance",
        help="Copy source geometry and parent audit into a relocatable frequency job.",
    )
    materialize_frequency.add_argument("--job-dir", type=Path, required=True)
    materialize_frequency.add_argument(
        "--source-xyz",
        type=Path,
        help="Relocated byte-identical source geometry when the declared path is stale.",
    )
    materialize_frequency.add_argument(
        "--parent-manifest",
        type=Path,
        help="Relocated byte-identical optimization audit when the declared path is stale.",
    )
    checkpoint_hessian = sub.add_parser(
        "checkpoint-distributed-hessian",
        help="Copy complete task pairs into a distinct byte-identical plan tree.",
    )
    checkpoint_hessian.add_argument("--source-plan", type=Path, required=True)
    checkpoint_hessian.add_argument("--destination-plan", type=Path, required=True)
    checkpoint_hessian.add_argument("--output", type=Path, required=True)
    reconcile_distributed = sub.add_parser(
        "reconcile-distributed-fixed-hessian-results",
        help=(
            "Reuse completed task pairs only when regenerated fixed-response plans "
            "have byte-identical QCSchema inputs and differ solely in policy provenance."
        ),
    )
    reconcile_distributed.add_argument("--source-plan", type=Path, required=True)
    reconcile_distributed.add_argument("--destination-plan", type=Path, required=True)
    reconcile_distributed.add_argument("--output", type=Path, required=True)
    distributed_run = sub.add_parser(
        "run-distributed-hessian-task",
        help="Run one hash-linked displaced-gradient task in the pinned QM environment.",
    )
    distributed_run.add_argument("--plan", type=Path, required=True)
    distributed_run.add_argument("--task-id", required=True)
    distributed_run.add_argument("--scratch-dir", type=Path, required=True)
    distributed_run.add_argument("--threads", type=int)
    distributed_run.add_argument("--memory-gib", type=int)
    distributed_assemble = sub.add_parser(
        "assemble-distributed-hessian",
        help="Recreate, hash-audit, and assemble all displaced-gradient results.",
    )
    distributed_assemble.add_argument("--job-dir", type=Path, required=True)
    distributed_assemble.add_argument("--plan", type=Path, required=True)
    distributed_assemble.add_argument("--output", type=Path, required=True)
    fixed_distributed_prepare = sub.add_parser(
        "prepare-distributed-fixed-hessian",
        help=(
            "Export a reviewed fixed-geometry job as immutable displaced-gradient "
            "QCSchema tasks."
        ),
    )
    fixed_distributed_prepare.add_argument("--job-dir", type=Path, required=True)
    fixed_distributed_prepare.add_argument("--output-dir", type=Path, required=True)
    fixed_distributed_assemble = sub.add_parser(
        "assemble-distributed-fixed-hessian",
        help=("Recreate and hash-audit a reviewed conformer's force/Hessian response."),
    )
    fixed_distributed_assemble.add_argument("--job-dir", type=Path, required=True)
    fixed_distributed_assemble.add_argument("--plan", type=Path, required=True)
    fixed_distributed_assemble.add_argument("--output", type=Path, required=True)
    run_series = sub.add_parser(
        "run-qm-series",
        help="Run or verify a hash-linked QM series with bounded parallelism.",
    )
    run_series.add_argument("--series-manifest", type=Path, required=True)
    run_series.add_argument("--psi4", type=Path, required=True)
    run_series.add_argument("--scratch-root", type=Path, required=True)
    run_series.add_argument("--max-parallel", type=int, default=1)
    build_series = sub.add_parser(
        "build-qm-series",
        help="Hash-link generated jobs of one kind into a resumable series.",
    )
    build_series.add_argument("--job-dir", type=Path, action="append", required=True)
    build_series.add_argument("--output", type=Path, required=True)
    audit = sub.add_parser(
        "audit-optimized-model",
        help="Check atom identity and stereochemistry after a completed optimization.",
    )
    audit.add_argument("--job-dir", type=Path, required=True)
    equivalence = sub.add_parser(
        "audit-model-equivalence",
        help="Audit optimized N-methyl models under ordered endpoint exchange.",
    )
    equivalence.add_argument("--first-job-dir", type=Path, required=True)
    equivalence.add_argument("--second-job-dir", type=Path, required=True)
    equivalence.add_argument("--independent-stereo-audit", type=Path, required=True)
    equivalence.add_argument("--output", type=Path, required=True)
    equivalent_hessian = sub.add_parser(
        "build-equivalent-hessian-reference",
        help="Bind a passed source Hessian to a proved endpoint-exchange atom mapping.",
    )
    equivalent_hessian.add_argument(
        "--source-frequency-job-dir", type=Path, required=True
    )
    equivalent_hessian.add_argument("--equivalence-audit", type=Path, required=True)
    equivalent_hessian.add_argument("--target-product-id", required=True)
    equivalent_hessian.add_argument("--output", type=Path, required=True)
    frequency_audit = sub.add_parser(
        "audit-frequency",
        help="Verify mode completeness and absence of imaginary frequencies.",
    )
    frequency_audit.add_argument("--job-dir", type=Path, required=True)
    hessian_targets = sub.add_parser(
        "build-hessian-targets",
        help="Bind an audited QM Hessian to reviewed stable-key bonded targets.",
    )
    hessian_targets.add_argument("--frequency-job-dir", type=Path, required=True)
    hessian_targets.add_argument("--output", type=Path, required=True)
    charge_targets = sub.add_parser(
        "build-charge-targets",
        help="Combine audited dipole/water evidence into a fail-closed charge-fit bundle.",
    )
    charge_targets.add_argument("--electrostatic-audit", type=Path, required=True)
    charge_targets.add_argument(
        "--water-audit", type=Path, action="append", required=True
    )
    charge_targets.add_argument("--scf-calibration-audit", type=Path, required=True)
    charge_targets.add_argument("--stereo-candidate-audit", type=Path, required=True)
    charge_targets.add_argument("--esp-audit", type=Path)
    charge_targets.add_argument("--initial-charge-guess", type=Path, required=True)
    charge_targets.add_argument("--atom-map", type=Path, required=True)
    charge_targets.add_argument("--output", type=Path, required=True)
    electrostatic_audit = sub.add_parser(
        "audit-electrostatics",
        help="Audit an HF dipole target at a passed optimized geometry.",
    )
    electrostatic_audit.add_argument("--job-dir", type=Path, required=True)
    esp = sub.add_parser(
        "generate-esp-job",
        help="Generate a deterministic HF electrostatic-potential grid job.",
    )
    esp.add_argument("--product-id", required=True)
    esp.add_argument("--model-id", required=True)
    esp.add_argument("--xyz", type=Path, required=True)
    esp.add_argument("--atom-map", type=Path, required=True)
    esp.add_argument("--parent-manifest", type=Path, required=True)
    esp.add_argument("--charge", type=int, default=0)
    esp.add_argument("--multiplicity", type=int, default=1)
    esp.add_argument("--memory-gib", type=int, default=4)
    esp.add_argument("--threads", type=int, default=4)
    esp.add_argument("--output-dir", type=Path, required=True)
    esp_audit = sub.add_parser("audit-esp", help="Hash-audit a completed GRID_ESP job.")
    esp_audit.add_argument("--job-dir", type=Path, required=True)
    template = sub.add_parser(
        "build-coordinate-template",
        help="Build a non-released product template from passed QM audits.",
    )
    template.add_argument("--geometry-job-dir", type=Path, required=True)
    template.add_argument("--frequency-job-dir", type=Path, required=True)
    template.add_argument("--version", required=True)
    template.add_argument("--output", type=Path, required=True)
    reconcile = sub.add_parser(
        "reconcile-qm-run",
        help="Reparse immutable Psi4 output into a separate correction record.",
    )
    reconcile.add_argument("--job-dir", type=Path, required=True)
    inventory = sub.add_parser(
        "inventory-bonded-terms",
        help="Enumerate graph-generated and locally affected bonded terms.",
    )
    inventory.add_argument("--product", default="TT-CPD")
    inventory.add_argument("--stereochemistry", default="cis-syn")
    inventory.add_argument("--output", type=Path, required=True)
    charges = sub.add_parser(
        "extract-initial-charges",
        help="Map pinned CGenFF 1MTH charges as a non-final fitting guess.",
    )
    charges.add_argument("--cgenff-topology", type=Path, required=True)
    charges.add_argument("--model-manifest", type=Path, required=True)
    charges.add_argument("--output", type=Path, required=True)
    atom_types = sub.add_parser(
        "build-atom-type-candidates",
        help="Map pinned saturated-thymine/cyclobutane analogs without selecting final types.",
    )
    atom_types.add_argument("--cgenff-topology", type=Path, required=True)
    atom_types.add_argument("--model-manifest", type=Path, required=True)
    atom_types.add_argument("--output", type=Path, required=True)
    nonbonded_fit = sub.add_parser(
        "fit-nonbonded-hypotheses",
        help="Fit and compare explicit gate-neutral charge/LJ transfer hypotheses.",
    )
    nonbonded_fit.add_argument("--charge-targets", type=Path, required=True)
    nonbonded_fit.add_argument("--atom-type-plan", type=Path, required=True)
    nonbonded_fit.add_argument("--cgenff-parameters", type=Path, required=True)
    nonbonded_fit.add_argument("--nucleic-parameters", type=Path)
    nonbonded_fit.add_argument(
        "--hypotheses",
        type=Path,
        default=None,
        help="Optional reviewed hypothesis JSON.",
    )
    nonbonded_fit.add_argument("--output", type=Path, required=True)
    coverage = sub.add_parser(
        "audit-parameter-coverage",
        help="Match explicit type hypotheses against pinned CHARMM bonded terms.",
    )
    coverage.add_argument("--atom-type-plan", type=Path, required=True)
    coverage.add_argument("--hypotheses", type=Path, required=True)
    coverage.add_argument("--cgenff-parameters", type=Path, required=True)
    coverage.add_argument("--nucleic-parameters", type=Path, required=True)
    coverage.add_argument("--output", type=Path, required=True)
    model_coverage = sub.add_parser(
        "audit-model-parameter-coverage",
        help="Audit every bonded term in one explicit capped-QM model hypothesis.",
    )
    model_coverage.add_argument("--model-manifest", type=Path, required=True)
    model_coverage.add_argument("--nonbonded-fit", type=Path, required=True)
    model_coverage.add_argument("--hypothesis-id", required=True)
    model_coverage.add_argument("--cgenff-parameters", type=Path, required=True)
    model_coverage.add_argument("--nucleic-parameters", type=Path)
    model_coverage.add_argument("--output", type=Path, required=True)
    bonded_fit_plan = sub.add_parser(
        "build-bonded-fit-plan",
        help="Join graph, Hessian, coverage, and stereochemistry into a null-valued fit plan.",
    )
    bonded_fit_plan.add_argument("--model-manifest", type=Path, required=True)
    bonded_fit_plan.add_argument("--hessian-targets", type=Path, required=True)
    bonded_fit_plan.add_argument("--model-coverage", type=Path, required=True)
    bonded_fit_plan.add_argument(
        "--improper-convention-audit", type=Path, required=True
    )
    bonded_fit_plan.add_argument("--output", type=Path, required=True)
    bonded_refit = sub.add_parser(
        "promote-bonded-refit-terms",
        help=(
            "Promote a policy-selected complete ring block from transferable CHARMM "
            "terms into a null-valued coupled refit basis."
        ),
    )
    bonded_refit.add_argument("--fit-plan", type=Path, required=True)
    bonded_refit.add_argument("--policy", type=Path)
    bonded_refit.add_argument("--output", type=Path, required=True)
    openmm_skeleton = sub.add_parser(
        "build-openmm-candidate-skeleton",
        help="Evaluate covered CHARMM terms while explicitly omitting every missing term.",
    )
    openmm_skeleton.add_argument("--fit-plan", type=Path, required=True)
    openmm_skeleton.add_argument("--nonbonded-fit", type=Path, required=True)
    openmm_skeleton.add_argument("--cgenff-topology", type=Path, required=True)
    openmm_skeleton.add_argument("--cgenff-parameters", type=Path, required=True)
    openmm_skeleton.add_argument("--nucleic-topology", type=Path)
    openmm_skeleton.add_argument("--nucleic-parameters", type=Path)
    openmm_skeleton.add_argument("--output-dir", type=Path, required=True)
    openmm_fit_basis = sub.add_parser(
        "build-openmm-linear-fit-basis",
        help="Add zero-valued bonded fitting coordinates to an incomplete OpenMM model.",
    )
    openmm_fit_basis.add_argument("--skeleton-manifest", type=Path, required=True)
    openmm_fit_basis.add_argument("--fit-plan", type=Path, required=True)
    openmm_fit_basis.add_argument(
        "--torsion-periodicity",
        type=int,
        action="append",
        dest="torsion_periodicities",
    )
    openmm_fit_basis.add_argument(
        "--improper-equilibrium-mode",
        choices=("fit_offset", "fixed_qm_reference"),
        default="fit_offset",
    )
    openmm_fit_basis.add_argument(
        "--angle-urey-bradley-mode",
        choices=("fit", "omit"),
        default="fit",
        help=(
            "Fit optional angle 1-3 Urey-Bradley terms or omit them as an explicit "
            "candidate model-form hypothesis."
        ),
    )
    openmm_fit_basis.add_argument("--output-dir", type=Path, required=True)
    openmm_response = sub.add_parser(
        "build-openmm-linear-response",
        help="Differentiate a fit basis into force and coupled-Hessian response arrays.",
    )
    openmm_response.add_argument("--fit-basis-manifest", type=Path, required=True)
    openmm_response.add_argument("--hessian-targets", type=Path, required=True)
    openmm_response.add_argument("--step-angstrom", type=float, default=1.0e-4)
    openmm_response.add_argument("--output-dir", type=Path, required=True)
    identifiability = sub.add_parser(
        "audit-openmm-fit-identifiability",
        help="Report unresolved linear bonded-fit directions without fitting values.",
    )
    identifiability.add_argument("--response-manifest", type=Path, required=True)
    identifiability.add_argument("--fit-plan", type=Path, required=True)
    identifiability.add_argument("--relative-threshold", type=float, default=1.0e-8)
    identifiability.add_argument("--output", type=Path, required=True)
    response_campaign = sub.add_parser(
        "build-openmm-response-campaign",
        help=(
            "Assemble disjoint, hash-linked training/holdout response datasets without "
            "fitting values."
        ),
    )
    response_campaign.add_argument(
        "--training-response", type=Path, action="append", required=True
    )
    response_campaign.add_argument(
        "--validation-response", type=Path, action="append", required=True
    )
    response_campaign.add_argument("--relative-threshold", type=float, default=1.0e-8)
    response_campaign.add_argument("--output-dir", type=Path, required=True)
    fit_specification = sub.add_parser(
        "build-response-fit-specification",
        help="Create a human-review template for bounded regularized response fitting.",
    )
    fit_specification.add_argument("--campaign", type=Path, required=True)
    fit_specification.add_argument("--output", type=Path, required=True)
    quantitative_fit_specification = sub.add_parser(
        "build-quantitative-response-fit-specification",
        help=(
            "Apply the hash-pinned training-only normalization, physical bounds, and "
            "ridge policy without releasing parameters."
        ),
    )
    quantitative_fit_specification.add_argument("--campaign", type=Path, required=True)
    quantitative_fit_specification.add_argument("--policy", type=Path)
    quantitative_fit_specification.add_argument("--output", type=Path, required=True)
    fit_evaluation = sub.add_parser(
        "evaluate-response-fit",
        help="Fit a reviewed ridge grid and report untouched holdout errors without selection.",
    )
    fit_evaluation.add_argument("--campaign", type=Path, required=True)
    fit_evaluation.add_argument("--specification", type=Path, required=True)
    fit_evaluation.add_argument("--output-dir", type=Path, required=True)
    geometry_refinement = sub.add_parser(
        "refine-response-fit-geometry",
        help=(
            "Refine a selected response fit against the QM minimum while reporting "
            "untouched holdout response and retaining a neutral release gate."
        ),
    )
    geometry_refinement.add_argument("--selected-fit", type=Path, required=True)
    geometry_refinement.add_argument("--policy", type=Path)
    geometry_refinement.add_argument("--output-dir", type=Path, required=True)
    geometry_audit = sub.add_parser(
        "audit-geometry-refinement",
        help=(
            "Re-minimize and finite-difference a passing geometry-refined candidate "
            "without advancing its release gate."
        ),
    )
    geometry_audit.add_argument("--refinement", type=Path, required=True)
    geometry_audit.add_argument("--policy", type=Path)
    geometry_audit.add_argument("--output", type=Path, required=True)
    geometry_transform = sub.add_parser(
        "transform-geometry-refinement-to-charmm",
        help="Transform an independently audited geometry refinement to CHARMM terms.",
    )
    geometry_transform.add_argument("--refinement", type=Path, required=True)
    geometry_transform.add_argument("--audit", type=Path, required=True)
    geometry_transform.add_argument("--output", type=Path, required=True)
    fit_comparison = sub.add_parser(
        "compare-response-fit-evaluations",
        help="Collate like-for-like nested-hypothesis holdout results without selection.",
    )
    fit_comparison.add_argument(
        "--evaluation", type=Path, action="append", required=True
    )
    fit_comparison.add_argument("--output", type=Path, required=True)
    fit_selection = sub.add_parser(
        "build-response-fit-selection",
        help="Create a human selection form from a neutral fit comparison.",
    )
    fit_selection.add_argument("--comparison", type=Path, required=True)
    fit_selection.add_argument("--output", type=Path, required=True)
    fit_extract = sub.add_parser(
        "extract-selected-response-fit",
        help="Extract a reviewed coefficient candidate without mapping or releasing CHARMM terms.",
    )
    fit_extract.add_argument("--selection", type=Path, required=True)
    fit_extract.add_argument("--output", type=Path, required=True)
    quantitative_fit_selection = sub.add_parser(
        "select-quantitative-response-fit",
        help=(
            "Select a physical smoke-test coefficient row by the hash-pinned held-out "
            "score and regularization policy; never releases parameters."
        ),
    )
    quantitative_fit_selection.add_argument("--evaluation", type=Path, required=True)
    quantitative_fit_selection.add_argument("--policy", type=Path)
    quantitative_fit_selection.add_argument("--output", type=Path, required=True)
    fit_transform = sub.add_parser(
        "transform-selected-fit-to-charmm",
        help="Apply the exact linear-basis inverse without emitting a parameter file.",
    )
    fit_transform.add_argument("--selected-candidate", type=Path, required=True)
    fit_transform.add_argument("--output", type=Path, required=True)
    relative_energy_audit = sub.add_parser(
        "audit-refined-relative-energies",
        help=(
            "Compare a geometry-refined OpenMM candidate with immutable fixed-geometry "
            "QM relative-energy targets without releasing it."
        ),
    )
    relative_energy_audit.add_argument("--refinement", type=Path, required=True)
    relative_energy_audit.add_argument("--targets", type=Path, required=True)
    relative_energy_audit.add_argument("--output", type=Path, required=True)
    nonbonded_transfer = sub.add_parser(
        "audit-nonbonded-transfer",
        help="Test one fitted charge/LJ model against independent product water curves.",
    )
    nonbonded_transfer.add_argument("--source-fit", type=Path, required=True)
    nonbonded_transfer.add_argument("--water-collection", type=Path, required=True)
    nonbonded_transfer.add_argument("--cgenff-parameters", type=Path, required=True)
    nonbonded_transfer.add_argument("--nucleic-parameters", type=Path, required=True)
    nonbonded_transfer.add_argument("--hypothesis-id", required=True)
    nonbonded_transfer.add_argument("--output", type=Path, required=True)
    joint_nonbonded = sub.add_parser(
        "fit-joint-nonbonded-transfer",
        help="Fit one gate-neutral charge vector across independent product water curves.",
    )
    joint_nonbonded.add_argument("--source-fit", type=Path, required=True)
    joint_nonbonded.add_argument("--water-collection", type=Path, required=True)
    joint_nonbonded.add_argument(
        "--additional-water-collection",
        type=Path,
        action="append",
        default=[],
        help="Add another hash-distinct orientation to joint fitting.",
    )
    joint_nonbonded.add_argument(
        "--fit-all-water-sites",
        action="store_true",
        help="Fit every site in >=2 orientations and require later independent validation.",
    )
    joint_nonbonded.add_argument("--frequency-root", type=Path, required=True)
    joint_nonbonded.add_argument("--cgenff-parameters", type=Path, required=True)
    joint_nonbonded.add_argument("--nucleic-parameters", type=Path, required=True)
    joint_nonbonded.add_argument("--hypothesis-id", required=True)
    joint_nonbonded.add_argument(
        "--product-id",
        action="append",
        help="Limit one shared fit to this product group; repeat for grouped products.",
    )
    joint_nonbonded.add_argument("--family-policy", type=Path)
    joint_nonbonded.add_argument("--family-id")
    joint_nonbonded.add_argument("--output", type=Path, required=True)
    independent_nonbonded = sub.add_parser(
        "audit-independent-nonbonded-candidate",
        help=(
            "Test a fitted joint charge model against a water collection that was "
            "strictly excluded from fitting."
        ),
    )
    independent_nonbonded.add_argument("--candidate", type=Path, required=True)
    independent_nonbonded.add_argument(
        "--validation-collection", type=Path, required=True
    )
    independent_nonbonded.add_argument("--cgenff-parameters", type=Path, required=True)
    independent_nonbonded.add_argument("--nucleic-parameters", type=Path, required=True)
    independent_nonbonded.add_argument("--output", type=Path, required=True)
    workbook = sub.add_parser(
        "build-parameter-workbook",
        help="Create a null-filled, non-releasable CHARMM fitting workbook.",
    )
    workbook.add_argument("--product", default="TT-CPD")
    workbook.add_argument("--stereochemistry", default="cis-syn")
    workbook.add_argument("--initial-charge-guess", type=Path)
    workbook.add_argument("--output", type=Path, required=True)
    workbook_audit = sub.add_parser(
        "audit-parameter-workbook",
        help="Audit candidate completeness without advancing a registry gate.",
    )
    workbook_audit.add_argument("--workbook", type=Path, required=True)
    workbook_audit.add_argument(
        "--output",
        type=Path,
        help="Optional path for the machine-readable audit (refuses overwrite).",
    )
    candidate_workbook = sub.add_parser(
        "assemble-quantitative-parameter-workbook",
        help=(
            "Map a selected QM response fit and pinned CGenFF records into a "
            "non-releasing CHARMM smoke-candidate workbook."
        ),
    )
    candidate_workbook.add_argument("--fit-plan", type=Path, required=True)
    candidate_workbook.add_argument("--nonbonded-fit", type=Path, required=True)
    candidate_workbook.add_argument("--charmm-transform", type=Path, required=True)
    candidate_workbook.add_argument("--dna-boundary-model", type=Path, required=True)
    candidate_workbook.add_argument("--cgenff-topology", type=Path, required=True)
    candidate_workbook.add_argument("--cgenff-parameters", type=Path, required=True)
    candidate_workbook.add_argument("--policy", type=Path)
    candidate_workbook.add_argument("--output", type=Path, required=True)
    improper_convention = sub.add_parser(
        "audit-namd-improper-convention",
        help="Prove CHARMM signed-improper behavior with real psfgen and NAMD.",
    )
    improper_convention.add_argument("--psfgen", type=Path, required=True)
    improper_convention.add_argument("--namd", type=Path, required=True)
    improper_convention.add_argument("--output-dir", type=Path, required=True)
    charmm_export = sub.add_parser(
        "export-charmm-candidate",
        help=(
            "Render a passed reviewed workbook into gate-neutral CHARMM candidate assets."
        ),
    )
    charmm_export.add_argument("--workbook", type=Path, required=True)
    charmm_export.add_argument("--workbook-audit", type=Path, required=True)
    charmm_export.add_argument("--output-dir", type=Path, required=True)
    charmm_export.add_argument(
        "--variant-id",
        help="Stable candidate variant ID; defaults to a workbook-hash identity.",
    )
    charmm_export.add_argument(
        "--parent-candidate-manifest",
        type=Path,
        help="Hash-pin the immediate predecessor when exporting a corrected variant.",
    )
    charmm_export.add_argument(
        "--correction-policy",
        type=Path,
        help="Required with --parent-candidate-manifest for a corrected variant.",
    )
    candidate_smoke = sub.add_parser(
        "run-candidate-engine-smoke",
        help=(
            "Build and audit a gate-neutral d(TpT) candidate with real psfgen, "
            "staged minimization, and ordinary-mass 2-fs NAMD dynamics."
        ),
    )
    candidate_smoke.add_argument("--candidate-manifest", type=Path, required=True)
    candidate_smoke.add_argument("--dna-boundary-model", type=Path, required=True)
    candidate_smoke.add_argument("--nucleic-topology", type=Path, required=True)
    candidate_smoke.add_argument("--nucleic-parameters", type=Path, required=True)
    candidate_smoke.add_argument("--psfgen", type=Path, required=True)
    candidate_smoke.add_argument("--namd", type=Path, required=True)
    candidate_smoke.add_argument("--output-dir", type=Path, required=True)
    candidate_smoke.add_argument("--minimize-steps", type=int, default=2000)
    candidate_smoke.add_argument("--dynamics-steps", type=int, default=1000)
    solution_smoke = sub.add_parser(
        "run-candidate-solution-smoke",
        help=(
            "Solvate a passed gate-neutral d(TpT) candidate and run staged "
            "ordinary-mass NAMD through a 2-fs solution trajectory."
        ),
    )
    solution_smoke.add_argument("--candidate-manifest", type=Path, required=True)
    solution_smoke.add_argument("--vacuum-smoke-report", type=Path, required=True)
    solution_smoke.add_argument("--nucleic-parameters", type=Path, required=True)
    solution_smoke.add_argument("--water-parameters", type=Path, required=True)
    solution_smoke.add_argument("--ion-nbfix-parameters", type=Path, required=True)
    solution_smoke.add_argument("--namd", type=Path, required=True)
    solution_smoke.add_argument("--output-dir", type=Path, required=True)
    solution_smoke.add_argument("--padding-nm", type=float, default=1.2)
    solution_smoke.add_argument("--ion-conc-mm", type=float, default=150.0)
    solution_smoke.add_argument("--seed", type=int, default=42)
    solution_smoke.add_argument("--minimize-steps", type=int, default=5000)
    solution_smoke.add_argument("--heat-steps", type=int, default=10000)
    solution_smoke.add_argument("--dynamics-steps", type=int, default=50000)
    context_topology = sub.add_parser(
        "build-candidate-context-topology",
        help=(
            "Resolve a gate-neutral candidate patch in a real NADOC design and "
            "audit its product/reactant PSFs; coordinates remain blocked for dynamics."
        ),
    )
    context_source = context_topology.add_mutually_exclusive_group(required=True)
    context_source.add_argument("--design", type=Path)
    context_source.add_argument(
        "--fixture",
        choices=(
            "reciprocal-crossover-1xt",
            "adjacent-intrastrand",
            "antiparallel-interstrand",
        ),
        help="Deterministic topology-only validation fixture.",
    )
    context_topology.add_argument("--candidate-manifest", type=Path, required=True)
    context_topology.add_argument("--psfgen", type=Path, required=True)
    context_topology.add_argument("--output-dir", type=Path, required=True)
    context_precondition = sub.add_parser(
        "run-candidate-context-precondition",
        help=(
            "Fit a full-boundary QM product into a stable-key NADOC context, "
            "locally minimize it with real NAMD, and audit the candidate coordinate seed."
        ),
    )
    precondition_source = context_precondition.add_mutually_exclusive_group(
        required=True
    )
    precondition_source.add_argument("--design", type=Path)
    precondition_source.add_argument(
        "--fixture",
        choices=(
            "reciprocal-crossover-1xt",
            "adjacent-intrastrand",
            "antiparallel-interstrand",
        ),
    )
    context_precondition.add_argument("--candidate-manifest", type=Path, required=True)
    context_precondition.add_argument("--dna-boundary-model", type=Path, required=True)
    context_precondition.add_argument("--qm-release-report", type=Path, required=True)
    context_precondition.add_argument("--nucleic-parameters", type=Path, required=True)
    context_precondition.add_argument("--psfgen", type=Path, required=True)
    context_precondition.add_argument("--namd", type=Path, required=True)
    context_precondition.add_argument(
        "--policy",
        type=Path,
        default=Path(
            "backend/data/forcefield/photoproduct_context_precondition_policy.json"
        ),
    )
    context_precondition.add_argument("--output-dir", type=Path, required=True)
    context_solution = sub.add_parser(
        "run-candidate-context-solution-smoke",
        help=(
            "Solvate a passed stable-key context precondition and run a short "
            "ordinary-mass real-NAMD 2-fs candidate smoke."
        ),
    )
    context_solution.add_argument("--candidate-manifest", type=Path, required=True)
    context_solution.add_argument("--precondition-report", type=Path, required=True)
    context_solution.add_argument("--nucleic-parameters", type=Path, required=True)
    context_solution.add_argument("--water-parameters", type=Path, required=True)
    context_solution.add_argument("--ion-nbfix-parameters", type=Path, required=True)
    context_solution.add_argument("--namd", type=Path, required=True)
    context_solution.add_argument("--output-dir", type=Path, required=True)
    context_solution.add_argument("--padding-nm", type=float, default=1.2)
    context_solution.add_argument("--ion-conc-mm", type=float, default=150.0)
    context_solution.add_argument("--seed", type=int, default=42)
    context_solution.add_argument("--minimize-steps", type=int, default=5000)
    context_solution.add_argument("--heat-steps", type=int, default=5000)
    context_solution.add_argument("--dynamics-steps", type=int, default=5000)
    smoke = sub.add_parser(
        "prepare-namd-smoke",
        help="Prepare a hash-linked load/local-min/global-min/2-fs lesion smoke sequence.",
    )
    smoke.add_argument("--package-dir", type=Path, required=True)
    smoke.add_argument("--output-dir", type=Path, required=True)
    smoke.add_argument("--local-steps", type=int, default=500)
    smoke.add_argument("--global-steps", type=int, default=1000)
    smoke.add_argument("--dynamics-steps", type=int, default=1000)
    smoke.add_argument("--dcd-freq", type=int, default=10)
    smoke.add_argument("--mobile-radius-angstrom", type=float, default=6.0)
    smoke_audit = sub.add_parser(
        "audit-namd-smoke",
        help="Audit all staged logs and the 2-fs lesion trajectory from a smoke plan.",
    )
    smoke_audit.add_argument("--package-dir", type=Path, required=True)
    smoke_audit.add_argument("--smoke-plan", type=Path, required=True)
    smoke_audit.add_argument("--output", type=Path, required=True)
    request = sub.add_parser(
        "request", help="Add a new definition-pending photoproduct request."
    )
    request.add_argument("--id", required=True, dest="product_id")
    request.add_argument("--product", required=True)
    request.add_argument("--stereochemistry", required=True)
    request.add_argument("--label", required=True)
    request.add_argument("--context", action="append", default=[])
    attach = sub.add_parser(
        "attach-asset",
        help="Attach a curated in-tree asset by relative path and SHA-256.",
    )
    attach.add_argument("--product-id", required=True)
    attach.add_argument("--kind", required=True)
    attach.add_argument("--asset", type=Path, required=True)
    attach.add_argument(
        "--patch-name",
        help="Required only for a topology asset; exact ordered CHARMM PRES name.",
    )
    review = sub.add_parser(
        "review-gate",
        help=(
            "Review chemical identity or block a gate; quantitative gates cannot be "
            "passed by human review."
        ),
    )
    review.add_argument("--product-id", required=True)
    review.add_argument("--gate", required=True)
    review.add_argument("--status", choices=("passed", "blocked"), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--rationale", required=True)
    review.add_argument("--evidence", type=Path)
    metric_gate = sub.add_parser(
        "record-metric-gate",
        help="Pass a quantitative gate from a curated, hash-linked machine-evidence envelope.",
    )
    metric_gate.add_argument("--product-id", required=True)
    metric_gate.add_argument("--gate", required=True)
    metric_gate.add_argument("--evidence", type=Path, required=True)
    metric_gate.add_argument("--acceptance-policy", type=Path, required=True)
    qm_release = sub.add_parser(
        "build-boundary-qm-release-audits",
        help="Consolidate all-eight d(TpT) optimization/frequency evidence.",
    )
    qm_release.add_argument(
        "--optimization-campaign", type=Path, action="append", required=True
    )
    qm_release.add_argument("--frequency-campaign", type=Path, required=True)
    qm_release.add_argument("--acceptance-policy", type=Path, required=True)
    qm_release.add_argument("--output-dir", type=Path, required=True)
    boundary_fit = sub.add_parser(
        "build-boundary-fit-inputs",
        help="Join all-eight optimized d(TpT) graphs and Hessians into fit inputs.",
    )
    boundary_fit.add_argument(
        "--optimization-campaign", type=Path, action="append", required=True
    )
    boundary_fit.add_argument("--frequency-campaign", type=Path, required=True)
    boundary_fit.add_argument("--output-dir", type=Path, required=True)
    boundary_nonbonded = sub.add_parser(
        "build-boundary-nonbonded-specification",
        help="Freeze CHARMM36 d(TpT) boundary charges/types around one product fit.",
    )
    boundary_nonbonded.add_argument("--model-manifest", type=Path, required=True)
    boundary_nonbonded.add_argument("--nucleic-topology", type=Path, required=True)
    boundary_nonbonded.add_argument("--cgenff-topology", type=Path, required=True)
    boundary_nonbonded.add_argument("--cgenff-parameters", type=Path, required=True)
    boundary_nonbonded.add_argument("--policy", type=Path)
    boundary_nonbonded.add_argument("--output", type=Path, required=True)
    boundary_charge_fit = sub.add_parser(
        "fit-boundary-charges",
        help="Fit 28 product charges with fixed CHARMM36 d(TpT) boundary values.",
    )
    boundary_charge_fit.add_argument("--specification", type=Path, required=True)
    boundary_charge_fit.add_argument("--esp-audit", type=Path, required=True)
    boundary_charge_fit.add_argument(
        "--water-audit", type=Path, action="append", required=True
    )
    boundary_charge_fit.add_argument("--cgenff-parameters", type=Path, required=True)
    boundary_charge_fit.add_argument("--nucleic-parameters", type=Path, required=True)
    boundary_charge_fit.add_argument("--output", type=Path, required=True)
    boundary_charge_campaign = sub.add_parser(
        "fit-boundary-charge-campaign",
        help="Fit charges for the passed all-eight d(TpT) ESP/water campaigns.",
    )
    boundary_charge_campaign.add_argument("--fit-input-root", type=Path, required=True)
    boundary_charge_campaign.add_argument("--esp-campaign", type=Path, required=True)
    boundary_charge_campaign.add_argument("--water-campaign", type=Path, required=True)
    boundary_charge_campaign.add_argument(
        "--cgenff-parameters", type=Path, required=True
    )
    boundary_charge_campaign.add_argument(
        "--nucleic-parameters", type=Path, required=True
    )
    boundary_bonded_fit = sub.add_parser(
        "fit-boundary-bonded-response",
        help="Select a physical smoke candidate from one full d(TpT) response.",
    )
    boundary_bonded_fit.add_argument("--response-manifest", type=Path, required=True)
    boundary_bonded_fit.add_argument("--fit-plan", type=Path, required=True)
    boundary_bonded_fit.add_argument("--policy", type=Path)
    boundary_bonded_fit.add_argument("--output-dir", type=Path, required=True)
    help_trajectory = sub.add_parser(
        "build-help-trajectory",
        help="Package real hash-audited NAMD frames for the photoproduct Help viewer.",
    )
    help_trajectory.add_argument("--product-id", required=True)
    help_trajectory.add_argument("--dcd", type=Path, required=True)
    help_trajectory.add_argument("--psf", type=Path, required=True)
    help_trajectory.add_argument("--parameters", type=Path, required=True)
    help_trajectory.add_argument("--static-topology-audit", type=Path, required=True)
    help_trajectory.add_argument("--namd-smoke-report", type=Path, required=True)
    help_trajectory.add_argument("--max-frames", type=int, default=120)
    help_trajectory.add_argument("--output", type=Path, required=True)
    return parser


def _enforce_storage_root(args: argparse.Namespace) -> dict[str, Any] | None:
    """Fail before dispatch when a durable destination escapes selected storage."""

    if args.storage_root is None:
        return None
    storage = validate_photoproduct_storage_root(args.storage_root)
    root = Path(storage["storage_root"])
    resolved: dict[str, Any] = dict(storage)
    for name in (
        "cache_dir",
        "output_dir",
        "scratch_dir",
        "scratch_root",
        "fit_input_root",
        "output",
        "job_dir",
        "destination_plan",
        "plan",
        "review_index",
        "decisions",
        "series_manifest",
        "campaign",
        "specification",
        "evaluation",
        "comparison",
        "selection",
        "selected_candidate",
    ):
        value = getattr(args, name, None)
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        checked_values = []
        for item in values:
            path = item.resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                option = name.replace("_", "-")
                raise ValueError(
                    f"--{option} must be under storage root {root}"
                ) from exc
            checked_values.append(str(path))
        resolved[name] = (
            checked_values if isinstance(value, list) else checked_values[0]
        )
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _enforce_storage_root(args)
    if args.command == "doctor":
        print(json.dumps(photoproduct_toolchain_status(), indent=2))
        return 0
    if args.command == "fetch-references":
        result = fetch_reference_bundle(
            args.product, args.stereochemistry, args.cache_dir
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-charge-model":
        result = build_charge_model(
            product=args.product,
            stereochemistry=args.stereochemistry,
            reference_dir=args.reference_dir,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-dna-boundary-model-candidate":
        if len(args.endpoint_resid) != 2:
            raise ValueError("--endpoint-resid must be supplied exactly twice")
        result = build_dna_boundary_model_candidate(
            reference_dir=args.reference_dir,
            output_dir=args.output_dir,
            chain_id=args.chain,
            endpoint_resids=tuple(args.endpoint_resid),
            pdb_model=args.pdb_model,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-grafted-dna-boundary-model-candidate":
        result = build_grafted_dna_boundary_model_candidate(
            reference_manifest_path=args.reference_manifest,
            mode_source_path=args.mode_source,
            chemical_definition_path=args.chemical_definition,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-dna-boundary-replicates":
        result = audit_dna_boundary_model_replicates(
            manifest_paths=args.manifest,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-tt-cpd-stereo-candidates":
        result = build_tt_cpd_stereo_candidates(
            reference_dir=args.reference_dir,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-tt-cpd-stereo-candidates":
        result = audit_tt_cpd_stereo_candidates(
            series_manifest_path=args.series_manifest,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-tt-cpd-stereo-openbabel":
        result = audit_tt_cpd_stereo_with_openbabel(
            series_manifest_path=args.series_manifest,
            candidate_audit_path=args.candidate_audit,
            openbabel_executable=args.openbabel,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-tt-cpd-definition-candidate":
        result = build_tt_cpd_chemical_definition_candidate(
            product_id=args.product_id,
            candidate_manifest_path=args.candidate_manifest,
            candidate_audit_path=args.candidate_audit,
            independent_audit_path=args.independent_audit,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-tt-cpd-definition-review-packet":
        result = build_tt_cpd_definition_review_packet(
            definition_candidate_paths=args.definition_candidate,
            candidate_audit_path=args.candidate_audit,
            independent_audit_path=args.independent_audit,
            frequency_audit_paths=args.frequency_audit,
            output_dir=args.output_dir,
            equivalent_hessian_reference_paths=args.equivalent_hessian_reference,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-tt-cpd-definition-review":

        def path_map(values: list[str], option: str) -> dict[str, Path]:
            records: dict[str, Path] = {}
            for value in values:
                product_id, separator, raw_path = value.partition("=")
                if not separator or not product_id or not raw_path:
                    raise ValueError(f"{option} must use PRODUCT_ID=PATH")
                if product_id in records:
                    raise ValueError(f"duplicate {option} for {product_id}")
                records[product_id] = Path(raw_path)
            return records

        result = audit_tt_cpd_definition_review(
            packet_path=args.packet,
            reviewed_definition_paths=path_map(
                args.reviewed_definition, "--reviewed-definition"
            ),
            decision_evidence_paths=path_map(
                args.decision_evidence, "--decision-evidence"
            ),
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "ingest-visual-definition-review":
        result = materialize_visual_definition_review(
            packet_path=args.packet,
            visual_decisions_path=args.visual_decisions,
            source_asset_template_path=args.source_asset_template,
            structural_reference_manifest_path=args.structural_reference_manifest,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "ingest-visual-boundary-review":
        result = materialize_reviewed_dna_boundary_model(
            candidate_manifest_path=args.candidate_manifest,
            visual_decisions_path=args.visual_decisions,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "screen-dna-boundary-model":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = materialize_quantitatively_screened_dna_boundary_model(
            candidate_manifest_path=args.candidate_manifest,
            replicate_audit_path=args.replicate_audit,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "screen-grafted-dna-boundary-model":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = materialize_quantitatively_screened_grafted_dna_boundary_model(
            candidate_manifest_path=args.candidate_manifest,
            replicate_audit_path=args.replicate_audit,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-flexibly-relaxed-dna-boundary-seed":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = build_flexibly_relaxed_dna_boundary_seed(
            rigid_graft_manifest_path=args.rigid_graft_manifest,
            output_dir=args.output_dir,
            maximum_iterations=args.maximum_iterations,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "ingest-visual-conformer-review":
        result = materialize_visual_coupled_conformer_review(
            review_index_path=args.review_index,
            visual_decisions_path=args.visual_decisions,
            output_dir=args.output_dir,
            product_ids=args.product_id,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-minimum-backed-definition-candidate":
        result = build_minimum_backed_definition_candidate(
            definition_candidate_path=args.definition_candidate,
            minimum_evidence_path=args.minimum_evidence,
            optimized_xyz_path=args.optimized_xyz,
            optimized_model_audit_path=args.optimized_model_audit,
            frequency_job_manifest_path=args.frequency_job_manifest,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "generate-qm-job":
        atom_map = json.loads(args.atom_map.read_text()) if args.atom_map else None
        result = generate_psi4_job(
            product_id=args.product_id,
            model_id=args.model_id,
            xyz_path=args.xyz,
            output_dir=args.output_dir,
            job_kind=args.kind,
            charge=args.charge,
            multiplicity=args.multiplicity,
            atom_map=atom_map,
            model_manifest_path=args.model_manifest,
            parent_manifest_path=args.parent_manifest,
            memory_gib=args.memory_gib,
            threads=args.threads,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "generate-water-job":
        atom_map = json.loads(args.atom_map.read_text())
        result = generate_water_interaction_job(
            product_id=args.product_id,
            model_id=args.model_id,
            model_xyz_path=args.model_xyz,
            water_xyz_path=args.water_xyz,
            parent_manifest_path=args.parent_manifest,
            atom_map=atom_map,
            probe_id=args.probe_id,
            target_atom=args.target_atom,
            probe_atom=args.probe_atom,
            output_dir=args.output_dir,
            charge=args.charge,
            multiplicity=args.multiplicity,
            memory_gib=args.memory_gib,
            threads=args.threads,
            scf_type_override=args.scf_type,
            scf_calibration_role=args.calibration_role,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "retry-geometry-job":
        result = generate_geometry_retry_job(
            failed_job_dir=args.failed_job_dir,
            output_dir=args.output_dir,
            maximum_iterations=args.maximum_iterations,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-water-series":
        result = audit_water_interaction_series(args.job_dir, output_path=args.output)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-water-scf-calibration":
        result = audit_water_scf_calibration(args.job_dir, output_path=args.output)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-water-series":
        result = build_water_probe_series(
            plan_path=args.plan,
            model_xyz_path=args.model_xyz,
            parent_manifest_path=args.parent_manifest,
            output_dir=args.output_dir,
            memory_gib=args.memory_gib,
            threads=args.threads,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "generate-torsion-job":
        result = generate_torsion_scan_job(
            scan_plan_path=args.scan_plan,
            point_id=args.point_id,
            xyz_path=args.xyz,
            output_dir=args.output_dir,
            memory_gib=args.memory_gib,
            threads=args.threads,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coupled-conformer-mode-source":
        result = build_coupled_conformer_mode_source(
            frequency_job_dir=args.frequency_job_dir,
            equivalent_hessian_reference_path=args.equivalent_hessian_reference,
            model_graph_path=args.model_graph,
            stable_atom_map_path=args.atom_map,
            stereochemistry_evidence_path=args.stereochemistry_evidence,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coupled-conformer-candidates":
        keyword = (
            {"active_rmsd_amplitudes_angstrom": args.amplitude_angstrom}
            if args.amplitude_angstrom
            else {}
        )
        result = build_coupled_conformer_candidates(
            hessian_targets_path=args.hessian_targets or args.mode_source,
            model_graph_path=args.model_graph,
            stable_atom_map_path=args.atom_map,
            stereochemistry_evidence_path=args.stereochemistry_evidence,
            active_atom_keys=args.active_atom,
            output_dir=args.output_dir,
            mode_pair_count=args.mode_pairs,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "screen-coupled-conformer-rank":
        result = screen_coupled_conformer_fit_rank(
            fit_basis_manifest_path=args.fit_basis_manifest,
            baseline_response_manifest_path=args.baseline_response_manifest,
            candidate_manifest_path=args.candidate_manifest,
            output_dir=args.output_dir,
            candidate_ids=args.candidate_id,
            step_angstrom=args.step_angstrom,
            relative_threshold=args.relative_threshold,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "compare-periodicity-rank-screens":
        result = compare_periodicity_rank_screens(
            screen_manifest_paths=args.rank_screen,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coupled-conformer-review":
        result = build_coupled_conformer_review_template(
            product_id=args.product_id,
            model_id=args.model_id,
            optimized_audit_path=args.optimized_audit,
            reference_geometry_path=args.reference_geometry,
            model_graph_path=args.model_graph,
            stable_atom_map_path=args.atom_map,
            stereochemistry_evidence_path=args.stereochemistry_evidence,
            candidate_xyz_paths=args.candidate_xyz or [],
            output_path=args.output,
            rank_screen_path=args.rank_screen,
            mode_source_path=args.mode_source,
            candidate_manifest_path=args.candidate_manifest,
            candidate_selection_policy=args.candidate_selection_policy,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coupled-conformer-review-index":
        result = build_coupled_conformer_review_index(
            plan_paths=args.review_plan,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coupled-conformer-review-visualization":
        result = build_coupled_conformer_review_visualization(
            review_index_path=args.review_index,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coupled-conformer-review-decisions":
        result = build_coupled_conformer_review_decision_template(
            review_index_path=args.review_index,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "apply-coupled-conformer-review-decisions":
        result = apply_coupled_conformer_review_decisions(
            decisions_path=args.decisions,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-coupled-conformer-review":
        result = audit_reviewed_coupled_conformer_plan(
            plan_path=args.plan,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "screen-coupled-conformer-plan":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = materialize_quantitatively_screened_coupled_conformer_plan(
            plan_path=args.plan,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "generate-fixed-geometry-hessian":
        result = generate_fixed_geometry_hessian_job(
            plan_path=args.plan,
            conformer_id=args.conformer_id,
            output_dir=args.output_dir,
            charge=args.charge,
            multiplicity=args.multiplicity,
            memory_gib=args.memory_gib,
            threads=args.threads,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-fixed-geometry-hessian":
        result = audit_fixed_geometry_hessian_result(args.job_dir)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-fixed-geometry-hessian-targets":
        result = build_fixed_geometry_hessian_target_bundle(
            job_dir=args.job_dir,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "run-qm-job":
        result = run_psi4_job(
            job_dir=args.job_dir,
            psi4_executable=args.psi4,
            scratch_dir=args.scratch_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "prepare-distributed-hessian":
        result = prepare_distributed_hessian(
            job_dir=args.job_dir,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "materialize-frequency-job-provenance":
        result = materialize_frequency_job_provenance(
            job_dir=args.job_dir,
            source_xyz_fallback=args.source_xyz,
            parent_manifest_fallback=args.parent_manifest,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "checkpoint-distributed-hessian":
        result = checkpoint_distributed_hessian_pairs(
            source_plan_path=args.source_plan,
            destination_plan_path=args.destination_plan,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "reconcile-distributed-fixed-hessian-results":
        result = reconcile_equivalent_distributed_hessian_pairs(
            source_plan_path=args.source_plan,
            destination_plan_path=args.destination_plan,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "run-distributed-hessian-task":
        result = run_distributed_hessian_task(
            plan_path=args.plan,
            task_id=args.task_id,
            scratch_dir=args.scratch_dir,
            threads=args.threads,
            memory_gib=args.memory_gib,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "assemble-distributed-hessian":
        result = assemble_distributed_hessian(
            job_dir=args.job_dir,
            plan_path=args.plan,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "prepare-distributed-fixed-hessian":
        result = prepare_distributed_fixed_geometry_hessian(
            job_dir=args.job_dir,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "assemble-distributed-fixed-hessian":
        result = assemble_distributed_fixed_geometry_hessian(
            job_dir=args.job_dir,
            plan_path=args.plan,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "run-qm-series":
        result = run_psi4_series(
            series_manifest_path=args.series_manifest,
            psi4_executable=args.psi4,
            scratch_root=args.scratch_root,
            max_parallel=args.max_parallel,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-qm-series":
        result = build_qm_job_series(args.job_dir, output_path=args.output)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-optimized-model":
        result = audit_optimized_model(args.job_dir)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-model-equivalence":
        result = audit_endpoint_exchange_equivalence(
            first_job_dir=args.first_job_dir,
            second_job_dir=args.second_job_dir,
            independent_stereo_audit_path=args.independent_stereo_audit,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-equivalent-hessian-reference":
        result = build_equivalent_hessian_reference(
            source_frequency_job_dir=args.source_frequency_job_dir,
            equivalence_audit_path=args.equivalence_audit,
            target_product_id=args.target_product_id,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-frequency":
        result = audit_frequency_result(args.job_dir)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-hessian-targets":
        result = build_hessian_target_bundle(
            frequency_job_dir=args.frequency_job_dir,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-charge-targets":
        result = build_charge_target_bundle(
            electrostatic_audit_path=args.electrostatic_audit,
            water_audit_paths=args.water_audit,
            scf_calibration_audit_path=args.scf_calibration_audit,
            stereo_candidate_audit_path=args.stereo_candidate_audit,
            esp_audit_path=args.esp_audit,
            initial_charge_guess_path=args.initial_charge_guess,
            atom_map_path=args.atom_map,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-electrostatics":
        result = audit_electrostatic_properties(args.job_dir)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "generate-esp-job":
        result = generate_esp_job(
            product_id=args.product_id,
            model_id=args.model_id,
            xyz_path=args.xyz,
            atom_map=json.loads(args.atom_map.read_text()),
            parent_manifest_path=args.parent_manifest,
            output_dir=args.output_dir,
            charge=args.charge,
            multiplicity=args.multiplicity,
            memory_gib=args.memory_gib,
            threads=args.threads,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-esp":
        result = audit_esp_job(args.job_dir)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-coordinate-template":
        result = build_candidate_coordinate_template(
            geometry_job_dir=args.geometry_job_dir,
            frequency_job_dir=args.frequency_job_dir,
            output_path=args.output,
            version=args.version,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "reconcile-qm-run":
        result = reconcile_psi4_run(args.job_dir)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "inventory-bonded-terms":
        result = write_term_inventory(args.product, args.stereochemistry, args.output)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "extract-initial-charges":
        result = extract_initial_charge_guess(
            cgenff_topology=args.cgenff_topology,
            model_manifest_path=args.model_manifest,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-atom-type-candidates":
        result = build_atom_type_candidate_plan(
            cgenff_topology=args.cgenff_topology,
            model_manifest_path=args.model_manifest,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "fit-nonbonded-hypotheses":
        keyword = {"hypotheses_path": args.hypotheses} if args.hypotheses else {}
        result = fit_nonbonded_hypotheses(
            charge_target_bundle_path=args.charge_targets,
            atom_type_plan_path=args.atom_type_plan,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-parameter-coverage":
        result = audit_photoproduct_parameter_coverage(
            atom_type_plan_path=args.atom_type_plan,
            hypotheses_path=args.hypotheses,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-model-parameter-coverage":
        result = audit_model_graph_parameter_coverage(
            model_manifest_path=args.model_manifest,
            nonbonded_fit_path=args.nonbonded_fit,
            hypothesis_id=args.hypothesis_id,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-bonded-fit-plan":
        result = build_bonded_fit_plan(
            model_manifest_path=args.model_manifest,
            hessian_targets_path=args.hessian_targets,
            model_coverage_path=args.model_coverage,
            improper_convention_audit_path=args.improper_convention_audit,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "promote-bonded-refit-terms":
        keyword = {"policy_path": args.policy} if args.policy is not None else {}
        result = promote_bonded_fit_terms(
            fit_plan_path=args.fit_plan,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-openmm-candidate-skeleton":
        result = build_openmm_candidate_skeleton(
            fit_plan_path=args.fit_plan,
            nonbonded_fit_path=args.nonbonded_fit,
            cgenff_topology_path=args.cgenff_topology,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_topology_path=args.nucleic_topology,
            nucleic_parameters_path=args.nucleic_parameters,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-openmm-linear-fit-basis":
        result = build_openmm_linear_fit_basis(
            skeleton_manifest_path=args.skeleton_manifest,
            fit_plan_path=args.fit_plan,
            output_dir=args.output_dir,
            torsion_periodicities=args.torsion_periodicities or range(1, 7),
            improper_equilibrium_mode=args.improper_equilibrium_mode,
            angle_urey_bradley_mode=args.angle_urey_bradley_mode,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-openmm-linear-response":
        result = build_openmm_linear_response(
            fit_basis_manifest_path=args.fit_basis_manifest,
            hessian_targets_path=args.hessian_targets,
            output_dir=args.output_dir,
            step_angstrom=args.step_angstrom,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-openmm-fit-identifiability":
        result = audit_openmm_fit_identifiability(
            response_manifest_path=args.response_manifest,
            fit_plan_path=args.fit_plan,
            output_path=args.output,
            relative_threshold=args.relative_threshold,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-openmm-response-campaign":
        result = build_openmm_response_campaign(
            training_response_paths=args.training_response,
            validation_response_paths=args.validation_response,
            output_dir=args.output_dir,
            relative_threshold=args.relative_threshold,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-response-fit-specification":
        result = build_response_fit_specification_template(
            campaign_path=args.campaign,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-quantitative-response-fit-specification":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = materialize_quantitative_response_fit_specification(
            campaign_path=args.campaign,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "evaluate-response-fit":
        result = evaluate_reviewed_response_fit(
            campaign_path=args.campaign,
            specification_path=args.specification,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "refine-response-fit-geometry":
        keyword = {"policy_path": args.policy} if args.policy is not None else {}
        result = refine_selected_response_fit_geometry(
            selected_fit_path=args.selected_fit,
            output_dir=args.output_dir,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-geometry-refinement":
        keyword = {"audit_policy_path": args.policy} if args.policy is not None else {}
        result = audit_geometry_refinement(
            refinement_report_path=args.refinement,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "transform-geometry-refinement-to-charmm":
        result = build_geometry_refined_charmm_transform(
            refinement_report_path=args.refinement,
            audit_path=args.audit,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "compare-response-fit-evaluations":
        result = compare_response_fit_evaluations(
            evaluation_paths=args.evaluation,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-response-fit-selection":
        result = build_response_fit_selection_template(
            comparison_path=args.comparison,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "extract-selected-response-fit":
        result = extract_reviewed_response_fit_candidate(
            selection_path=args.selection,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "select-quantitative-response-fit":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = select_quantitative_response_fit_candidate(
            evaluation_path=args.evaluation,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "transform-selected-fit-to-charmm":
        result = build_charmm_bonded_transform_candidate(
            selected_candidate_path=args.selected_candidate,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-refined-relative-energies":
        result = audit_refined_relative_energies(
            refinement_report_path=args.refinement,
            relative_energy_targets_path=args.targets,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "audit-nonbonded-transfer":
        result = audit_nonbonded_transfer(
            source_fit_path=args.source_fit,
            water_collection_path=args.water_collection,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            hypothesis_id=args.hypothesis_id,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "fit-joint-nonbonded-transfer":
        result = fit_joint_nonbonded_transfer(
            source_fit_path=args.source_fit,
            water_collection_path=args.water_collection,
            frequency_root=args.frequency_root,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            hypothesis_id=args.hypothesis_id,
            output_path=args.output,
            product_ids=args.product_id,
            family_policy_path=args.family_policy,
            family_id=args.family_id,
            additional_water_collection_paths=args.additional_water_collection,
            fit_all_water_sites=args.fit_all_water_sites,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("fit_completed", result["passed"]) else 1
    if args.command == "audit-independent-nonbonded-candidate":
        result = audit_joint_nonbonded_candidate(
            candidate_path=args.candidate,
            validation_collection_path=args.validation_collection,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "build-parameter-workbook":
        result = build_parameter_workbook(
            product=args.product,
            stereochemistry=args.stereochemistry,
            output_path=args.output,
            initial_charge_guess_path=args.initial_charge_guess,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-parameter-workbook":
        result = audit_parameter_workbook(args.workbook)
        if args.output is not None:
            if args.output.exists():
                raise FileExistsError(
                    f"refusing to overwrite parameter workbook audit: {args.output}"
                )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "assemble-quantitative-parameter-workbook":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = assemble_quantitative_parameter_workbook(
            fit_plan_path=args.fit_plan,
            nonbonded_fit_path=args.nonbonded_fit,
            charmm_transform_path=args.charmm_transform,
            dna_boundary_model_path=args.dna_boundary_model,
            cgenff_topology_path=args.cgenff_topology,
            cgenff_parameters_path=args.cgenff_parameters,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-namd-improper-convention":
        result = audit_namd_improper_convention(
            output_dir=args.output_dir,
            psfgen_path=args.psfgen,
            namd_path=args.namd,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "export-charmm-candidate":
        result = export_charmm_candidate_assets(
            workbook_path=args.workbook,
            workbook_audit_path=args.workbook_audit,
            output_dir=args.output_dir,
            variant_id=args.variant_id,
            parent_candidate_manifest_path=args.parent_candidate_manifest,
            correction_policy_path=args.correction_policy,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "run-candidate-engine-smoke":
        if args.storage_root is None:
            raise ValueError("candidate engine smoke requires --storage-root")
        result = run_candidate_engine_smoke(
            candidate_manifest_path=args.candidate_manifest,
            boundary_manifest_path=args.dna_boundary_model,
            nucleic_topology_path=args.nucleic_topology,
            nucleic_parameters_path=args.nucleic_parameters,
            psfgen_path=args.psfgen,
            namd_path=args.namd,
            output_dir=args.output_dir,
            storage_root=args.storage_root,
            minimize_steps=args.minimize_steps,
            dynamics_steps=args.dynamics_steps,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "run-candidate-solution-smoke":
        if args.storage_root is None:
            raise ValueError("candidate solution smoke requires --storage-root")
        result = run_candidate_solution_smoke(
            candidate_manifest_path=args.candidate_manifest,
            vacuum_smoke_report_path=args.vacuum_smoke_report,
            nucleic_parameters_path=args.nucleic_parameters,
            water_parameters_path=args.water_parameters,
            ion_nbfix_parameters_path=args.ion_nbfix_parameters,
            namd_path=args.namd,
            output_dir=args.output_dir,
            storage_root=args.storage_root,
            padding_nm=args.padding_nm,
            ion_conc_mM=args.ion_conc_mm,
            seed=args.seed,
            minimize_steps=args.minimize_steps,
            heat_steps=args.heat_steps,
            dynamics_steps=args.dynamics_steps,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "build-candidate-context-topology":
        if args.storage_root is None:
            raise ValueError("candidate context topology requires --storage-root")
        from backend.core.models import Design

        candidate_payload = json.loads(args.candidate_manifest.read_text())
        registry_entry = next(
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == candidate_payload.get("product_id")
        )
        if args.design is not None:
            design = Design.model_validate_json(args.design.read_text())
        elif args.fixture == "reciprocal-crossover-1xt":
            design = build_reciprocal_crossover_1xt_context(
                stereochemistry=registry_entry["stereochemistry"]
            )
        else:
            design = build_duplex_context(
                stereochemistry=registry_entry["stereochemistry"],
                relationship=args.fixture,
            )
        result = build_candidate_context_topology(
            design=design,
            candidate_manifest_path=args.candidate_manifest,
            psfgen_path=args.psfgen,
            output_dir=args.output_dir,
            storage_root=args.storage_root,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "run-candidate-context-precondition":
        if args.storage_root is None:
            raise ValueError(
                "candidate context preconditioning requires --storage-root"
            )
        from backend.core.models import Design

        candidate_payload = json.loads(args.candidate_manifest.read_text())
        registry_entry = next(
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == candidate_payload.get("product_id")
        )
        if args.design is not None:
            design = Design.model_validate_json(args.design.read_text())
        elif args.fixture == "reciprocal-crossover-1xt":
            design = build_reciprocal_crossover_1xt_context(
                stereochemistry=registry_entry["stereochemistry"]
            )
        else:
            design = build_duplex_context(
                stereochemistry=registry_entry["stereochemistry"],
                relationship=args.fixture,
            )
        result = run_candidate_context_precondition(
            design=design,
            candidate_manifest_path=args.candidate_manifest,
            boundary_manifest_path=args.dna_boundary_model,
            qm_release_report_path=args.qm_release_report,
            nucleic_parameters_path=args.nucleic_parameters,
            psfgen_path=args.psfgen,
            namd_path=args.namd,
            policy_path=args.policy,
            output_dir=args.output_dir,
            storage_root=args.storage_root,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "run-candidate-context-solution-smoke":
        if args.storage_root is None:
            raise ValueError("candidate context solution smoke requires --storage-root")
        result = run_candidate_context_solution_smoke(
            candidate_manifest_path=args.candidate_manifest,
            precondition_report_path=args.precondition_report,
            nucleic_parameters_path=args.nucleic_parameters,
            water_parameters_path=args.water_parameters,
            ion_nbfix_parameters_path=args.ion_nbfix_parameters,
            namd_path=args.namd,
            output_dir=args.output_dir,
            storage_root=args.storage_root,
            padding_nm=args.padding_nm,
            ion_conc_mM=args.ion_conc_mm,
            seed=args.seed,
            minimize_steps=args.minimize_steps,
            heat_steps=args.heat_steps,
            dynamics_steps=args.dynamics_steps,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "prepare-namd-smoke":
        result = prepare_photoproduct_namd_smoke(
            package_dir=args.package_dir,
            output_dir=args.output_dir,
            local_minimize_steps=args.local_steps,
            global_minimize_steps=args.global_steps,
            dynamics_steps=args.dynamics_steps,
            dcd_freq=args.dcd_freq,
            mobile_radius_angstrom=args.mobile_radius_angstrom,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "audit-namd-smoke":
        result = audit_photoproduct_namd_smoke(
            package_dir=args.package_dir,
            smoke_plan_path=args.smoke_plan,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "request":
        entry = request_photoproduct(
            product_id=args.product_id,
            product=args.product,
            stereochemistry=args.stereochemistry,
            label=args.label,
            requested_contexts=args.context,
            path=args.registry,
        )
        print(json.dumps(entry, indent=2))
        return 0
    if args.command == "attach-asset":
        record = attach_photoproduct_asset(
            product_id=args.product_id,
            kind=args.kind,
            asset_path=args.asset,
            patch_name=args.patch_name,
            path=args.registry,
        )
        print(json.dumps(record, indent=2))
        return 0
    if args.command == "review-gate":
        record = record_photoproduct_gate_review(
            product_id=args.product_id,
            gate=args.gate,
            status=args.status,
            reviewer=args.reviewer,
            rationale=args.rationale,
            evidence_path=args.evidence,
            path=args.registry,
        )
        print(json.dumps(record, indent=2))
        return 0
    if args.command == "record-metric-gate":
        record = record_photoproduct_metric_gate(
            product_id=args.product_id,
            gate=args.gate,
            evidence_path=args.evidence,
            acceptance_policy_path=args.acceptance_policy,
            path=args.registry,
        )
        print(json.dumps(record, indent=2))
        return 0
    if args.command == "build-boundary-qm-release-audits":
        result = build_boundary_qm_release_audits(
            optimization_campaign_roots=args.optimization_campaign,
            frequency_campaign_root=args.frequency_campaign,
            acceptance_policy_path=args.acceptance_policy,
            output_root=args.output_dir,
            registry_path=args.registry,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-boundary-fit-inputs":
        result = build_boundary_fit_input_campaign(
            optimization_campaign_roots=args.optimization_campaign,
            frequency_campaign_root=args.frequency_campaign,
            output_root=args.output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-boundary-nonbonded-specification":
        keyword = {}
        if args.policy is not None:
            keyword["policy_path"] = args.policy
        result = build_boundary_nonbonded_specification(
            model_manifest_path=args.model_manifest,
            nucleic_topology_path=args.nucleic_topology,
            cgenff_topology_path=args.cgenff_topology,
            cgenff_parameters_path=args.cgenff_parameters,
            output_path=args.output,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "fit-boundary-charges":
        result = fit_boundary_charges(
            specification_path=args.specification,
            esp_audit_path=args.esp_audit,
            water_audit_paths=args.water_audit,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2, default=lambda value: value.tolist()))
        return 0
    if args.command == "fit-boundary-charge-campaign":
        result = fit_boundary_charge_campaign(
            fit_input_root=args.fit_input_root,
            esp_campaign_root=args.esp_campaign,
            water_campaign_root=args.water_campaign,
            cgenff_parameters_path=args.cgenff_parameters,
            nucleic_parameters_path=args.nucleic_parameters,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "fit-boundary-bonded-response":
        keyword = {"policy_path": args.policy} if args.policy is not None else {}
        result = fit_boundary_bonded_response(
            response_manifest_path=args.response_manifest,
            fit_plan_path=args.fit_plan,
            output_dir=args.output_dir,
            **keyword,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "build-help-trajectory":
        result = build_photoproduct_help_trajectory(
            product_id=args.product_id,
            dcd_path=args.dcd,
            psf_path=args.psf,
            parameter_path=args.parameters,
            static_topology_audit_path=args.static_topology_audit,
            namd_smoke_report_path=args.namd_smoke_report,
            output_path=args.output,
            max_frames=args.max_frames,
        )
        print(json.dumps(result, indent=2))
        return 0
    catalog = photoproduct_capabilities(args.registry)
    for item in catalog["products"]:
        state = "ready" if item["simulation_ready"] else f"next={item['next_gate']}"
        print(f"{item['id']}: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
