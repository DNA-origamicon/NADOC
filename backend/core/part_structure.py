"""Bounded structural reference diagnostics, separate from scientific validity.

Cluster/frame identities and frame/cell references are checked for all designs.
Explicit separate organization additionally checks its typed member references;
legacy None never adds a strand walk. No geometry, serialization or repair occurs.
"""

MAX_ITEMS = 30_000
MAX_ISSUES = 100
MAX_ID_CHARS = 512
_COLLECTIONS = (("cluster_transforms", "clusters", "cluster"),
                ("lattice_frames", "frames", "lattice_frame"),
                ("helices", "helices", "helix"))


class _Incomplete(Exception):
    def __init__(self, code, *, maximum=None, model_path=None):
        self.detail = {"code": code}
        if maximum is not None:
            self.detail["maximum"] = maximum
        if model_path is not None:
            self.detail["model_path"] = model_path


def assess_structure(design, *, checkpoint=None, max_items=MAX_ITEMS, max_issues=MAX_ISSUES):
    """Return JSON diagnostics for this narrow structural check only.

    Item allowance counts collection records, checked before indexing. Issue
    allowance stops at the first omitted diagnostic; ``incomplete`` can never
    mean valid, including when some errors were already observed. Checkpoint
    exceptions propagate unchanged so cancellation/deadline policy stays with
    the caller. Identity strings are bounded before any dictionary/set lookup.
    """
    if any(type(value) is not int or value < 0 for value in (max_items, max_issues)):
        raise ValueError("Structural allowances must be nonnegative integers")
    check = checkpoint if checkpoint is not None else lambda: None
    result = {"scope": "part_structural_references", "version": 1,
              "status": "valid", "complete": True, "scientific_integrity_checked": False,
              "checked_counts": {"clusters": 0, "frames": 0, "helices": 0},
              "observed_errors": 0, "issues": []}

    def issue(code, path, kind, identity, **extra):
        result["observed_errors"] += 1
        if len(result["issues"]) >= max_issues:
            raise _Incomplete("structure_issue_limit", maximum=max_issues)
        result["issues"].append({"code": code, "model_path": path,
                                 "resource": {"kind": kind, "identity": identity}, **extra})

    def identity(value, path, kind, owner=None):
        if type(value) is not str or not value:
            issue("invalid_identity", path, kind, owner)
            return None
        if len(value) > MAX_ID_CHARS:
            raise _Incomplete("structure_identity_limit", maximum=MAX_ID_CHARS, model_path=path)
        return value

    def index(values, field, count, kind):
        first, ambiguous, keys = {}, set(), []
        root = [field] if type(field) is str else list(field)
        for position, item in enumerate(values):
            check()
            result["checked_counts"][count] += 1
            path = [*root, position, "id"]
            key = identity(item.id, path, kind)
            keys.append(key)
            if key is None:
                continue
            if key in first:
                ambiguous.add(key)
                issue("duplicate_identity", path, kind, key,
                      first_model_path=[*root, first[key], "id"])
            else:
                first[key] = position
        return first, ambiguous, keys

    def reference(value, path, kind, owner, target_kind, target_index):
        target = identity(value, path, kind, owner)
        if target is None:
            return
        first, ambiguous, _ = target_index
        code = "ambiguous_reference" if target in ambiguous else "missing_reference" if target not in first else None
        if code:
            issue(code, path, kind, owner, reference={"kind": target_kind, "identity": target})
            return None
        return target

    try:
        check()
        collections = {}
        total = 0
        for field, _, _ in _COLLECTIONS:
            values = getattr(design, field, None)
            if type(values) is not list:
                raise _Incomplete("structure_input_shape", model_path=[field])
            total += len(values)
            if total > max_items:
                raise _Incomplete("structure_item_limit", maximum=max_items)
            collections[field] = values
        organization = getattr(design, "group_organization", None)
        if organization is not None:
            from backend.core.models import Domain, Strand
            from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup

            if (type(organization) is not GroupOrganization
                    or type(organization.version) is not int or organization.version != 1
                    or type(organization.groups) is not list or type(design.strands) is not list):
                raise _Incomplete("structure_input_shape", model_path=["group_organization"])
            groups, strands = organization.groups, design.strands
            total += len(groups) + len(strands)
            if total > max_items:
                raise _Incomplete("structure_item_limit", maximum=max_items)
            # Reserve all group-member occurrences before any identity index or
            # member traversal. Domain addresses are O(1) indexes, not full
            # strand/domain scans. Repeated references still consume allowance.
            for position, group in enumerate(groups):
                check()
                path = ["group_organization", "groups", position]
                if (type(group) is not PartGroup or type(group.helix_ids) is not list
                        or type(group.domain_ids) is not list):
                    raise _Incomplete("structure_input_shape", model_path=path)
                total += len(group.helix_ids) + len(group.domain_ids)
                if total > max_items:
                    raise _Incomplete("structure_item_limit", maximum=max_items)
            result["checked_counts"].update(part_groups=0, strands=0, group_members=0)
        indexes = {field: index(collections[field], field, count, kind)
                   for field, count, kind in _COLLECTIONS}
        for position, frame in enumerate(collections["lattice_frames"]):
            check()
            reference(frame.placement_cluster_id, ["lattice_frames", position, "placement_cluster_id"],
                      "lattice_frame", indexes["lattice_frames"][2][position], "cluster", indexes["cluster_transforms"])
        for position, helix in enumerate(collections["helices"]):
            check()
            if helix.lattice_frame_id is None:
                continue  # Unframed legacy/native helices need no frame or local cell.
            owner = indexes["helices"][2][position]
            reference(helix.lattice_frame_id, ["helices", position, "lattice_frame_id"],
                      "helix", owner, "lattice_frame", indexes["lattice_frames"])
            if helix.grid_pos is None:
                issue("missing_lattice_cell", ["helices", position, "grid_pos"], "helix", owner)
        if organization is not None:
            for position, strand in enumerate(strands):
                check()
                if type(strand) is not Strand:
                    raise _Incomplete("structure_input_shape", model_path=["strands", position])
            strand_index = index(strands, "strands", "strands", "strand")
            group_index = index(groups, ("group_organization", "groups"), "part_groups", "part_group")
            for position, group in enumerate(groups):
                owner = group_index[2][position]
                base = ["group_organization", "groups", position]
                for offset, helix_id in enumerate(group.helix_ids):
                    check()
                    result["checked_counts"]["group_members"] += 1
                    reference(helix_id, [*base, "helix_ids", offset], "part_group", owner,
                              "helix", indexes["helices"])
                for offset, member in enumerate(group.domain_ids):
                    check()
                    result["checked_counts"]["group_members"] += 1
                    path = [*base, "domain_ids", offset]
                    if type(member) is not GroupDomainRef:
                        raise _Incomplete("structure_input_shape", model_path=path)
                    strand_id = reference(member.strand_id, [*path, "strand_id"], "part_group", owner,
                                          "strand", strand_index)
                    if type(member.domain_index) is not int or member.domain_index < 0:
                        issue("invalid_reference", [*path, "domain_index"], "part_group", owner)
                        continue
                    if member.domain_index.bit_length() > 64:
                        raise _Incomplete("structure_identity_limit", maximum=64,
                                          model_path=[*path, "domain_index"])
                    if strand_id is None:
                        continue
                    strand = strands[strand_index[0][strand_id]]
                    if type(strand.domains) is not list:
                        raise _Incomplete("structure_input_shape", model_path=[
                            "strands", strand_index[0][strand_id], "domains"])
                    if member.domain_index >= len(strand.domains):
                        issue("missing_reference", [*path, "domain_index"], "part_group", owner,
                              reference={"kind": "domain", "identity": f"{strand_id}:{member.domain_index}"})
                        continue
                    domain = strand.domains[member.domain_index]
                    if type(domain) is not Domain:
                        raise _Incomplete("structure_input_shape", model_path=[
                            "strands", strand_index[0][strand_id], "domains", member.domain_index])
                    reference(domain.helix_id, [*path, "domain_index"], "part_group", owner,
                              "helix", indexes["helices"])
        check()
    except _Incomplete as error:
        result.update(status="incomplete", complete=False, limit=error.detail)
        return result
    if result["issues"]:
        result["status"] = "invalid"
    return result
