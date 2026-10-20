"""Closed, provisional admission for native Full DNA comparison.

This is display admission, not molecular validation or a construction recipe.
All counts precede native array allocation. Limits remain provisional until the
host qualifies the complete projection; no normal geometry path uses them.
"""

from dataclasses import dataclass

from backend.core.models import Design, Direction, StrandType
from backend.core.part_comparison_projection import _identity, _reject, _unique
from backend.core.part_history_contract import FIELD_ROLES


COMPONENT_VERSION = 3
# Sized for ordinary origami parts (see part_deformation_preview); runaway guards.
MAX_HELICES = 512
MAX_STRANDS = 50_000
MAX_DOMAINS = 200_000
MAX_OPERATIONS = 2_048
MAX_SLOTS = 2_000_000
MAX_SELECTORS = 50_000
MAX_PATH_STATIONS = 200_000
MAX_AXIS_POINTS = 2_000_000
DNA_FIELDS = frozenset({"lattice_frames", "helices", "strands", "deformations",
    "cluster_transforms", "nucleotide_transforms", "overhangs", "crossovers",
    "crossover_constraints", "forced_ligations"})
ALLOWED_AUTHORING = DNA_FIELDS | frozenset({"dimensions", "lattice_type", "metadata",
    "tm_settings", "nanoparticles", "protein_assets", "protein_attachments", "group_organization"})


def _limit(value, maximum, label):
    if type(value) is not int or value < 0 or value > maximum:
        _reject(f"DNA comparison {label} exceeds its display allowance", "comparison_limit")


def _bp(value):
    if type(value) is not int or abs(value) > 1_000_000:
        _reject("DNA comparison requires bounded integer bp addresses", "comparison_limit")
    return value


def check_scope(design, *, checkpoint=lambda: None):
    """Count prospective work on a lock-owned source; no derivation or hashing.

    Native geometry builds both sides of complete helices before occupancy
    filtering. Extended domains allocate the entire interval to the helix edge,
    even when only a remote endpoint is occupied. Both costs are counted here.
    """
    if type(design) is not Design or set(type(design).model_fields) != set(FIELD_ROLES):
        _reject("DNA comparison requires the reviewed mutable standard-part schema")
    for name, role in FIELD_ROLES.items():
        checkpoint()
        if role == "authoring" and name not in ALLOWED_AUTHORING and getattr(design, name):
            _reject(f"DNA comparison does not yet cover {name}")
    _limit(len(design.helices), MAX_HELICES, "helix count")
    _limit(len(design.strands), MAX_STRANDS, "strand count")
    _limit(len(design.deformations) + len(design.cluster_transforms), MAX_OPERATIONS, "operation count")
    for field in DNA_FIELDS - {"helices", "strands", "deformations", "cluster_transforms"}:
        _limit(len(getattr(design, field)), MAX_SELECTORS, field)
    indices = {field: _unique(getattr(design, field), field, checkpoint) for field in DNA_FIELDS}
    helices = indices["helices"]
    extent, slots = {}, 0
    for helix in helices.values():
        checkpoint()
        if helix.id.startswith(("__lnk__", "__np__", "__strep_dna__")) or helix.native_residues or helix.native_source:
            _reject("Native-residue and attachment helices need a separately reviewed DNA projection")
        _limit(helix.length_bp, MAX_SLOTS // 2, "helix span")
        if helix.length_bp == 0:
            _reject("DNA comparison requires positive helix spans", "invalid_comparison_geometry")
        start = _bp(helix.bp_start)
        extent[helix.id] = [start, start + helix.length_bp - 1]
        _limit(len(helix.loop_skips), MAX_SLOTS, "loop/skip count")
        insertions = 0
        for change in helix.loop_skips:
            checkpoint()
            bp = _bp(change.bp_index)
            if type(change.delta) is not int or change.delta not in {-1, 1}:
                _reject("DNA comparison requires ordinary loop/skip marks")
            if not start <= bp < start + helix.length_bp:
                _reject("A DNA loop/skip target lies outside its helix", "invalid_comparison_reference")
            insertions += max(0, change.delta)
        slots += 2 * (helix.length_bp + insertions)
        _limit(slots, MAX_SLOTS, "prospective nucleotide slots")
    domains, walk = 0, 0
    for strand in design.strands:
        checkpoint()
        if strand.strand_type not in {StrandType.SCAFFOLD, StrandType.STAPLE} or strand.id.startswith("__lnk__"):
            _reject("Linker and binder strands need a separately reviewed DNA projection")
        domains += len(strand.domains)
        _limit(domains, MAX_DOMAINS, "domain count")
        _limit(len(strand.routing_seed or []), MAX_DOMAINS, "routing seed count")
        if not strand.domains:
            _reject("DNA comparison requires occupied strand domains", "invalid_comparison_reference")
        for domain in strand.domains:
            checkpoint()
            hid = _identity(domain.helix_id)
            if hid not in helices:
                _reject("A DNA domain refers to a missing helix", "invalid_comparison_reference")
            lo, hi = sorted((_bp(domain.start_bp), _bp(domain.end_bp)))
            walk += hi - lo + 1
            _limit(walk, MAX_SLOTS, "occupied domain walk")
            if domain.binds_overhang_id is not None:
                _reject("Bound overhang domains need a separate complete projection")
            if domain.direction not in {Direction.FORWARD, Direction.REVERSE}:
                _reject("A DNA domain has no supported direction", "invalid_comparison_reference")
            if ((domain.direction == Direction.FORWARD and domain.start_bp > domain.end_bp)
                    or (domain.direction == Direction.REVERSE and domain.start_bp < domain.end_bp)):
                _reject("A DNA domain disagrees with its native traversal direction", "invalid_comparison_reference")
            extent[hid][0], extent[hid][1] = min(extent[hid][0], lo), max(extent[hid][1], hi)
    for hid, (lo, hi) in extent.items():
        helix = helices[hid]
        slots += 2 * (helix.bp_start - lo + hi - (helix.bp_start + helix.length_bp - 1))
        _limit(slots, MAX_SLOTS, "extended prospective nucleotide slots")
    if design.deformations and extent:
        # Native arm frame tables span the interval from the first arm bp to
        # the last requested site, including empty gaps between short helices.
        _limit(max(hi for _, hi in extent.values()) - min(lo for lo, _ in extent.values()) + 1,
               MAX_SLOTS, "deformed arm span")
    from backend.core.part_dna_display_scope import organization_index
    indices["group_organization"], selectors = organization_index(design, checkpoint, indices)
    stations = 0
    for cluster in design.cluster_transforms:
        checkpoint()
        selectors += len(cluster.helix_ids) + len(cluster.domain_ids)
        if cluster.overhang_duplex_driver_id is not None:
            _reject("Duplex-owned clusters need a separate complete projection")
    for op in design.deformations:
        checkpoint()
        selectors += len(op.affected_helix_ids) + len(op.cluster_ids) + len(op.targets or []) + len(op.target_ranges or [])
        _bp(op.plane_a_bp), _bp(op.plane_b_bp)
        if op.type != op.params.kind or op.type not in {"twist", "bend", "sweep"}:
            _reject("DNA comparison requires native deformation definitions")
        if op.type == "sweep":
            params = op.params
            stations += len(params.points_nm) + len(params.bp_positions_nm or []) + len(params.bp_frames or [])
            stations += len(params.point_frames or []) + len(params.warning_bps)
            selectors += len(params.preceding_op_ids)
            _limit(params.steps, MAX_SLOTS, "sweep steps")
            _bp(params.start_step)
        _limit(stations, MAX_PATH_STATIONS, "path stations")
    for constraint in design.crossover_constraints:
        checkpoint()
        selectors += len(constraint.helix_ids_a) + len(constraint.helix_ids_b) + len(constraint.allowed_bp_intervals)
    for overhang in design.overhangs:
        checkpoint()
        if overhang.parent_overhang_id is not None or overhang.auxiliary_endpoint or overhang.strand_anim_setup:
            _reject("Chained, auxiliary or animated overhangs need a separate complete projection")
        selectors += len(overhang.sub_domains)
    _limit(selectors, MAX_SELECTORS, "selector count")
    for item in [*design.crossovers, *design.forced_ligations]:
        checkpoint()
        if item.extra_bases:
            _reject("Inserted crossover bases need a separate complete projection")
    for item in design.nucleotide_transforms:
        checkpoint()
        if item.kind != "base":
            _reject("Inserted-base transforms need a separate complete projection")
    return indices


@dataclass(frozen=True)
class Inventory:
    """Expected occupied sites, independent of display-kernel omissions."""

    sites: dict
    indices: dict


def inventory(design, *, previous=None):
    """Validate exact references on already-owned, bounded worker inputs."""
    from backend.core.part_scope_references import COLLECTIONS, referenced_resources
    from backend.core.part_dna_display_scope import validate_owned_organization

    indices = check_scope(design)
    validate_owned_organization(design)
    resources = {(COLLECTIONS[field], identity) for field, entries in indices.items()
                 if field != "group_organization" for identity in entries}
    resources.update(("part_group", identity) for identity in indices["group_organization"])
    subdomains = _unique([sub for overhang in design.overhangs for sub in overhang.sub_domains], "subdomain", lambda: None)
    resources.update(("sub_domain", identity) for identity in subdomains)
    for field in DNA_FIELDS:
        for item in getattr(design, field):
            try:
                if field == "deformations":
                    from backend.core.part_dna_display_scope import deformation_references
                    references = deformation_references(item)
                else:
                    references = referenced_resources(item)
            except NotImplementedError as error:
                _reject(str(error))
            if references - resources:
                _reject(f"DNA comparison has an unresolved {field} reference", "invalid_comparison_reference")
    strands = indices["strands"]

    def domain_ref(strand_id, domain_index):
        strand = strands.get(strand_id)
        if strand is None or type(domain_index) is not int or not 0 <= domain_index < len(strand.domains):
            _reject("DNA comparison has an unresolved domain selection", "invalid_comparison_reference")
        return strand.domains[domain_index]

    for cluster in design.cluster_transforms:
        for ref in cluster.domain_ids:
            domain_ref(ref.strand_id, ref.domain_index)
        visited, current = set(), cluster
        while current.parent_cluster_id is not None:
            if current.id in visited:
                _reject("DNA comparison has a cyclic cluster hierarchy", "invalid_comparison_reference")
            visited.add(current.id)
            if not current.domain_ids:
                _reject("Child clusters require explicit domain membership", "invalid_comparison_reference")
            current = indices["cluster_transforms"][current.parent_cluster_id]
    for op in design.deformations:
        for target in (op.targets or []) if op.target_ranges is None else []:
            if target["kind"] == "domain":
                domain_ref(target.get("strand_id", target.get("strandId")), target.get("domain_index", target.get("domainIndex")))
    # Occupancy is topology-only. Exact model equality (including loop copies,
    # ordered domains and overhang ownership) permits reuse within a private
    # preview session. Scope and changing deformation references above, and all
    # emitted coordinate/inventory checks in the projection, still run.
    if previous is not None and all(indices[name] == previous.indices[name]
                                    for name in ("helices", "strands", "overhangs")):
        sites = previous.sites
    else:
        sites = _occupied_sites(design)
    _limit(len(sites), MAX_SLOTS, "emitted nucleotide count")
    for item in design.nucleotide_transforms:
        key = item.helix_id, item.bp_index, item.direction.value, item.copy_k
        if key not in sites:
            _reject("A nucleotide pose target is not occupied", "invalid_comparison_reference")
    for item in design.crossovers:
        for half in (item.half_a, item.half_b):
            if (half.helix_id, half.index, half.strand.value, 0) not in sites:
                _reject("A crossover endpoint is not occupied", "invalid_comparison_reference")
    for item in design.forced_ligations:
        for end in ("three_prime", "five_prime"):
            key = (getattr(item, end + "_helix_id"), getattr(item, end + "_bp"), getattr(item, end + "_direction").value, 0)
            if key not in sites:
                _reject("A forced-ligation endpoint is not occupied", "invalid_comparison_reference")
    return Inventory(sites, indices)


def _occupied_sites(design):
    deltas = {}
    for helix in design.helices:
        for change in helix.loop_skips:
            key = helix.id, change.bp_index
            deltas[key] = deltas.get(key, 0) + change.delta
    occupied, sites, overhang_owners = set(), {}, {}
    for strand in design.strands:
        for index, domain in enumerate(strand.domains):
            if domain.overhang_id:
                if domain.overhang_id in overhang_owners:
                    _reject("An overhang has ambiguous domain ownership", "invalid_comparison_reference")
                overhang_owners[domain.overhang_id] = (strand.id, index, domain)
            for bp in range(min(domain.start_bp, domain.end_bp), max(domain.start_bp, domain.end_bp) + 1):
                key = domain.helix_id, bp, domain.direction.value
                if key in occupied:
                    _reject("Two domains occupy the same DNA site", "invalid_comparison_reference")
                occupied.add(key)
                for copy in range(max(0, 1 + deltas.get((domain.helix_id, bp), 0))):
                    sites[(*key, copy)] = (strand.id, index, domain.overhang_id, strand.is_reference)
    _limit(len(sites), MAX_SLOTS, "emitted nucleotide count")
    for overhang in design.overhangs:
        owner = overhang_owners.get(overhang.id)
        if owner is None or owner[0] != overhang.strand_id or owner[2].helix_id != overhang.helix_id:
            _reject("An overhang has no exact occupied owner", "invalid_comparison_reference")
    return sites
