"""Positive field inventory for an owned, ordinary DNA preparation archive.

This describes copyable archival structure, not a physical-input fingerprint or
feature proof. The source profile separately excludes unreviewed live families.
New fields must be reviewed here rather than inferred from current serializers.
"""

from types import MappingProxyType

from backend.core import models as m
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
from backend.core.part_history_contract import PartRecipeRoot
from backend.core.part_input_sources import EmbeddedInput, InputSource
from backend.core.part_repair_draft import RepairBaseFingerprint, RepairDraft
from backend.core.part_repair_inputs import SetInput, UpgradeClusterCreation, UpgradeNumericalContract


_fields = {
    m.Design: """recipe_root input_sources repair_draft dimensions id lattice_frames helices strands
        lattice_type metadata deformations cluster_transforms group_organization nucleotide_transforms cluster_joints
        cluster_join_constraints overhangs overhang_connections overhang_bindings connection_versions
        duplexes flexible_segment_marks flexible_connections protein_assets protein_attachments nanoparticles
        nanoparticle_conjugations nanoparticle_connection_versions tm_settings extensions staple_groups
        plate_layout representation_overrides view_volumes annotations annotations_enabled visibility_state
        photoproduct_junctions crossovers crossover_constraints forced_ligations camera_poses animations
        chain_sim_projects loadouts atomistic_reference active_loadout_id last_editable_loadout_id
        feature_log feature_log_cursor feature_log_sub_cursor""",
    m.Vec3: "x y z",
    m.Helix: """id axis_start axis_end native_residues native_source phase_offset twist_per_bp_rad
        length_bp bp_start loop_skips label lattice_frame_id grid_pos direction""",
    m.LoopSkip: "bp_index delta",
    m.Domain: "helix_id start_bp end_bp direction overhang_id binds_overhang_id",
    m.Strand: "id domains strand_type sequence custom_scaffold_length color name notes routing_seed is_reference",
    m.SubDomain: """id name color start_bp_offset length_bp sequence_override rotation_theta_deg
        rotation_phi_deg notes tm_celsius gc_percent hairpin_warning dimer_warning""",
    m.OverhangSpec: """id helix_id strand_id sequence label rotation pivot translation sub_domains
        parent_overhang_id auxiliary_endpoint strand_anim_setup""",
    m.HalfCrossover: "helix_id index strand",
    m.Crossover: "id half_a half_b extra_bases process_id",
    m.CrossoverConstraint: "id helix_ids_a helix_ids_b allowed_bp_intervals",
    m.ForcedLigation: """id three_prime_helix_id three_prime_bp three_prime_direction five_prime_helix_id
        five_prime_bp five_prime_direction extra_bases is_periodic_seam""",
    m.DeformationRange: "helix_id start_bp end_bp direction strand_id domain_index",
    m.DeformationOp: "id type targets target_ranges plane_a_bp plane_b_bp affected_helix_ids cluster_ids params",
    m.TwistParams: "kind total_degrees degrees_per_nm",
    m.BendParams: "kind curvature_deg_per_bp direction_deg endpoints midpoint polymer_circle_count",
    m.SweepParams: """kind points_nm origin_nm initial_rotation initial_tangent point_frames warning_bps
        auto_loop_skips loop_skip_warnings preceding_op_ids direction start_step steps path_length_nm
        bp_positions_nm bp_frames""",
    m.DomainRef: "strand_id domain_index",
    GroupDomainRef: "strand_id domain_index",
    PartGroup: "id name helix_ids domain_ids color opacity is_default auto_created",
    GroupOrganization: "version groups",
    m.NucleotideTransform: """id kind helix_id bp_index direction copy_k crossover_id extra_base_k
        pivot translation rotation""",
    m.ClusterRigidTransform: """id name is_default helix_ids domain_ids translation rotation pivot
        parent_cluster_id overhang_duplex_driver_id color opacity auto_created""",
    m.ClusterJoint: """id cluster_id name joint_type local_axis_origin local_axis_direction surface_detail
        min_angle_deg max_angle_deg""",
    m.Dimension: "id name a b visible",
    m.LatticeFrame: "id plane placement_cluster_id",
    m.StapleGroup: "id name color strand_ids",
    m.DesignMetadata: """name description author created_at modified_at tags identity_last_known_path
        identity_confirmed_at primitive_kind hardware_defaults peg_surface namd_peg_review namd_box_solvent
        namd_peg_coating namd_peg_visible""",
    m.TmSettings: "na_mM conc_nM",
    m.CameraPose: "id name position target up fov orbit_mode",
    m.WellAssignment: "strand_id plate row col",
    m.TubeAssignment: "strand_id reason",
    m.PlateLayout: "orientation plate_count wells tubes",
    m.RepresentationSegment: "helix_id bp_start bp_end",
    m.RepresentationOverride: "id name representation segments protein_attachment_ids",
    m.Annotation: "id text icon callout_type color transparency size manual screen_pos visible refs",
    m.ViewVolume: "id name shape min_corner max_corner rotation representation opacity coloring outline_visible enabled",
    m.VisibilityState: "hidden_base_keys shown_base_keys hidden_cluster_ids hidden_part_group_ids",
    m.DesignAnimation: "id name fps loop keyframes",
    m.AnimationKeyframe: """id name camera_pose_id configuration_id feature_log_index hold_duration_s
        transition_duration_s easing joint_values binding_states strand_anim_phi is_trajectory trajectory_job_id
        trajectory_engine trajectory_frame_start trajectory_frame_end trajectory_scope trajectory_stride
        trajectory_show_ions trajectory_show_box spin_axis spin_rotations spin_invert text text_font_family
        text_font_size_px text_color text_bold text_italic text_align""",
    m.ChainSimStage: """id engine protocol field anchors surface run_target cluster_name length_ns steps label
        seed_job_id seed_job_name seed_engine""",
    m.ChainSimProject: "id name stages",
    m.OxdnaHardwareDefault: "backend device steps_per_s benchmarked_at proxy_nucleotides",
    m.NamdHardwareDefault: "threads devices ns_per_day benchmarked_at proxy_nucleotides",
    m.HardwareBenchmark: "oxdna namd",
    m.DesignLoadout: """id name design_snapshot_gz_b64 snapshot_size_bytes protected simulation_engine
        simulation_job_id head_revision_id base_revision_id""",
    PartRecipeRoot: "version kind lattice_type initial_name source_json source_sha256",
    InputSource: "version sha256 size_bytes format media_type",
    EmbeddedInput: "data_b64",
    RepairDraft: "version draft_id generation base_design_id base repair_version actions",
    RepairBaseFingerprint: "version root_sha256 commands_sha256 sources_sha256",
    SetInput: "feature_id child_id action parameter_path expected_old expected_old_json value",
    UpgradeNumericalContract: "feature_id child_id action expected_engine expected_template",
    UpgradeClusterCreation: "feature_id child_id action expected_version expected_cluster_id expected_definition_sha256",
}

_history = {
    m.SnapshotLogEntry: """feature_type id op_kind label timestamp params design_snapshot_gz_b64
        snapshot_size_bytes post_state_gz_b64 post_state_size_bytes evicted diff_added_b64 diff_removed_ids
        diff_modified_b64 pre_state_from_previous""",
    m.MinorMutationLogEntry: """feature_type id op_subtype label timestamp params diff_added_b64
        diff_removed_b64 diff_modified_b64 diff_size_bytes""",
    m.RoutingClusterLogEntry: """feature_type id label timestamp children pre_state_gz_b64
        pre_state_size_bytes post_state_gz_b64 post_state_size_bytes evicted diffs_evicted""",
    m.DeformationLogEntry: "proof_version feature_type id deformation_id op_snapshot",
    m.ClusterOpLogEntry: "authored_fields proof_version feature_type id cluster_id translation rotation pivot source",
    m.ClusterCreateLogEntry: "proof_version feature_type id cluster_snapshot cluster_id name helix_ids domain_ids",
    m.OverhangRotationLogEntry: """feature_type proof_version id overhang_ids rotations labels sub_domain_ids
        sub_domain_thetas_deg sub_domain_phis_deg""",
}
SCHEMAS = MappingProxyType({
    **{model: frozenset(fields.split()) for model, fields in _fields.items()},
    **{model: frozenset(fields.split()) | {"autogenerated_group_id"} for model, fields in _history.items()},
})
HISTORY_TYPES = frozenset(_history)
ENUM_TYPES = frozenset({m.LatticeType, m.Direction, m.StrandType, m.ConnectionType})
