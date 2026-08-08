"""Direct input→output unit tests for the pure assembly-validation service
(`backend/core/assembly_validate.py`), extracted from assembly.py's
`_validate_assembly` (carve-up Refactor #8, service push, B=0).

No TestClient — these pin the validation rules directly.
"""

from backend.core.assembly_validate import validate_assembly_report
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    Design,
    PartInstance,
    PartSourceFile,
    PartSourceInline,
)


def _inline_instance(inst_id: str, name: str = "Part") -> PartInstance:
    return PartInstance(id=inst_id, name=name, source=PartSourceInline(design=Design()))


def test_empty_assembly_passes():
    rep = validate_assembly_report(Assembly())
    assert rep["passed"] is True
    assert isinstance(rep["results"], list)


def test_valid_assembly_with_instances_and_joint_passes():
    a = _inline_instance("a")
    b = _inline_instance("b")
    joint = AssemblyJoint(name="j", instance_b_id="b")
    asm = Assembly(instances=[a, b], joints=[joint])
    rep = validate_assembly_report(asm)
    assert rep["passed"] is True
    # All distinct checks reported once (dedup of ok=True duplicates).
    checks = [r["check"] for r in rep["results"]]
    assert len(checks) == len(set(checks))


def test_duplicate_instance_ids_fail():
    asm = Assembly(instances=[_inline_instance("dup"), _inline_instance("dup")])
    rep = validate_assembly_report(asm)
    assert rep["passed"] is False
    fails = [r for r in rep["results"] if not r["ok"]]
    assert any(r["check"] == "instance_ids_unique" for r in fails)


def test_joint_referencing_missing_instance_fails():
    asm = Assembly(
        instances=[_inline_instance("a")],
        joints=[AssemblyJoint(name="bad", instance_b_id="ghost")],
    )
    rep = validate_assembly_report(asm)
    assert rep["passed"] is False
    bad = [
        r
        for r in rep["results"]
        if r["check"] == "joint_instance_refs_valid" and not r["ok"]
    ]
    assert bad and "ghost" in bad[0]["message"]


def test_joint_below_min_limit_fails():
    asm = Assembly(
        instances=[_inline_instance("b")],
        joints=[
            AssemblyJoint(
                name="j", instance_b_id="b", current_value=-5.0, min_limit=0.0
            )
        ],
    )
    rep = validate_assembly_report(asm)
    assert rep["passed"] is False
    bad = [
        r
        for r in rep["results"]
        if r["check"] == "joint_limits_not_exceeded" and not r["ok"]
    ]
    assert bad and "min_limit" in bad[0]["message"]


def test_joint_above_max_limit_fails():
    asm = Assembly(
        instances=[_inline_instance("b")],
        joints=[
            AssemblyJoint(
                name="j", instance_b_id="b", current_value=10.0, max_limit=1.0
            )
        ],
    )
    rep = validate_assembly_report(asm)
    assert rep["passed"] is False
    bad = [
        r
        for r in rep["results"]
        if r["check"] == "joint_limits_not_exceeded" and not r["ok"]
    ]
    assert bad and "max_limit" in bad[0]["message"]


def test_missing_file_source_fails():
    asm = Assembly(
        instances=[
            PartInstance(
                id="f",
                name="missing",
                source=PartSourceFile(path="does/not/exist.nadoc"),
            ),
        ],
    )
    rep = validate_assembly_report(asm)
    assert rep["passed"] is False
    bad = [
        r for r in rep["results"] if r["check"] == "file_sources_exist" and not r["ok"]
    ]
    assert bad and "not found" in bad[0]["message"]


def test_ok_checks_are_deduplicated_across_instances():
    # Two valid inline instances → file_sources_exist would appear twice; dedup collapses to one ok row.
    asm = Assembly(instances=[_inline_instance("a"), _inline_instance("b")])
    rep = validate_assembly_report(asm)
    fs = [r for r in rep["results"] if r["check"] == "file_sources_exist"]
    assert len(fs) == 1 and fs[0]["ok"] is True
