"""Prospective work admission for ordinary native preview producers.

This adapter selects no geometry and supplies no replay authority. The shared
executor remains responsible for identities, topology, polarity and errors.
Bounds reuse the preview's existing site/helix/span limits; conservative growth
also counts temporary restored and rebuilt topology before native allocation.
Numerical convert/relax commands deliberately remain in their worker lane.
"""

from bisect import bisect_left, bisect_right
from math import isfinite

from backend.core.part_capture_graph import CaptureLimit, GraphBudget


KINDS = frozenset({"overhang-extrude", "overhang-sequence", "overhang_rotation", "overhang-bulk",
    "linker-add", "linker-patch", "linker-delete", "duplex-create", "duplex-connect",
    "duplex-patch", "duplex-delete", "duplex-sync-bindings", "extension-upsert", "extension-delete"})
SUBDOMAINS = frozenset({"sub-domain-split", "sub-domain-merge", "sub-domain-patch",
    "sub-domain-recompute-annotations", "tm-settings-update", "resize-free-end"})
BINDINGS = frozenset({"overhang-binding-create", "overhang-binding-patch", "overhang-binding-delete"})
PENDING = frozenset({"connection-version-create", "connection-version-patch", "connection-version-delete"})
APPLY = "connection-version-apply-linker"


def _preview():
    # Lazy to keep the shared replay module independent at import time.
    from backend.api import part_deformation_preview
    return part_deformation_preview


def _limit(message):
    _preview()._reject(message, "preview_limit")


def _length(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= _preview().MAX_SLOTS:
        _limit("Producer span exceeds the private preview site allowance")
    return value


class _Work:
    def __init__(self, design):
        p = _preview()
        p._work(design, lambda: None)
        self.design, self.sites, self.added_helices, self.added_walk = design, 0, 0, 0
        self.helices = {h.id: h for h in design.helices}
        self.loops = {}
        for helix in design.helices:
            if len(helix.loop_skips) > p.MAX_SLOTS:
                _limit("Producer loop inventory exceeds the preview work allowance")
            self.loops[helix.id] = sorted(mark.bp_index for mark in helix.loop_skips if mark.delta > 0
                for _ in range(_length(mark.delta)))
        self.walk = sum(self.domain(domain) for strand in design.strands for domain in strand.domains)
        if self.walk > p.MAX_SLOTS:
            _limit("Producer domain copies exceed the preview work allowance")
        # These strings/subdomain spans feed native annotation/sequence helpers,
        # even if their owner is not currently part of a rendered domain.
        sequences = sum(len(o.sequence or "") + sum(len(sd.sequence_override or "") for sd in o.sub_domains)
                        for o in design.overhangs)
        subdomains = sum(sd.length_bp for o in design.overhangs for sd in o.sub_domains)
        if max(sequences, subdomains, sum(len(s.sequence or "") for s in design.strands)) > p.MAX_SLOTS:
            _limit("Producer sequence inventory exceeds the preview work allowance")
        self.restored_walk = {}
        self.saved_budget = GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None, clock=lambda: 0)

    def domain(self, domain):
        lo, hi = sorted((domain.start_bp, domain.end_bp))
        positions = self.loops.get(domain.helix_id, ())
        return hi - lo + 1 + bisect_right(positions, hi) - bisect_left(positions, lo)

    def grow(self, sites=0, walk=0, helices=0):
        self.sites += sites
        self.added_walk += walk
        self.added_helices += helices
        _preview()._growth(self.design, self.sites, self.added_helices)
        if self.walk + self.added_walk > _preview().MAX_SLOTS:
            _limit("Prospective producer domain work exceeds the preview allowance")

    def sequence(self, identity, sequence):
        if sequence is None or sequence == "":
            return
        if type(sequence) is not str:
            _preview()._reject("Producer sequence must be text", "invalid_preview_definition")
        length = _length(len(sequence))
        spec = next((o for o in self.design.overhangs if o.id == identity), None)
        if spec is None:
            return  # Preserve the native exact missing-reference diagnostic.
        host = self.helices.get(spec.helix_id)
        inline = identity.startswith("ovhg_inline_")
        if host is not None and not inline:
            delta = max(0, length - host.length_bp)
            self.grow(2 * delta)
            _preview()._span(self.design, host.bp_start - delta,
                host.bp_start + host.length_bp - 1 + delta)
        for strand in self.design.strands:
            for domain in strand.domains:
                if domain.overhang_id != identity:
                    continue
                delta = max(0, length - abs(domain.end_bp - domain.start_bp) - 1)
                # Both possible terminal directions are admitted conservatively;
                # the unchanged builder alone chooses the native free end.
                _preview()._span(self.design, min(domain.start_bp, domain.end_bp) - delta,
                    max(domain.start_bp, domain.end_bp) + delta)
                self.grow(2 * delta if inline else 0,
                    delta + (len(self.loops.get(domain.helix_id, ())) if delta else 0))

    def relocate(self, identities, *, driver=None):
        from backend.core.lattice import _find_overhang_domain
        domains = {identity: _find_overhang_domain(self.design, identity) for identity in identities}
        if len(domains) != 2 or any(value is None for value in domains.values()):
            return  # Native reference validation still owns missing anchors.
        visits = {identity: self.restored_walk.get(identity, self.domain(domain))
                  for identity, domain in domains.items()}
        if driver in visits:
            driven = next(identity for identity in visits if identity != driver)
            increase = max(0, visits[driver] - visits[driven])
        else:
            # Heuristic driver choice remains exclusively native. The larger
            # endpoint bounds either choice, including insertion copies.
            increase = max(visits.values()) - min(visits.values())
        self.grow(walk=increase)

    def restore(self, owner):
        value = owner.prior_driven_topology
        if value is None:
            return
        # Native model_dump emits a JSON tree. Reject sharing/cycles before a
        # Pydantic parse can expand aliases beyond the capture-sized budget.
        containers = set()
        def shape(item):
            if type(item) in {dict, list}:
                if id(item) in containers:
                    raise ValueError("Saved topology requires a JSON tree without container aliases")
                containers.add(id(item))
                if type(item) is dict and any(type(key) is not str for key in item):
                    raise ValueError("Saved topology keys must be strings")
            elif item is None or type(item) in {str, bool}:
                pass
            elif type(item) is int and item.bit_length() <= 64:
                pass
            elif type(item) is float and isfinite(item):
                pass
            else:
                raise ValueError("Saved topology contains unsupported JSON values")
        try:
            self.saved_budget.charge(value, validate=shape, reject_cycles=True)
        except CaptureLimit as error:
            _limit(str(error))
        except ValueError as error:
            _preview()._reject(str(error), "invalid_preview_definition")
        from backend.core.part_saved_topology import snapshot_for
        try:
            saved = snapshot_for(owner)
        except (ValueError, TypeError, KeyError, NotImplementedError) as error:
            _preview()._reject(str(error), "invalid_preview_definition")
        if saved is None:
            return
        helix = saved.helix
        length = _length(helix.length_bp)
        if len(helix.loop_skips) > _preview().MAX_SLOTS:
            _limit("Restored loop inventory exceeds the preview work allowance")
        loops = sum(max(0, mark.delta) for mark in helix.loop_skips)
        prior = saved.value["prior_domain"]
        domain_length = _length(abs(prior["end_bp"] - prior["start_bp"]) + 1)
        extras = sum(len(item.extra_bases or "") for item in saved.crossovers)
        if saved.ligation is not None:
            extras += len(saved.ligation.extra_bases or "")
        self.restored_walk[saved.value["driven_oh_id"]] = domain_length + loops
        self.grow(2 * (length + loops) + extras, domain_length + loops,
            int(helix.id not in self.helices))
        _preview()._span(self.design, helix.bp_start, helix.bp_start + length - 1,
            prior["start_bp"], prior["end_bp"])


def _extrude(work, params):
    p = _preview()
    length, bp = _length(params.get("length_bp")), p._bp(params.get("bp_index"))
    p._span(work.design, bp - length + 1, bp + length - 1)
    overhang_hosts = {o.helix_id for o in work.design.overhangs}
    cell = (params.get("neighbor_row"), params.get("neighbor_col"))
    reused = next((h for h in work.design.helices if params.get("reuse_existing_helix", True)
        and h.grid_pos is not None and tuple(h.grid_pos) == cell and h.id in overhang_hosts), None)
    if reused is None:
        work.grow(2 * length, length, 1)
    else:
        lo, hi = reused.bp_start, reused.bp_start + reused.length_bp - 1
        # Bound either native orientation, including the unoccupied gap; do not
        # duplicate the molecular strand-polarity choice in this adapter.
        extent = max(max(hi, bp) - min(lo, bp - length + 1) + 1,
                     max(hi, bp + length - 1) - min(lo, bp) + 1)
        work.grow(2 * (extent - reused.length_bp), length + len(work.loops[reused.id]))


def _linker_length(value, unit):
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.lattice import _length_value_to_bp
    bound = _preview().MAX_SLOTS * (BDNA_RISE_PER_BP if unit == "nm" else 1)
    if type(value) not in {int, float} or not isfinite(value) or not 0 <= value <= bound:
        _limit("Linker length exceeds the preview work allowance")
    if unit not in {"bp", "nm"}:
        _preview()._reject("Unsupported linker length unit", "invalid_preview_definition")
    return 0 if value == 0 else _length(_length_value_to_bp(value, unit))


def _linker(work, params, *, current=None):
    values = (current.model_dump(mode="json") if current is not None else {})
    values.update({key: value for key, value in params.items() if value is not None})
    length = _linker_length(values.get("length_value"), values.get("length_unit", "bp"))
    if current is not None and (values["length_value"], values["length_unit"]) == (current.length_value, current.length_unit):
        return
    from backend.core.lattice import _find_overhang_domain
    complements = [_find_overhang_domain(work.design, values.get(field))
                   for field in ("overhang_a_id", "overhang_b_id")]
    work.grow(2 * length, 2 * length + sum(work.domain(d) for d in complements if d is not None), int(length > 0))
    if length:
        _preview()._span(work.design, 0, length - 1)


def _apply_linker(work, params):
    from backend.api.part_connection_application_commands import parse_command
    from backend.api.routes_connection_versions import _cv_sequence_for_live_overhang
    body = parse_command(params)
    version = next((v for v in work.design.connection_versions if v.id == body.version_id), None)
    if version is None:
        return
    length = max(1, _length(version.bridge_length, zero=True))
    for identity, sequence in ((body.overhang_a_id, version.overhang_a_seq), (body.overhang_b_id, version.overhang_b_seq)):
        # Existing Apply fits stored text to the CURRENT backing length; stale
        # candidate strings must not be mistaken for a requested geometry resize.
        work.sequence(identity, _cv_sequence_for_live_overhang(work.design, identity, sequence))
    _linker(work, {"length_value": length, "length_unit": "bp",
        "overhang_a_id": body.overhang_a_id, "overhang_b_id": body.overhang_b_id})


def _extension(work, kind, params):
    from backend.api.part_extension_commands import parse_command
    values = parse_command(kind, params)
    if kind == "extension-delete":
        return
    counts = {e.id: len(e.sequence or "") + bool(e.modification) for e in work.design.extensions}
    before = sum(counts.values())
    for item in values["entries"]:
        ext = item["extension"]
        counts[ext["id"]] = len(ext["sequence"] or "") + bool(ext["modification"])
    work.grow(max(0, sum(counts.values()) - before))


def admit(kind, design, params):
    """Return whether this finite producer family was prospectively admitted."""
    if kind not in KINDS:
        return False
    action = params.get("action") if kind == "overhang-bulk" else None
    if kind == "overhang-bulk" and action not in SUBDOMAINS | BINDINGS | PENDING | {APPLY}:
        return False
    work = _Work(design)
    if kind == "overhang-extrude":
        _extrude(work, params)
    elif kind == "overhang-sequence":
        work.sequence(params.get("overhang_id"), params.get("sequence"))
    elif kind == "linker-add":
        _linker(work, params)
    elif kind == "linker-patch":
        current = next((c for c in design.overhang_connections if c.id == params.get("conn_id")), None)
        if current is not None:
            _linker(work, params, current=current)
    elif kind.startswith("duplex-"):
        from backend.api.part_duplex_commands import parse_command
        body = parse_command(kind, params)
        for side in (getattr(body, "left", None), getattr(body, "right", None)):
            if side is not None:
                _length(abs(side.end_bp - side.start_bp) + 1)
                _preview()._span(design, side.start_bp, side.end_bp)
        linked = [owner for identity in getattr(body, "binding_ids", None) or ()
                  for owner in design.overhang_bindings if owner.id == identity]
        for owner in linked:
            if kind == "duplex-patch" and owner.bound:
                work.restore(owner)
        if kind == "duplex-connect" and not body.binding_ids:
            endpoints = (body.overhang_a_id, body.overhang_b_id)
            driver = endpoints[0 if body.driver == "left" else 1] if body.driver else None
            work.relocate(endpoints, driver=driver)
        elif kind == "duplex-patch" and linked and linked[0].bound and linked[0].prior_driven_topology:
            current = next((edge for edge in design.duplexes if edge.id == body.duplex_id), None)
            if current is not None:
                endpoints = ((body.left or current.left).overhang_id, (body.right or current.right).overhang_id)
                work.relocate(endpoints, driver=endpoints[0 if (body.driver or current.driver) == "left" else 1])
        if kind == "duplex-connect" and len(design.cluster_transforms) + len(design.deformations) + 1 > _preview().MAX_OPERATIONS:
            _limit("Duplex placement exceeds the preview object allowance")
    elif kind.startswith("extension-"):
        _extension(work, kind, params)
    elif action in PENDING:
        from backend.api.part_connection_version_commands import parse_command
        parse_command(params)
    elif action == APPLY:
        _apply_linker(work, params)
    elif action == "overhang-binding-patch":
        owner = next((b for b in design.overhang_bindings if b.id == params.get("binding_id")), None)
        if owner is not None and owner.bound and params.get("bound") is False:
            work.restore(owner)
        elif owner is not None and not owner.bound and params.get("bound") is True:
            work.relocate((owner.overhang_a_id, owner.overhang_b_id), driver=owner.driver_oh_id)
    elif action == "resize-free-end":
        delta = abs(_preview()._bp(params.get("delta_bp")))
        _length(delta, zero=True)
        spec = next((o for o in design.overhangs if o.id == params.get("overhang_id")), None)
        insertions = len(work.loops.get(spec.helix_id, ())) if spec is not None and delta else 0
        work.grow(2 * delta, delta + insertions)
        if spec is not None and spec.helix_id in work.helices:
            helix = work.helices[spec.helix_id]
            _preview()._span(design, helix.bp_start - delta, helix.bp_start + helix.length_bp - 1 + delta)
    elif action in SUBDOMAINS:
        sequence = params.get("sequence_override")
        if sequence:
            _length(len(sequence))
    return True
