"""Per-nucleotide display-geometry kernel (carve-up service push #46).

Pure compute: a ``Design`` in → a list of per-nucleotide geometry dicts out
(``backbone_position`` / ``base_position`` / ``base_normal`` / ``axis_tangent``
plus strand metadata). This is the geometry feed for every renderer and exporter
path — ``_design_response_with_geometry``, the assembly geometry routes, the
oxDNA/PDB/PSF exporters, the feature-log preview routes, etc.

These functions were marooned in ``backend/api/crud.py``'s "Internal helpers"
block; they touch no api-layer state (no ``design_state``, no ``HTTPException``),
so they belong in ``backend/core``. ``crud.py`` re-exports them under their
original underscore names, so the ~15 cross-file callers that do
``from backend.api.crud import _geometry_for_design`` keep working unchanged.

One reason to change: how NADOC turns topology + B-DNA constants into the
per-bead display geometry streamed to the Three.js renderer.

``backend/core`` must never import ``backend/api`` (L4) — the only api-ish
dependency, the live ``Design`` resolution, stays on the api side; here every
function takes the design as an explicit argument.
"""

from __future__ import annotations

import math

import numpy as np

from backend.core.models import (
    Design,
    Direction,
    Domain,  # noqa: F401  (string annotation in _emit_bridge_nucs)
    Strand,  # noqa: F401  (string annotation in _emit_bridge_nucs)
)
from backend.core.geometry import (
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
from backend.core.deformation import (
    _apply_ovhg_rotations_to_axes,
    apply_overhang_rotation_if_needed,
    deformed_helix_axes,
    deformed_nucleotide_arrays,
    effective_helix_for_geometry,
)
from backend.core.native_full_placement import (
    SOURCE, NativePlacementError, place_native_full, require_native_full_option,
)
from backend.core.constants import (
    ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG,
    FULL_REP_BALANCE_ROLL_HONEYCOMB_DEG,
    FULL_REP_BALANCE_ROLL_SQUARE_DEG,
    SSDNA_CONTOUR_PER_NT_NM,
)

# How far the extension arc bows off the straight radial, as a fraction of the arc
# length.  Bounds the worst consecutive bead spacing at
# sqrt(1 + (2·_EXT_BOW_FRAC)²) · SSDNA_CONTOUR_PER_NT_NM = 0.793 nm — inside oxDNA's
# 0.857 nm FENE ceiling with ~8 % margin.  If a seed ever trips ``fene_safe``, this
# is the knob: 0.20 pulls the worst spacing down to 0.732 nm.
_EXT_BOW_FRAC: float = 0.30


def apply_nucleotide_transforms_to_geometry(nucleotides: list[dict], design: Design) -> set[str]:
    """Project persisted residue poses onto the abstract nucleotide geometry.

    The same world-space delta is applied by ``atomistic.apply_nucleotide_transforms``;
    keeping this projection here makes full and atomistic representations siblings of
    one saved pose instead of independent edits.
    """
    transforms = {
        t.target_key(): t for t in design.nucleotide_transforms if t.kind == "base"
    }
    if not transforms:
        return set()
    matched: set[str] = set()
    matrices: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for nuc in nucleotides:
        key = (
            "base", nuc.get("helix_id"), nuc.get("bp_index"),
            nuc.get("direction"), int(nuc.get("copy_k", nuc.get("copy", 0)) or 0),
        )
        transform = transforms.get(key)
        if transform is None:
            continue
        parts = matrices.get(transform.id)
        if parts is None:
            x, y, z, w = transform.rotation
            rotation = np.array([
                [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
                [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
                [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
            ])
            parts = rotation, np.asarray(transform.pivot), np.asarray(transform.translation)
            matrices[transform.id] = parts
        rotation, pivot, translation = parts
        if nuc.get("helical_site") is not None:
            site = dict(nuc["helical_site"])
            site["axis_point"] = (pivot + rotation @ (np.asarray(site["axis_point"]) - pivot) + translation).tolist()
            site["radial_hat"] = (rotation @ np.asarray(site["radial_hat"])).tolist()
            nuc["helical_site"] = site
        for field in ("backbone_position", "base_position", "slab_position"):
            if nuc.get(field) is not None:
                p = np.asarray(nuc[field], dtype=float)
                nuc[field] = (pivot + rotation @ (p - pivot) + translation).tolist()
        for field in ("base_normal", "axis_tangent"):
            if nuc.get(field) is not None:
                nuc[field] = (rotation @ np.asarray(nuc[field], dtype=float)).tolist()
        if nuc.get("slab_quaternion") is not None:
            from scipy.spatial.transform import Rotation

            try:
                quaternion = np.asarray(nuc["slab_quaternion"], dtype=float)
            except (TypeError, ValueError, OverflowError) as error:
                raise NativePlacementError("Cannot transform a nonnumeric canonical slab quaternion.",
                    details={"identity": key, "field": "slab_quaternion",
                             "actual": nuc["slab_quaternion"]}) from error
            if (quaternion.shape != (4,) or not np.all(np.isfinite(quaternion))
                    or abs(np.linalg.norm(quaternion) - 1.0) > 1e-6):
                raise NativePlacementError("Cannot transform an invalid canonical slab quaternion.")
            nuc["slab_quaternion"] = Rotation.from_matrix(
                rotation @ Rotation.from_quat(quaternion).as_matrix()
            ).as_quat().tolist()
        matched.add(transform.id)
    return matched


def full_rep_balance_roll_rad(design: Design) -> float:
    """The accepted lattice-dependent roll of the native Full nucleotide frame.

    Returns the angle every helix is rotated about its own axis by, for the FULL
    (coarse-grained) representation only: 0 on honeycomb, which already draws its
    junctions symmetrically, and +13.125° on square, which without it draws one arc of
    every pair at 1.126 nm and the other at 0.286 nm under the old construction
    projection. Provenance is on ``constants.FULL_REP_BALANCE_ROLL_*``.

    Every native Full caller, including pose fitting, uses this same frame.
    Simulation-specific chemical landmarks must be converted at the named
    simulation boundary; disabling this roll is not a placement option.
    """
    from backend.core.models import LatticeType

    deg = (
        FULL_REP_BALANCE_ROLL_SQUARE_DEG
        if design.lattice_type == LatticeType.SQUARE
        else FULL_REP_BALANCE_ROLL_HONEYCOMB_DEG
    )
    return math.radians(deg)


def native_full_phase_roll_rad(design: Design) -> float:
    """Canonical phase convention used by native Full and its anchor readers."""
    return full_rep_balance_roll_rad(design) - math.radians(ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG)


def native_full_arrays_for_helix(
    helix, design: Design, *, compact_skips=False, apply_overhang_pose=True,
) -> dict:
    """The shared canonical per-helix preparation, including unoccupied sites.

    Prospective linker anchors need an unoccupied complementary site before
    topology is created. They must consume this same authority as Full; raw
    construction beads must never stand in for those anchors.
    """
    arrs = deformed_nucleotide_arrays(
        helix, design, compact_skips=compact_skips,
        phase_roll_rad=native_full_phase_roll_rad(design))
    if effective_helix_for_geometry(helix, design).native_residues:
        arrs = {**arrs, "placement_source": "authored-residue-c1-v1"}
    else:
        arrs = place_native_full(arrs)
    return apply_overhang_rotation_if_needed(arrs, helix, design) if apply_overhang_pose else arrs


def native_full_nucleotide_at(helix, design: Design, bp: int, direction: Direction) -> dict | None:
    """Resolve a prospective anchor through the same native placement and pose.

    Unoccupied complementary sites are needed while linker topology is built.
    This includes a persisted per-nucleotide override, just as Full emission
    does before deriving its bridge from the live anchor records.
    """
    arrs = native_full_arrays_for_helix(helix, design)
    matches = np.flatnonzero((arrs["bp_indices"] == bp) &
                            (arrs["directions"] == (direction == Direction.REVERSE)))
    if not len(matches):
        return None
    i = int(matches[0])
    record = {"helix_id": helix.id, "bp_index": int(bp), "direction": direction.value,
              "copy_k": 0, "placement_source": arrs["placement_source"],
              "backbone_position": arrs["positions"][i].tolist(),
              "base_position": arrs["base_positions"][i].tolist(),
              "base_normal": arrs["base_normals"][i].tolist(),
              "axis_tangent": arrs["axis_tangents"][i].tolist()}
    if arrs["placement_source"] == SOURCE:
        record["helical_site"] = {
            "axis_point": arrs["axis_points"][i].tolist(),
            "radial_hat": arrs["radial_hats"][i].tolist(),
            "azimuth_rad": float(arrs["azimuths"][i]),
            "groove_offset_rad": float(arrs["azimuths"][i // 2 * 2 + 1] - arrs["azimuths"][i // 2 * 2]),
            "phase_roll_rad": native_full_phase_roll_rad(design),
        }
    apply_nucleotide_transforms_to_geometry([record], design)
    return record


def _rolled(helix, roll_rad: float):
    """Apply the junction-balance roll to an ALREADY-normalised helix.

    For the ss-loop extension paths, which call ``effective_helix_for_geometry``
    themselves and hand the result straight to ``geometry``.  Rolling before
    normalisation would be a no-op — the grid re-derives ``phase_offset``.
    """
    if not roll_rad:
        return helix
    return helix.model_copy(update={"phase_offset": helix.phase_offset + roll_rad})


def _strand_nucleotide_info(
    design: Design, helix_ids: frozenset[str] | None = None
) -> dict:
    """(helix_id, bp_index, Direction) → strand metadata dict.

    If *helix_ids* is given, only nucleotides whose domain is on one of those
    helices are included.  Used by partial geometry to avoid iterating all strands.
    """
    info: dict = {}
    # Display-only flexible-segment flag → per-bead (flows through `**sinfo`,
    # exactly like is_reference). Keyed by (strand_id, domain_index, bp, dir).
    # Driven by DERIVED connections, NOT raw marks: a bead is excluded from rigid
    # rendering (and drawn on the bowed arc instead) only when its marked run
    # actually formed a FlexibleConnection between two clusters. A mark that yields
    # no connection (e.g. an in-cluster ssDNA run) leaves its bead rigid-rendered,
    # so marking can never silently delete geometry.
    flex_marks = {
        (a.strand_id, a.domain_index, a.bp_index, a.direction)
        for conn in design.flexible_connections
        for a in conn.segment_bead_keys
    }
    # Unpaired (ssDNA) beads — gates the flexible-segment right-click menu on the
    # frontend. (helix_id, bp, direction) with no Watson-Crick partner.
    from backend.core.flexible_segments import unpaired_bead_keys

    _unpaired = unpaired_bead_keys(design)
    for strand in design.strands:
        if not strand.domains:
            continue
        # NOTE: do NOT skip LINKER strands. Their complement domain lives on a
        # real overhang helix and we need the geometry pipeline to associate
        # the nucleotides at those positions with the linker strand so they
        # render. The bridge domain lives on a __lnk__ helix that is skipped
        # in the helix iteration, so it produces no positions to look up.
        first = strand.domains[0]
        last = strand.domains[-1]
        five_prime_key = (first.helix_id, first.start_bp, first.direction)
        three_prime_key = (last.helix_id, last.end_bp, last.direction)
        for di, domain in enumerate(strand.domains):
            if helix_ids is not None and domain.helix_id not in helix_ids:
                continue
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                key = (domain.helix_id, bp, domain.direction)
                info[key] = {
                    "strand_id": strand.id,
                    "strand_type": strand.strand_type.value,
                    "is_five_prime": key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                    "domain_index": di,
                    "overhang_id": domain.overhang_id,
                    "is_reference": strand.is_reference,
                    "is_flexible_segment": (strand.id, di, bp, domain.direction)
                    in flex_marks,
                    "is_unpaired": (domain.helix_id, bp, domain.direction) in _unpaired,
                }
    return info


def _geometry_for_design_straight(design: Design) -> list[dict]:
    """Return geometry with both deformations and cluster transforms removed.

    This is the t=0 base for the deform lerp: the original unmodified bundle positions
    before any deformation ops or cluster rotations.  Stripping cluster_transforms here
    means the deform toggle visually returns a cluster to its pre-rotation position.
    Cone directions at t=1 are derived from the current bead positions (fe.pos/te.pos)
    in helix_renderer.applyDeformLerp rather than from this map, so removing cluster
    transforms here no longer causes cone-direction mismatches at t=1.
    """
    straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
    return _geometry_for_design(straight)


def _straight_helix_axes(design: Design) -> list[dict]:
    """Return un-deformed helix axes using stored axis_start/axis_end positions.

    We use the stored positions rather than re-deriving from grid_pos via
    _normalize_helix_for_grid, because that would ignore re-centering applied
    at import time (e.g. _recenter_design for scadnano/cadnano designs).
    """
    result = []
    for h in design.helices:
        result.append(
            {
                "helix_id": h.id,
                "start": [h.axis_start.x, h.axis_start.y, h.axis_start.z],
                "end": [h.axis_end.x, h.axis_end.y, h.axis_end.z],
                "samples": None,
            }
        )
    return result


def _extension_anchor_keys(design: Design, extension_ids=None) -> set:
    """Only terminal frames used by the requested strand extensions."""
    strands = {strand.id: strand for strand in design.strands}
    keys = set()
    for ext in design.extensions:
        if extension_ids is not None and ext.id not in extension_ids:
            continue
        strand = strands.get(ext.strand_id)
        if strand is None or not strand.domains:
            continue
        domain = strand.domains[0] if ext.end == "five_prime" else strand.domains[-1]
        bp = domain.start_bp if ext.end == "five_prime" else domain.end_bp
        keys.add((domain.helix_id, bp, domain.direction))
    return keys


def _strand_extension_geometry(
    design: Design,
    nuc_pos_map: dict,
    extension_ids: frozenset[str] | None = None,
) -> list[dict]:
    """
    Compute geometry dicts for StrandExtension entries.

    Extension beads are placed along a quadratic Bézier arc starting at the
    terminal nucleotide and curving radially outward from the helix centre,
    bowing in the direction the strand was already heading.  Sequence beads come
    first (bp_index 0…n-1), then the fluorophore bead if a modification is
    set (bp_index n, is_modification=True).

    Synthetic helix_id: ``__ext_{extension.id}``

    THE SPACING IS LOAD-BEARING, NOT COSMETIC.  These beads are real nucleotides:
    they are emitted into the oxDNA topology + configuration (and the atomistic
    model) as single-stranded tail particles, so consecutive bead separations ARE
    oxDNA backbone bonds.  oxDNA's FENE spring is only defined over
    ~0.431–0.857 nm (``oxdna_health.FENE_*``); the arc must therefore hand every
    consecutive pair a separation inside that window.  Two properties do that:

    * ``arc_len = n_total * SSDNA_CONTOUR_PER_NT_NM`` (0.68 nm/nt, ≈ oxDNA's FENE
      rest length) and bead *i* at ``t = (i+1)/n_total`` — so the LAST bead lands
      exactly on the arc end.  (The old ``(i+1)/(n_total+1)`` reserved a phantom
      slot past the tip, which put a lone bead at *half* the arc.)
    * the bow is taken ⟂ to the radial in the deformed frame.  Because p1's radial
      component is exactly half of p2's, the radial part of B(t) is exactly linear
      in t, so the only non-uniformity is the bow term — bounded independent of n.
      Consecutive spacing therefore stays in [0.680, 0.793] nm for every n.

    A world-axis bow would NOT be safe: a cluster rotation that lines the radial up
    with the bow axis degenerates the Bézier (the arc doubles back), which both
    over- and under-shoots the FENE window.
    """
    import numpy as np

    result = []
    strand_by_id = {s.id: s for s in design.strands}

    for ext in design.extensions:
        if extension_ids is not None and ext.id not in extension_ids:
            continue
        strand = strand_by_id.get(ext.strand_id)
        if strand is None or not strand.domains:
            continue

        if ext.end == "five_prime":
            dom = strand.domains[0]
            terminal_bp = dom.start_bp
            domain_index = -1.0
        else:
            dom = strand.domains[-1]
            terminal_bp = dom.end_bp
            domain_index = float(len(strand.domains))

        nuc_a = nuc_pos_map.get((dom.helix_id, terminal_bp, dom.direction))
        if nuc_a is None:
            continue

        helix = design.find_helix(dom.helix_id)
        if helix is None:
            continue

        p0 = nuc_a.position  # terminal nucleotide backbone position (numpy array)

        # Radial outward direction: the deformed base_normal points inward
        # (backbone → base, toward the axis).  Negating it gives the outward
        # radial in the already-deformed frame, so extensions follow
        # bend / twist / translate / rotate transforms automatically.
        bn_raw = np.array(nuc_a.base_normal, dtype=float)
        radial_len = float(np.linalg.norm(bn_raw))
        if radial_len < 1e-6:
            radial = np.array([1.0, 0.0, 0.0])
        else:
            radial = -bn_raw / radial_len

        n_seq = len(ext.sequence) if ext.sequence else 0
        has_mod = ext.modification is not None
        n_total = n_seq + (1 if has_mod else 0)
        if n_total == 0:
            continue

        # Arc endpoint and Bézier control point.  One ssDNA contour length per
        # nucleotide, so consecutive beads sit an oxDNA-FENE-legal bond apart.
        arc_len = n_total * SSDNA_CONTOUR_PER_NT_NM
        p2 = p0 + radial * arc_len
        mid = (p0 + p2) * 0.5

        # Bow direction: keep heading the way the strand was already going as it
        # left the duplex (3′ tail bows along the anchor's 5′→3′; a 5′ tail is
        # walked backwards, so it bows against it).  Taken in the anchor's own
        # deformed frame — NOT a world axis — so the arc follows bend / twist /
        # cluster transforms and can never degenerate against the radial.
        chain_tan = np.array(nuc_a.axis_tangent, dtype=float)
        if dom.direction == Direction.REVERSE:
            chain_tan = -chain_tan
        bow_dir = chain_tan if ext.end == "three_prime" else -chain_tan
        bow_dir = bow_dir - float(np.dot(bow_dir, radial)) * radial  # ⟂ radial
        bow_len = float(np.linalg.norm(bow_dir))
        if bow_len < 1e-6:  # axis_tangent ∥ radial (degenerate frame): any ⟂ vector
            bow_dir = np.cross(radial, np.array([0.0, 0.0, 1.0]))
            if float(np.linalg.norm(bow_dir)) < 1e-6:
                bow_dir = np.cross(radial, np.array([0.0, 1.0, 0.0]))
            bow_len = float(np.linalg.norm(bow_dir))
        bow_dir = bow_dir / bow_len
        p1 = mid + bow_dir * (arc_len * _EXT_BOW_FRAC)

        # Base-normal: inward radial (slabs face toward the helix).
        bn = -radial

        synthetic_helix_id = f"__ext_{ext.id}"

        def _bead(i: int, is_mod: bool, mod_name: str | None) -> dict:
            # Last bead lands ON the arc end (t=1) — no phantom slot past the tip.
            t = (i + 1) / n_total
            pos = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2
            tangent = 2 * (1 - t) * (p1 - p0) + 2 * t * (p2 - p1)
            tlen = float(np.linalg.norm(tangent))
            tangent = tangent / tlen if tlen > 1e-6 else np.array(nuc_a.axis_tangent)
            base_pos = pos + 0.3 * bn
            # Extension sequences are stored in chemical 5′→3′ order, while
            # ext_k/bp_index always increases away from the duplex anchor. A
            # 5′ tail therefore traverses its stored sequence in reverse. Keep
            # this identical to atomistic._build_extension_atoms so every
            # representation colors the same residue.
            base_char = None
            if not is_mod and ext.sequence:
                base_char = (
                    ext.sequence[i]
                    if ext.end == "three_prime"
                    else ext.sequence[n_seq - 1 - i]
                ).upper()
            d = {
                "helix_id": synthetic_helix_id,
                "bp_index": i,
                "direction": dom.direction.value,
                "backbone_position": pos.tolist(),
                "base_position": base_pos.tolist(),
                "base_normal": bn.tolist(),
                "axis_tangent": tangent.tolist(),
                "strand_id": ext.strand_id,
                "strand_type": strand.strand_type.value,
                "is_five_prime": (not is_mod)
                and (ext.end == "five_prime")
                and (i == n_seq - 1),
                "is_three_prime": False,
                "domain_index": domain_index,
                "overhang_id": None,
                "extension_id": ext.id,
                "placement_source": "chemical-modification-v1" if is_mod else "native-full-extension-v1",
                "nucleobase": base_char,
                "is_modification": is_mod,
                "modification": mod_name,
            }
            return d

        for i in range(n_seq):
            result.append(_bead(i, False, None))

        if has_mod:
            result.append(_bead(n_seq, True, ext.modification))

    return result


def _geometry_for_helices(
    design: Design,
    helix_ids: frozenset[str] | None = None,
    include_linker_helices: bool = False,
    compact_skips: bool = False,
    *,
    extension_ids: frozenset[str] | None = None,
    measured_positioning: bool = True,
    junction_balance: bool = True,
    helix_axes: list[dict] | None = None,
) -> list[dict]:
    """Compute nucleotide geometry for *design*.

    If *helix_ids* is given, only nucleotides on those helices are returned.
    This is the partial-update fast path for Fix B: callers that know which
    helices changed pass that set to skip the other 90 % of geometry work.

    *extension_ids* enables exact partial extension geometry. Callers must also
    include the owning strands' terminal anchor helices in *helix_ids* so the
    required nucleotide frames are available in ``nuc_pos_map``.

    The accepted lattice-dependent roll is part of the canonical native frame.
    Retired ``measured_positioning=False`` and ``junction_balance=False`` requests
    raise errors; neither is an alternative geometry. Explicitly different
    simulation landmarks require conversion at their named chemical boundary.

    *include_linker_helices*: per-design rendering skips ``__lnk__`` virtual
    bridge helices and emits their bridge nucs via ``_emit_bridge_nucs`` (which
    reads ``design.overhang_connections``). The cross-part assembly path has the
    bridge baked into a real world-space ``__lnk__`` helix but no
    ``overhang_connections`` on its synthetic design, so it sets this True to
    render the bridge helix directly through the normal per-helix pipeline.
    """
    from types import SimpleNamespace

    full_mode = helix_ids is None
    nuc_info = _strand_nucleotide_info(design, helix_ids)
    if junction_balance is not True:
        raise NativePlacementError("Unbalanced native Full placement has been removed; junction_balance must be True.")
    roll = native_full_phase_roll_rad(design)
    require_native_full_option(measured_positioning)

    # Only nucleotide tails replace the terminal DNA nucleotide. A modification
    # remains outside the DNA walk and must not hide its attachment endpoint.
    five_prime_ext_strands = {
        ext.strand_id for ext in design.extensions if ext.end == "five_prime" and ext.sequence
    }
    for strand in design.strands:
        if strand.id not in five_prime_ext_strands or not strand.domains:
            continue
        first = strand.domains[0]
        if helix_ids is not None and first.helix_id not in helix_ids:
            continue
        key = (first.helix_id, first.start_bp, first.direction)
        entry = nuc_info.get(key)
        if entry and entry.get("is_five_prime"):
            nuc_info[key] = {**entry, "is_five_prime": False}

    _dir_enums = (Direction.FORWARD, Direction.REVERSE)  # index by int 0/1
    needs_pos_map = bool(design.extensions) and (full_mode or bool(extension_ids))
    result: list[dict] = []
    nuc_pos_map: dict = {}
    anchor_keys = _extension_anchor_keys(design, extension_ids) if needs_pos_map else set()

    # Pre-compute min/max bp referenced by any strand domain per helix.
    # Needed to render ss-scaffold loops that extend outside the physical helix span.
    min_domain_bp: dict[str, int] = {}
    max_domain_bp: dict[str, int] = {}
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            hid = domain.helix_id
            if hid not in min_domain_bp or lo < min_domain_bp[hid]:
                min_domain_bp[hid] = lo
            if hid not in max_domain_bp or hi > max_domain_bp[hid]:
                max_domain_bp[hid] = hi

    def _emit_arrs(arrs: dict, helix_id: str) -> None:
        """Serialize an already-authoritative nucleotide arrays block."""
        M = len(arrs["bp_indices"])
        if M == 0:
            return
        if not arrs.get("placement_source"):
            raise NativePlacementError(f"Unplaced nucleotide arrays on helix {helix_id}.")
        bp_list = arrs["bp_indices"].tolist()
        dir_arr = arrs["directions"]
        pos_list = arrs["positions"].tolist()
        base_list = arrs["base_positions"].tolist()
        bn_list = arrs["base_normals"].tolist()
        at_list = arrs["axis_tangents"].tolist()
        sites = arrs["placement_source"] == SOURCE
        copies: dict[tuple[int, Direction], int] = {}
        for i in range(M):
            bp = bp_list[i]
            d_enum = _dir_enums[dir_arr[i]]
            copy_key = (bp, d_enum)
            copy_k = copies.get(copy_key, 0)
            copies[copy_key] = copy_k + 1
            key = (helix_id, bp, d_enum)
            if key in anchor_keys:
                nuc_pos_map[key] = SimpleNamespace(
                    position=arrs["positions"][i],
                    axis_tangent=arrs["axis_tangents"][i],
                    base_normal=arrs["base_normals"][i],
                )
            sinfo = nuc_info.get(key)
            if sinfo is None:
                # No real strand occupies this helix-lattice slot — this is a
                # single-stranded overhang region where only the complementary strand
                # exists.  Emitting a phantom base here (the old `_missing` placeholder)
                # drew a non-existent nucleotide that misrepresents ssDNA as duplex and
                # could never receive MD data (the persistent "bright slab" in MD views).
                # Skip it so ssDNA regions render single-stranded.  Every export/sim keys
                # off the real strand order, so they are unaffected (see the blast-radius
                # audit); only rendering changes.  nuc_pos_map above still carries the
                # slot for extension anchoring.
                continue
            result.append(
                {
                    "helix_id": helix_id,
                    "bp_index": bp,
                    "direction": d_enum.value,
                    "copy_k": copy_k,
                    "backbone_position": pos_list[i],
                    "base_position": base_list[i],
                    "base_normal": bn_list[i],
                    "axis_tangent": at_list[i],
                    "placement_source": arrs["placement_source"],
                    **({"helical_site": {
                        "axis_point": arrs["axis_points"][i].tolist(),
                        "radial_hat": arrs["radial_hats"][i].tolist(),
                        "azimuth_rad": float(arrs["azimuths"][i]),
                        "groove_offset_rad": float(arrs["azimuths"][i // 2 * 2 + 1] - arrs["azimuths"][i // 2 * 2]),
                        "phase_roll_rad": roll,
                    }} if sites else {}),
                    **sinfo,
                }
            )

    for helix in design.helices:
        if helix_ids is not None and helix.id not in helix_ids:
            continue
        if helix.id.startswith("__lnk__") and not include_linker_helices:
            continue  # virtual linker helices have no real geometry (per-design:
            # bridge nucs come from _emit_bridge_nucs below instead)
        arrs = native_full_arrays_for_helix(helix, design, compact_skips=compact_skips)
        _emit_arrs(arrs, arrs["helix_id"])

        # Render nucleotides outside the physical helix span (ss-scaffold loops).
        # These must go through the same deformation / cluster transform pipeline
        # so they follow bend / twist / translate / rotate ops.
        from backend.core.deformation import deform_extended_arrays

        norm_helix = None  # lazy — only normalise once if either side needs it

        lo_bp = min_domain_bp.get(helix.id, helix.bp_start)
        if lo_bp < helix.bp_start:
            norm_helix = _rolled(effective_helix_for_geometry(helix, design), roll)
            extra_arrs = nucleotide_positions_arrays_extended(norm_helix, lo_bp)
            extra_arrs = deform_extended_arrays(
                extra_arrs, helix, design, edge_bp=helix.bp_start
            )
            extra_arrs = place_native_full(extra_arrs)
            extra_arrs = apply_overhang_rotation_if_needed(extra_arrs, helix, design)
            _emit_arrs(extra_arrs, helix.id)

        hi_bp = max_domain_bp.get(helix.id, helix.bp_start + helix.length_bp - 1)
        helix_hi = helix.bp_start + helix.length_bp  # first bp past helix right edge
        if hi_bp >= helix_hi:
            if norm_helix is None:
                norm_helix = _rolled(effective_helix_for_geometry(helix, design), roll)
            extra_arrs = nucleotide_positions_arrays_extended_right(norm_helix, hi_bp)
            extra_arrs = deform_extended_arrays(
                extra_arrs, helix, design, edge_bp=helix_hi - 1
            )
            extra_arrs = place_native_full(extra_arrs)
            extra_arrs = apply_overhang_rotation_if_needed(extra_arrs, helix, design)
            _emit_arrs(extra_arrs, helix.id)

    # Emit bridge nucs for ds linkers AFTER the regular helix loop so they
    # can read the live OH/complement positions (cluster transforms applied)
    # to derive their axis. Without this pass the bridge tube is JS-only —
    # not selectable, no real geometry payload, no slabs/cones in standard
    # rendering paths.
    apply_nucleotide_transforms_to_geometry(result, design)
    regular_count = len(result)
    _emit_bridge_nucs(design, nuc_info, result)

    if design.extensions and (full_mode or extension_ids):
        result.extend(_strand_extension_geometry(design, nuc_pos_map, extension_ids))
    apply_nucleotide_transforms_to_geometry(result[regular_count:], design)
    from backend.core.native_slab_placement import attach_native_slab_poses
    attach_native_slab_poses(result)
    return result


def _emit_bridge_nucs(design: Design, nuc_info: dict, result: list[dict]) -> None:
    """For each ds OverhangConnection, append nuc dicts for the bridge
    domain to *result*. Bridge positions are derived from the live anchors
    on each side (complement nuc on the OH helix at the OH's `attach`-end
    bp). The bridge axis is centred using the exact canonical O5′ boundary
    beads, including strand-specific radial, azimuthal, and axial offsets.

    No-op when the design has no ds linkers, when the linker strand or its
    bridge domain can't be resolved, or when the OH/complement nucs aren't
    in *result* yet (e.g. partial geometry that didn't compute the OH helix).
    """
    from backend.core.linker_relax import (
        _anchor_pos_and_normal,
        _comp_first,
        bridge_axis_geometry,
        bridge_nucleotide_geometry,
        bridge_nucleotide_site,
    )

    ds_conns = [c for c in design.overhang_connections if c.linker_type == "ds"]
    if not ds_conns:
        return

    for conn in ds_conns:
        bridge_helix_id = f"__lnk__{conn.id}"
        # Find the two bridge strands (one per side).
        side_strand: dict[str, "Strand"] = {}
        for side in ("a", "b"):
            sid = f"__lnk__{conn.id}__{side}"
            s = next((st for st in design.strands if st.id == sid), None)
            if s is not None:
                side_strand[side] = s
        if not side_strand:
            continue
        # Find the bridge domain on each strand (the one on the virtual helix).
        side_bridge: dict[str, tuple[int, "Domain"]] = {}
        for side, s in side_strand.items():
            for di, dom in enumerate(s.domains):
                if dom.helix_id == bridge_helix_id:
                    side_bridge[side] = (di, dom)
                    break
        if not side_bridge:
            continue

        pa, na = _anchor_pos_and_normal(result, conn, conn.overhang_a_id, True)
        pb, _ = _anchor_pos_and_normal(result, conn, conn.overhang_b_id, False)
        if pa is None or pb is None:
            continue

        any_dom = next(iter(side_bridge.values()))[1]
        L = abs(any_dom.end_bp - any_dom.start_bp) + 1
        cfa = _comp_first(conn.overhang_a_id, conn.overhang_a_attach)
        cfb = _comp_first(conn.overhang_b_id, conn.overhang_b_attach)
        g = bridge_axis_geometry(pa, na, pb, L, cfa, cfb,
            identity={"connection_id": conn.id, "bridge_helix_id": bridge_helix_id,
                      "overhang_a_id": conn.overhang_a_id, "overhang_b_id": conn.overhang_b_id})
        fz = g["fz"]

        # Per-side: emit one nuc per bp of the bridge domain. Side A's
        # strand uses FORWARD-style angles (radial = fx·cos+fy·sin) when
        # comp_first_a; REVERSE-style otherwise. Same per-side rule.
        for side, (dom_idx, dom) in side_bridge.items():
            strand = side_strand[side]
            first_dom = strand.domains[0]
            last_dom = strand.domains[-1]
            five_prime_key = (
                first_dom.helix_id,
                first_dom.start_bp,
                first_dom.direction,
            )
            three_prime_key = (last_dom.helix_id, last_dom.end_bp, last_dom.direction)
            is_fwd = dom.direction == Direction.FORWARD
            for bp in range(
                min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp) + 1
            ):
                bb_pos, base_pos, bn = bridge_nucleotide_geometry(g, bp, reverse=not is_fwd)
                site_origin, site_radial, _site_tangent, site_angle = bridge_nucleotide_site(g, bp)
                from backend.core.geometry import groove_offset_rad
                bridge_helix = design.find_helix(bridge_helix_id)
                groove = groove_offset_rad(bridge_helix.direction if bridge_helix else None)
                if not is_fwd:
                    site_radial = np.cos(groove) * site_radial + np.sin(groove) * np.cross(fz, site_radial)
                key = (bridge_helix_id, bp, dom.direction)
                sinfo = nuc_info.get(
                    key,
                    {
                        "strand_id": strand.id,
                        "strand_type": strand.strand_type.value,
                        "is_five_prime": key == five_prime_key,
                        "is_three_prime": key == three_prime_key,
                        "domain_index": dom_idx,
                        "overhang_id": None,
                    },
                )
                result.append(
                    {
                        "helix_id": bridge_helix_id,
                        "bp_index": bp,
                        "direction": dom.direction.value,
                        "backbone_position": bb_pos.tolist(),
                        "base_position": base_pos.tolist(),
                        "base_normal": bn.tolist(),
                        "axis_tangent": fz.tolist(),
                        "placement_source": SOURCE,
                        "helical_site": {
                            "axis_point": site_origin.tolist(),
                            "radial_hat": site_radial.tolist(),
                            "azimuth_rad": float(site_angle + (0 if is_fwd else groove)),
                            "groove_offset_rad": groove,
                            "phase_roll_rad": native_full_phase_roll_rad(design),
                        },
                        **sinfo,
                    }
                )


def _geometry_for_design(
    design: Design,
    include_linker_helices: bool = False,
    compact_skips: bool = False,
    *,
    measured_positioning: bool = True,
    junction_balance: bool = True,
) -> list[dict]:
    """The sole native Full per-nucleotide geometry, including canonical slab poses."""
    return _geometry_for_helices(
        design,
        include_linker_helices=include_linker_helices,
        compact_skips=compact_skips,
        measured_positioning=measured_positioning,
        junction_balance=junction_balance,
    )


def fitting_geometry(design: Design) -> list[dict]:
    """Fit against the same canonical nucleotide geometry the user sees.

    There is no alternate bead/base placement hidden behind the fitting boundary.
    """
    return _geometry_for_design(design)


def _compact_geometry_from_nucleotides(nucleotides: list[dict]) -> dict:
    """Convert a flat list of nucleotide dicts into the COMPACT
    per-helix-per-direction parallel-array form used by the
    ``nucleotides_compact`` wire format. See _compact_geometry_for_design
    for the rationale; this helper exists so callers that already have the
    nucleotide list (e.g. _design_response_with_geometry) don't recompute it.
    """
    out: dict = {}
    for n in nucleotides:
        helix = n.get("helix_id")
        if helix is None:
            continue
        direction = n.get("direction")
        helix_bucket = out.get(helix)
        if helix_bucket is None:
            helix_bucket = {}
            out[helix] = helix_bucket
        b = helix_bucket.get(direction)
        if b is None:
            b = {
                "bp": [],
                "bb": [],
                "bs": [],
                "bn": [],
                "at": [],
                "sp": [],
                "sq": [],
                "pv": [],
                "sid": [],
                "stype": [],
                "is5": [],
                "is3": [],
                "did": [],
                "ohid": [],
                # Sparse fields: appended lazily, so empty arrays don't ship.
                "extid": None,
                "ismod": None,
                "mod": None,
                "base": None,
            }
            helix_bucket[direction] = b
        b["bp"].append(n.get("bp_index"))
        b["bb"].append(n.get("backbone_position"))
        b["bs"].append(n.get("base_position"))
        b["bn"].append(n.get("base_normal"))
        b["at"].append(n.get("axis_tangent"))
        b["sp"].append(n.get("slab_position"))
        b["sq"].append(n.get("slab_quaternion"))
        b["pv"].append(n["placement_source"])
        b["sid"].append(n.get("strand_id"))
        b["stype"].append(n.get("strand_type"))
        b["is5"].append(bool(n.get("is_five_prime")))
        b["is3"].append(bool(n.get("is_three_prime")))
        b["did"].append(n.get("domain_index", 0))
        b["ohid"].append(n.get("overhang_id"))
        # Sparse fields — only allocate the array when first non-default appears.
        ext_id = n.get("extension_id")
        if ext_id is not None:
            if b["extid"] is None:
                b["extid"] = [None] * (len(b["bp"]) - 1)
            b["extid"].append(ext_id)
        elif b["extid"] is not None:
            b["extid"].append(None)
        is_mod = bool(n.get("is_modification"))
        if is_mod:
            if b["ismod"] is None:
                b["ismod"] = [False] * (len(b["bp"]) - 1)
            b["ismod"].append(True)
        elif b["ismod"] is not None:
            b["ismod"].append(False)
        mod = n.get("modification")
        if mod is not None:
            if b["mod"] is None:
                b["mod"] = [None] * (len(b["bp"]) - 1)
            b["mod"].append(mod)
        elif b["mod"] is not None:
            b["mod"].append(None)
        base = n.get("nucleobase")
        if base is not None:
            if b["base"] is None:
                b["base"] = [None] * (len(b["bp"]) - 1)
            b["base"].append(base)
        elif b["base"] is not None:
            b["base"].append(None)
    # Drop sparse-field placeholders that never got populated, to keep the wire
    # tight when none of those fields apply.
    for helix_bucket in out.values():
        for b in helix_bucket.values():
            for k in ("extid", "ismod", "mod", "base"):
                if b.get(k) is None:
                    b.pop(k, None)
    return out


def _compact_geometry_for_design(
    design: "Design", *, measured_positioning: bool = True, junction_balance: bool = True
) -> dict:
    """Compute full deformed geometry in COMPACT per-helix-per-direction
    parallel-arrays form. Wire size is ~50% of the equivalent dict-list
    ``nucleotides`` payload because field names don't repeat per nuc;
    JSON.parse on the frontend is roughly proportionally faster.
    """
    return _compact_geometry_from_nucleotides(
        _geometry_for_design(
            design,
            measured_positioning=measured_positioning,
            junction_balance=junction_balance,
        )
    )


def _positions_by_helix(nucleotides: list[dict]) -> dict:
    """Serialize canonical records for ``positions_only`` without recalculation.

    Bead, base and slab poses plus their authority identifier always travel
    together. Full and incremental views cannot select different placement.
    """
    out: dict = {}
    for n in nucleotides:
        helix = n.get("helix_id")
        if helix is None:
            continue
        direction = n.get("direction")
        bucket = out.setdefault(helix, {}).setdefault(direction, None)
        if bucket is None:
            bucket = {"bp": [], "bb": [], "bs": [], "bn": [], "at": [], "sp": [], "sq": [], "pv": [],
                      "sid": [], "extid": [], "ismod": [], "mod": []}
            out[helix][direction] = bucket
        bucket["bp"].append(n.get("bp_index"))
        bucket["bb"].append(n.get("backbone_position"))
        bucket["bs"].append(n.get("base_position"))
        bucket["bn"].append(n.get("base_normal"))
        bucket["at"].append(n.get("axis_tangent"))
        bucket["sp"].append(n.get("slab_position"))
        bucket["sq"].append(n.get("slab_quaternion"))
        bucket["pv"].append(n["placement_source"])
        bucket["sid"].append(n.get("strand_id"))
        bucket["extid"].append(n.get("extension_id"))
        bucket["ismod"].append(bool(n.get("is_modification")))
        bucket["mod"].append(n.get("modification"))
    return out


def _positions_for_design(
    design: Design,
    *,
    measured_positioning: bool = True,
    junction_balance: bool = True,
) -> tuple[dict, list[dict]]:
    """Compact positions from the exact same canonical records as a full rebuild.

    A second positioning implementation is forbidden. In particular, scoped
    strand transforms, overhangs, residue poses, and extensions cannot select
    different placement through an incremental response.
    """
    nucleotides = _geometry_for_design(
        design, measured_positioning=measured_positioning,
        junction_balance=junction_balance,
    )
    axes = deformed_helix_axes(design)
    lookup = {(n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
              for n in nucleotides}
    _apply_ovhg_rotations_to_axes(design, axes, nuc_lookup=lookup)
    return _positions_by_helix(nucleotides), axes
