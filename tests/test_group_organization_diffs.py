"""Recorded Fine Routing state must retain final organizational membership.

These are recovery-format tests, not a topology-lineage implementation. Native
nick/ligation supplies real topology; explicit expected membership supplies the
already-reconciled metadata that the recorder must preserve.
"""

import json

import pytest

from backend.core import models as m
from backend.core.design_diff import (
    _gzip_b64,
    _ungzip_b64,
    apply_child_diff_forward,
    apply_child_diff_run,
    encode_child_diff,
    is_diff_child,
)
from backend.core.design_geometry import _geometry_for_design
from backend.core.feature_evaluation import evaluate_child_prefix
from backend.core.lattice import _ligate, make_nick
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup


def source():
    return m.Design(id="organization-diff", helices=[m.Helix(id="h", length_bp=12,
        axis_start=m.Vec3(x=0, y=0, z=0), axis_end=m.Vec3(x=0, y=0, z=3.74))],
        strands=[m.Strand(id="chain", domains=[m.Domain(helix_id="h", start_bp=0,
            end_bp=11, direction=m.Direction.FORWARD)])],
        cluster_transforms=[m.ClusterRigidTransform(id="placement", helix_ids=["h"],
            translation=[2, 0, 0])], group_organization=organization())


def organization(name="Selected", members=("chain",)):
    return GroupOrganization(groups=[PartGroup(id="group", name=name,
        helix_ids=["h"] if members else [], domain_ids=[
            GroupDomainRef(strand_id=identity, domain_index=0) for identity in members])])


def _payload(value):
    return value.model_dump(mode="json") if value is not None else None


def recorded(pre, post, *, encode=True):
    added, removed, modified, size = encode_child_diff(pre, post)
    if not encode:
        # Independently construct the proposed envelope so application tests do
        # not pass or fail solely because the producer omitted the new field.
        body = json.loads(_ungzip_b64(modified)) if modified else {"pre": {}, "post": {}}
        body["pre"]["group_organization"] = _payload(pre.group_organization)
        body["post"]["group_organization"] = _payload(post.group_organization)
        text = json.dumps(body)
        modified = _gzip_b64(text.encode())
        size = sum(len(_ungzip_b64(value)) for value in (added, removed) if value) + len(text)
    return m.MinorMutationLogEntry(op_subtype="nick", label="Recorded native edit",
        diff_added_b64=added, diff_removed_b64=removed, diff_modified_b64=modified,
        diff_size_bytes=size)


def apply(anchor, child, *, defensive=False):
    return apply_child_diff_forward(anchor, child.diff_added_b64, child.diff_removed_b64,
        child.diff_modified_b64, defensive=defensive)


def _no_replay(*args, **kwargs):
    raise AssertionError("A recorded metadata delta must not fall back to native replay")


@pytest.mark.parametrize("before,after", [
    (None, organization()), (organization(), None),
    (organization(), GroupOrganization(groups=[])),
    (organization(), organization("Changed")),
], ids=["activate", "deactivate", "empty", "replace"])
def test_encoder_records_complete_optional_replacement_and_actual_recovery_size(before, after):
    pre = source().copy_with(group_organization=before)
    post = pre.copy_with(group_organization=after)
    child = recorded(pre, post)
    assert is_diff_child(child)
    body = json.loads(_ungzip_b64(child.diff_modified_b64))
    assert body == {"pre": {"group_organization": _payload(before)},
                    "post": {"group_organization": _payload(after)}}
    assert child.diff_size_bytes == len(_ungzip_b64(child.diff_modified_b64))
    recovered, warnings = apply(pre, child)
    assert warnings == []
    assert recovered.model_dump(mode="json") == post.model_dump(mode="json")


def test_unchanged_organization_is_absent_from_legacy_compatible_envelope():
    pre = source()
    post = pre.copy_with(strands=[pre.strands[0].model_copy(update={"color": "#123456"})])
    active = encode_child_diff(pre, post)
    legacy = encode_child_diff(pre.copy_with(group_organization=None),
        post.copy_with(group_organization=None))
    assert active == legacy
    assert "group_organization" not in json.loads(_ungzip_b64(active[2]))["post"]
    assert encode_child_diff(pre, pre) == ("", "", "", 0)
    child = recorded(pre.copy_with(group_organization=None), post.copy_with(group_organization=None))
    recovered, warnings = apply(pre, child)
    assert warnings == [] and recovered.group_organization == pre.group_organization
    assert recovered.strands == post.strands


@pytest.mark.parametrize("defensive", [False, True])
def test_replacement_restores_metadata_without_touching_native_placement_or_aliasing_source(defensive):
    pre = source()
    original = pre.model_dump(mode="json")
    post = pre.copy_with(group_organization=organization("Replacement", ()))
    recovered, warnings = apply(pre, recorded(pre, post, encode=False), defensive=defensive)
    assert warnings == []
    assert recovered.model_dump(mode="json") == post.model_dump(mode="json")
    assert _geometry_for_design(recovered) == _geometry_for_design(pre)
    assert recovered.cluster_transforms == pre.cluster_transforms
    recovered.group_organization.groups[0].name = "Private recovered value"
    assert pre.model_dump(mode="json") == original
    assert post.group_organization.groups[0].name == "Replacement"


def native_history():
    pre = source()
    nicked = make_nick(pre, "h", 5, m.Direction.FORWARD)
    nicked = nicked.copy_with(group_organization=organization(
        members=tuple(strand.id for strand in nicked.strands)))
    ordered = sorted(nicked.strands, key=lambda strand: strand.domains[0].start_bp)
    joined = _ligate(nicked, *ordered)
    joined = joined.copy_with(group_organization=organization(members=(joined.strands[0].id,)))
    states = [pre, nicked, joined]
    # The optimized child composer starts at eight children. Ten real recorded
    # style changes exercise that path without padding top-level history.
    for index in range(10):
        states.append(states[-1].copy_with(group_organization=organization(
            name=f"Native descendants {index}", members=(joined.strands[0].id,))))
    return states


@pytest.mark.parametrize("optimized", [False, True])
def test_every_native_split_merge_and_metadata_prefix_reconstructs_exact_final_wrapper(optimized):
    states = native_history()
    original = states[0].model_dump(mode="json")
    children = [recorded(pre, post, encode=False) for pre, post in zip(states, states[1:])]
    for stop, expected in enumerate(states[1:], 1):
        recovered = evaluate_child_prefix(states[0], children[:stop], _no_replay, optimized=optimized)
        assert recovered.model_dump(mode="json") == expected.model_dump(mode="json")
        assert _geometry_for_design(recovered) == _geometry_for_design(expected)
        assert m.Design.model_validate_json(recovered.model_dump_json()) == recovered
    assert states[0].model_dump(mode="json") == original


@pytest.mark.parametrize("mode", ["forward", "defensive", "optimized"])
@pytest.mark.parametrize("baseline", [None, GroupOrganization(groups=[]), organization("Different")],
    ids=["missing", "empty", "changed"])
def test_missing_or_changed_recorded_baseline_refuses_instead_of_overwriting_group_state(mode, baseline):
    pre = source()
    post = pre.copy_with(group_organization=organization("Later"))
    child = recorded(pre, post, encode=False)
    anchor = pre.copy_with(group_organization=baseline)
    original = anchor.model_dump(mode="json")
    with pytest.raises(ValueError, match="[Gg]roup|organiz|baseline"):
        if mode == "optimized":
            apply_child_diff_run(anchor, [child, recorded(post, pre, encode=False)])
        else:
            apply(anchor, child, defensive=mode == "defensive")
    assert anchor.model_dump(mode="json") == original


@pytest.mark.parametrize("malformation", ["pre-absent", "post-absent", "bad-version",
    "bool-version", "unknown-field", "negative-ordinal", "too-many-groups"])
@pytest.mark.parametrize("optimized", [False, True])
def test_malformed_replacement_is_never_silently_ignored(malformation, optimized):
    pre, post = source(), source().copy_with(group_organization=organization("Changed"))
    child = recorded(pre, post, encode=False)
    body = json.loads(_ungzip_b64(child.diff_modified_b64))
    if malformation.endswith("-absent"):
        body[malformation.split("-")[0]].pop("group_organization")
    else:
        value = body["post"]["group_organization"]
        if malformation == "bad-version":
            value["version"] = 2
        elif malformation == "bool-version":
            value["version"] = True
        elif malformation == "unknown-field":
            value["groups"][0]["translation"] = [1, 2, 3]
        elif malformation == "negative-ordinal":
            value["groups"][0]["domain_ids"][0]["domain_index"] = -1
        else:
            value["groups"] *= 2001
    child.diff_modified_b64 = _gzip_b64(json.dumps(body).encode())
    original = pre.model_dump(mode="json")
    with pytest.raises(ValueError):
        if optimized:
            apply_child_diff_run(pre, [child, recorded(post, pre, encode=False)])
        else:
            apply(pre, child)
    assert pre.model_dump(mode="json") == original


def test_encoder_checks_repeated_metadata_expansion_before_dump(monkeypatch):
    group = PartGroup(id="repeated", name="x" * 512)
    oversized = GroupOrganization(groups=[group] * 1024)
    pre = source()
    post = pre.copy_with(group_organization=oversized)

    def unexpected_dump(*args, **kwargs):
        raise AssertionError("Unadmitted organization must not be serialized")

    monkeypatch.setattr(GroupOrganization, "model_dump", unexpected_dump)
    with pytest.raises(ValueError, match="budget|limit|bound"):
        encode_child_diff(pre, post)


@pytest.mark.parametrize("optimized", [False, True])
def test_decoded_replacement_obeys_cumulative_metadata_budget(optimized):
    pre = source()
    post = pre.copy_with(group_organization=organization("Changed"))
    child = recorded(pre, post, encode=False)
    body = json.loads(_ungzip_b64(child.diff_modified_b64))
    repeated = PartGroup(id="repeated", name="x" * 512).model_dump(mode="json")
    body["post"]["group_organization"]["groups"] = [repeated] * 1024
    child.diff_modified_b64 = _gzip_b64(json.dumps(body).encode())
    with pytest.raises(ValueError, match="budget|limit|bound"):
        if optimized:
            apply_child_diff_run(pre, [child, recorded(post, pre, encode=False)])
        else:
            apply(pre, child)
