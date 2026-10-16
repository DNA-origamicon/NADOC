"""Passive native resize/shift observations preserve contributor ancestry.

Tiny in-memory fixtures exercise real native topology. The organization-free
builder is the complete model oracle; membership expectations are explicit.
No publication, file, worker, atomistic builder or simulation is involved.
"""

import pytest

from backend.api import crud
from backend.api.part_proof_commands import execute
from backend.core import lattice, models as m
from backend.core.cluster_reconcile import reconcile_cluster_membership
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.part_command_errors import CommandContractError
from tests.test_part_group_lineage import grouped, refs, selected_domains


KINDS = ("strand-end-resize", "domain-shift")


def source(direction=m.Direction.FORWARD, *, scaffold=True, native=False):
    forward = direction == m.Direction.FORWARD
    helix = m.Helix(id="h", axis_start=m.Vec3(x=0, y=0, z=0),
        axis_end=m.Vec3(x=0, y=0, z=79 * RISE), length_bp=80)
    strands = [m.Strand(id="stap", strand_type=m.StrandType.STAPLE,
        domains=[m.Domain(helix_id="h", direction=direction,
                          start_bp=14 if forward else 25, end_bp=25 if forward else 14)])]
    if scaffold:
        strands.insert(0, m.Strand(id="scaf", strand_type=m.StrandType.SCAFFOLD,
            domains=[m.Domain(helix_id="h", direction=m.Direction.REVERSE if forward else m.Direction.FORWARD,
                              start_bp=29 if forward else 10, end_bp=10 if forward else 29)]))
    if native:
        # Typed address anchors trigger the native core/tail topology branch.
        # These two records are deliberately not an atomistic geometry fixture.
        helix = helix.model_copy(update={"native_residues": [
            m.NativeResidue(bp_index=bp, base="A", source_residue=str(bp), atoms={})
            for bp in (10, 29)]})
        strands[-1] = strands[-1].model_copy(update={"sequence": "A" * 12})
    return m.Design(helices=[helix], strands=strands)


def outward(direction, end):
    return -1 if (direction == m.Direction.FORWARD) == (end == "5p") else 1


def resize_entry(*, end="3p", delta=1, sid="stap"):
    return {"strand_id": sid, "helix_id": "h", "end": end, "delta_bp": delta}


def shift_entry(*, index=0, delta=1, sid="stap"):
    return {"strand_id": sid, "domain_index": index, "delta_bp": delta}


def native(kind, design, entries, *, lineage=None, pass_observer=False):
    kwargs = {"lineage": lineage} if pass_observer else {}
    if kind == "strand-end-resize":
        return crud._build_strand_end_resize(design, crud.StrandEndResizeRequest(entries=entries), **kwargs)
    return crud._build_domain_shift(design, crud.DomainShiftRequest(entries=entries), **kwargs)


def completed(before, raw):
    return lattice.retry_pending_ligations(before, reconcile_cluster_membership(before, raw))


def inline_source(direction=m.Direction.FORWARD, end="3p", *, native=False):
    design = source(direction, native=native)
    return lattice.resize_strand_ends(design, [resize_entry(end=end, delta=8 * outward(direction, end))])


def organize_inline(design, end):
    core, tail = (1, 0) if end == "5p" else (0, 1)
    return grouped(design, [[("stap", core)], [("stap", tail)], [("stap", core)]], whole=True)


def parity(design, kind, entries):
    saved = design.model_dump(mode="json")
    bare = design.copy_with(group_organization=None)
    expected = completed(bare, native(kind, bare, entries))
    actual = execute(kind, design, {"_proof_version": 1, "entries": entries})
    assert actual.model_dump(mode="json", exclude={"group_organization"}) == expected.model_dump(
        mode="json", exclude={"group_organization"})
    assert design.model_dump(mode="json") == saved
    assert actual.group_organization is not design.group_organization
    for before, after in zip(design.group_organization.groups, actual.group_organization.groups):
        assert before.model_dump(exclude={"helix_ids", "domain_ids"}) == after.model_dump(
            exclude={"helix_ids", "domain_ids"})
    return actual


@pytest.mark.parametrize("direction", list(m.Direction))
@pytest.mark.parametrize("end", ["5p", "3p"])
def test_native_control_creates_inline_split_and_trims_it_back(direction, end):
    design = inline_source(direction, end)
    strand = design.find_strand("stap")
    assert len(strand.domains) == 2 and len(design.overhangs) == 1
    tail = strand.domains[0 if end == "5p" else -1]
    assert tail.overhang_id is not None and abs(tail.end_bp - tail.start_bp) + 1 == 4
    trimmed = native("strand-end-resize", design,
        [resize_entry(end=end, delta=-6 * outward(direction, end))])
    assert len(trimmed.find_strand("stap").domains) == 1
    assert trimmed.find_strand("stap").domains[0].overhang_id is None
    assert trimmed.overhangs == []


class ScalarObserver:
    """Observe actual native decisions without returning or changing topology."""
    def __init__(self):
        self.events = []

    @staticmethod
    def domain(value):
        return value.helix_id, value.direction, value.start_bp, value.end_bp

    def repartition(self, sid, index, before_domains, after_domains):
        self.events.append(("repartition", sid, index,
            tuple(self.domain(item) for item in before_domains),
            tuple(self.domain(item) for item in after_domains)))

    def resize(self, sid, index, old_domain, new_domain, *, end):
        self.events.append(("resize", sid, index, self.domain(old_domain), self.domain(new_domain), end))

    def translate(self, sid, index, old_domain, new_domain):
        self.events.append(("translate", sid, index, self.domain(old_domain), self.domain(new_domain)))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("direction", list(m.Direction))
def test_observer_forwarding_is_passive_and_does_not_change_native_model(kind, direction):
    design = source(direction)
    entries = ([resize_entry(delta=8 * outward(direction, "3p"))] if kind == KINDS[0]
               else [shift_entry(delta=10)])
    saved = design.model_dump(mode="json")
    expected = native(kind, design, entries)
    observer = ScalarObserver()
    actual = native(kind, design, entries, lineage=observer, pass_observer=True)
    assert actual == expected and observer.events
    assert observer.events[0][0] == ("resize" if kind == KINDS[0] else "translate")
    assert any(event[0] == "repartition" for event in observer.events)
    assert design.model_dump(mode="json") == saved


@pytest.mark.parametrize("direction", list(m.Direction))
@pytest.mark.parametrize("end", ["5p", "3p"])
@pytest.mark.parametrize("growth", [False, True])
def test_plain_end_edit_follows_original_entity_without_inheriting_opposite_strand(direction, end, growth):
    design = grouped(source(direction), [[("stap", 0)], [("stap", 0)], [("scaf", 0)]], whole=True)
    delta = outward(direction, end) * (2 if growth else -2)
    result = parity(design, KINDS[0], [resize_entry(end=end, delta=delta)])
    assert refs(result) == refs(result, 1) == [("stap", 0)]
    assert refs(result, 2) == [("scaf", 0)]
    assert selected_domains(result, 2) == selected_domains(design, 2)


@pytest.mark.parametrize("direction", list(m.Direction))
@pytest.mark.parametrize("end", ["5p", "3p"])
def test_new_inline_split_selects_both_descendants_of_original_domain(direction, end):
    design = grouped(source(direction), [[("stap", 0)], [("stap", 0)]], whole=True)
    result = parity(design, KINDS[0], [resize_entry(end=end, delta=8 * outward(direction, end))])
    assert refs(result) == refs(result, 1) == [("stap", 0), ("stap", 1)]


@pytest.mark.parametrize("direction", list(m.Direction))
@pytest.mark.parametrize("end", ["5p", "3p"])
@pytest.mark.parametrize("native_core", [False, True])
def test_existing_core_and_tail_keep_separate_ancestry_through_internal_repartition(direction, end, native_core):
    design = organize_inline(inline_source(direction, end, native=native_core), end)
    result = parity(design, KINDS[0], [resize_entry(end=end, delta=2 * outward(direction, end))])
    assert refs(result) == refs(result, 2) == refs(design)
    assert refs(result, 1) == refs(design, 1)
    assert selected_domains(result) == selected_domains(design)


@pytest.mark.parametrize("direction", list(m.Direction))
@pytest.mark.parametrize("end", ["5p", "3p"])
@pytest.mark.parametrize("native_core", [False, True])
def test_fully_trimmed_tail_does_not_reappear_when_native_normalization_merges(direction, end, native_core):
    design = organize_inline(inline_source(direction, end, native=native_core), end)
    result = parity(design, KINDS[0], [resize_entry(end=end, delta=-6 * outward(direction, end))])
    assert refs(result) == refs(result, 2) == [("stap", 0)]
    assert refs(result, 1) == []
    assert result.group_organization.groups[1].helix_ids == []
    assert len(result.find_strand("stap").domains) == 1


@pytest.mark.parametrize("end", ["5p", "3p"])
def test_same_batch_temporary_inversion_keeps_terminal_entity_for_regrowth(end):
    direction = m.Direction.FORWARD
    design = organize_inline(inline_source(direction, end), end)
    sign = outward(direction, end)
    result = parity(design, KINDS[0], [resize_entry(end=end, delta=-6 * sign),
                                     resize_entry(end=end, delta=3 * sign)])
    assert refs(result) == refs(design)
    assert refs(result, 1) == refs(design, 1)
    tail, = selected_domains(result, 1)
    assert tail.start_bp == tail.end_bp


def test_separate_command_regrowth_cannot_resurrect_a_removed_tail_selection():
    design = organize_inline(inline_source(), "3p")
    trimmed = parity(design, KINDS[0], [resize_entry(delta=-6)])
    regrown = parity(trimmed, KINDS[0], [resize_entry(delta=6)])
    assert refs(regrown) == refs(regrown, 2) == [("stap", 0), ("stap", 1)]
    assert refs(regrown, 1) == [] and regrown.group_organization.groups[1].helix_ids == []


@pytest.mark.parametrize("direction", list(m.Direction))
def test_repeated_endpoint_edits_use_current_native_terminal(direction):
    design = grouped(source(direction), [[("stap", 0)]])
    sign = outward(direction, "3p")
    result = parity(design, KINDS[0], [resize_entry(delta=3 * sign), resize_entry(delta=5 * sign)])
    assert refs(result) == [("stap", 0), ("stap", 1)]


@pytest.mark.parametrize("direction", list(m.Direction))
def test_whole_domain_shift_to_disjoint_addresses_retains_entity(direction):
    design = grouped(source(direction, scaffold=False), [[("stap", 0)], [("stap", 0)]], whole=True)
    result = parity(design, KINDS[1], [shift_entry(delta=30)])
    assert refs(result) == refs(result, 1) == [("stap", 0)]
    old, = selected_domains(design)
    moved, = selected_domains(result)
    assert (moved.start_bp, moved.end_bp) == (old.start_bp + 30, old.end_bp + 30)


@pytest.mark.parametrize("direction", list(m.Direction))
def test_shift_then_inline_split_follows_both_actual_children(direction):
    design = grouped(source(direction), [[("stap", 0)], [("stap", 0)]])
    result = parity(design, KINDS[1], [shift_entry(delta=10)])
    assert refs(result) == refs(result, 1) == [("stap", 0), ("stap", 1)]


def test_batch_shift_reuses_old_addresses_without_cross_assigning_ancestry():
    design = source(scaffold=False)
    first = design.find_strand("stap").domains[0]
    design = design.copy_with(strands=[m.Strand(id="stap", domains=[
        first, first.model_copy(update={"start_bp": 40, "end_bp": 51})])])
    design = grouped(design, [[("stap", 0)], [("stap", 1)], [("stap", 0)]])
    result = parity(design, KINDS[1], [shift_entry(index=1, delta=-26), shift_entry(index=0, delta=26)])
    assert refs(result) == refs(result, 2) == [("stap", 0)]
    assert refs(result, 1) == [("stap", 1)]
    assert [(d.start_bp, d.end_bp) for d in result.find_strand("stap").domains] == [(40, 51), (14, 25)]


@pytest.mark.parametrize("direction", list(m.Direction))
def test_joint_scaffold_and_staple_shift_uses_updated_coverage(direction):
    design = grouped(source(direction), [[("stap", 0)], [("scaf", 0)]])
    result = parity(design, KINDS[1], [shift_entry(delta=30), shift_entry(delta=30, sid="scaf")])
    assert refs(result) == [("stap", 0)] and refs(result, 1) == [("scaf", 0)]
    assert len(result.find_strand("stap").domains) == 1 and result.overhangs == []


@pytest.mark.parametrize("kind", KINDS)
def test_noop_keeps_selections_and_complete_native_output(kind):
    design = grouped(source(), [[("stap", 0)]], whole=True)
    entry = resize_entry(delta=0) if kind == KINDS[0] else shift_entry(delta=0)
    result = parity(design, kind, [entry])
    assert result.group_organization == design.group_organization


@pytest.mark.parametrize("failure", ["duplicate", "missing", "bad-ordinal", "negative", "overlap"])
def test_shift_refusal_preserves_source_and_does_not_fall_back(failure):
    design = source(scaffold=False)
    entries = [shift_entry(delta=2)]
    if failure == "duplicate":
        entries *= 2
    elif failure == "missing":
        entries = [shift_entry(sid="missing")]
    elif failure == "bad-ordinal":
        entries = [shift_entry(index=7)]
    elif failure == "negative":
        entries = [shift_entry(delta=-30)]
    else:
        domain = design.strands[0].domains[0].model_copy(update={"start_bp": 30, "end_bp": 40})
        design = design.copy_with(strands=[*design.strands, m.Strand(id="blocker", domains=[domain])])
        entries = [shift_entry(delta=10)]
    design = grouped(design, [[("stap", 0)]])
    original = design.model_dump(mode="json")
    with pytest.raises((CommandContractError, ValueError, KeyError)) as error:
        execute(KINDS[1], design, {"_proof_version": 1, "entries": entries})
    if isinstance(error.value, CommandContractError):
        assert error.value.code not in {"unsupported_group_lineage_command", "unsupported_group_organization_command"}
    assert design.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_calls_do_not_acquire_an_observer(monkeypatch, kind):
    design = source()
    builder = lattice.resize_strand_ends if kind == KINDS[0] else lattice.shift_domains

    def unchanged(source, entries, **kwargs):
        assert kwargs.get("lineage") is None
        return builder(source, entries)

    monkeypatch.setattr(lattice, "resize_strand_ends" if kind == KINDS[0] else "shift_domains", unchanged)
    entry = resize_entry(delta=1) if kind == KINDS[0] else shift_entry(delta=1)
    result = execute(kind, design, {"_proof_version": 1, "entries": [entry]})
    assert result.group_organization is None
