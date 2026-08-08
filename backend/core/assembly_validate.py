"""Pure assembly validation — HTTP-free correctness checks on an Assembly.

Lives in `backend/core` (never imports `backend/api`): the dependency arrow is
api → core. The api route handler (`GET /assembly/validate`) shrinks to
parse → delegate → respond and calls `validate_assembly_report` here.

One reason to change: the set of correctness checks run against an assembly
(file sources, joint refs, joint limits, ID uniqueness, flattened-ID uniqueness).
"""

from __future__ import annotations

from backend.core.models import Assembly


def validate_assembly_report(assembly: Assembly) -> dict:
    """
    Run all validation checks on an assembly and return a structured report.
    """
    from backend.core.assembly_flatten import flatten_assembly, _load_design

    results = []

    # 1. File sources exist
    for inst in assembly.instances:
        if hasattr(inst.source, "path"):
            try:
                _load_design(inst.source)
                results.append({"check": "file_sources_exist", "ok": True})
            except FileNotFoundError:
                results.append(
                    {
                        "check": "file_sources_exist",
                        "ok": False,
                        "message": f"{inst.source.path!r} not found",
                    }
                )
        else:
            results.append({"check": "file_sources_exist", "ok": True})

    # 2. Joint instance refs valid
    inst_ids = {i.id for i in assembly.instances}
    for joint in assembly.joints:
        ok = joint.instance_b_id in inst_ids
        entry: dict = {"check": "joint_instance_refs_valid", "ok": ok}
        if not ok:
            entry["message"] = (
                f"Joint {joint.name!r}: instance_b_id {joint.instance_b_id!r} not found"
            )
        results.append(entry)

    # 3. Joint limits not exceeded
    for joint in assembly.joints:
        exceeded = False
        msg = ""
        if joint.min_limit is not None and joint.current_value < joint.min_limit:
            exceeded = True
            msg = f"Joint {joint.name!r}: current_value {joint.current_value} < min_limit {joint.min_limit}"
        elif joint.max_limit is not None and joint.current_value > joint.max_limit:
            exceeded = True
            msg = f"Joint {joint.name!r}: current_value {joint.current_value} > max_limit {joint.max_limit}"
        entry = {"check": "joint_limits_not_exceeded", "ok": not exceeded}
        if exceeded:
            entry["message"] = msg
        results.append(entry)

    # 4. Instance IDs unique
    all_inst_ids = [i.id for i in assembly.instances]
    ids_unique = len(all_inst_ids) == len(set(all_inst_ids))
    results.append({"check": "instance_ids_unique", "ok": ids_unique})

    # 5. Flattened IDs unique
    try:
        flatten_assembly(assembly)
        results.append({"check": "flattened_ids_unique", "ok": True})
    except ValueError as exc:
        results.append(
            {"check": "flattened_ids_unique", "ok": False, "message": str(exc)}
        )
    except FileNotFoundError:
        # Missing file already caught above
        results.append({"check": "flattened_ids_unique", "ok": True})

    # Deduplicate results with the same check name + ok=True (collapse multiple instances)
    seen_ok: dict[str, bool] = {}
    deduped = []
    for r in results:
        key = r["check"]
        if not r["ok"]:
            deduped.append(r)
            seen_ok[key] = False
        elif key not in seen_ok:
            deduped.append(r)
            seen_ok[key] = True

    passed = all(r["ok"] for r in deduped)
    return {"passed": passed, "results": deduped}
