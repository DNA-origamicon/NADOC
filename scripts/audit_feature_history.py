"""Static feature-history inventory; does not import NADOC or open user designs.

Run from the checkout: python3 scripts/audit_feature_history.py > inventory.json
Direct calls and literal dispatch branches are evidence, not runtime reachability
or regeneration certification. Dynamic dispatch and external callers need review.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SINKS = {
    "mutate_with_feature_log", "mutate_with_minor_log",
    "_apply_assembly_mutation_with_feature_log", "_apply_part_mutation_with_feature_log",
    "set_design", "set_design_silent", "set_design_silent_reconciled",
    "set_design_branch", "load_design", "restore_doc_design", "snapshot",
    "set_assembly", "set_assembly_silent", "load_assembly", "restore_doc_assembly",
    "_replace_instance_design", "SnapshotLogEntry", "MinorMutationLogEntry",
    "DeformationLogEntry", "ClusterOpLogEntry", "ClusterCreateLogEntry",
    "OverhangRotationLogEntry", "RoutingClusterLogEntry",
}


def name(node):
    return ast.unparse(node)


def constants(node):
    return sorted({n.value for n in ast.walk(node)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)})


def body_nodes(node):
    """Walk a function, excluding bodies of nested function/class definitions."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from body_nodes(child)


def inventory():
    result = {"scope": "Static Python AST inventory of backend; no runtime certification",
              "declared": {}, "dispatch": {}, "model_fields": {}, "calls": [],
              "routes": [], "direct_state_assignments": [], "capability_constants": {},
              "replay_registries": {}}
    for path in sorted((ROOT / "backend").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(), filename=rel)
        sets = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            else:
                continue
            if target in {"PART_SNAPSHOT_COMMANDS", "PART_MINOR_COMMANDS"} and isinstance(value, ast.Call) and value.args and isinstance(value.args[0], ast.Dict):
                result["replay_registries"][target] = {
                    "path": rel, "line": node.lineno,
                    "kinds": [k.value for k in value.args[0].keys if isinstance(k, ast.Constant)],
                }
            if isinstance(value, (ast.Set, ast.Tuple, ast.List)):
                sets[target] = constants(value)
            elif isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr) and isinstance(value.left, ast.Name) and value.left.id in sets:
                sets[target] = sorted(set(sets[value.left.id]) | set(constants(value.right)))
            if target in {"_EDITABLE_OP_KINDS", "_REPLAYABLE_OP_KINDS", "_DIFF_FIELDS", "_ID_COLLECTIONS"} and target in sets:
                result["capability_constants"][rel + ":" + target] = {"line": node.lineno, "values": sets[target]}
        if rel == "backend/core/models.py":
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in {"SnapshotOpKind", "MinorOpSubtype"}:
                            result["declared"][target.id] = constants(node.value)
                if isinstance(node, ast.ClassDef) and node.name in {"Design", "Assembly"}:
                    result["model_fields"][node.name] = [
                        {"name": n.target.id, "annotation": name(n.annotation), "line": n.lineno}
                        for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = list(body_nodes(node))
            site = {"path": rel, "function": node.name, "line": node.lineno}
            calls = [n for n in nodes if isinstance(n, ast.Call)]
            sink_calls = [n for n in calls if name(n.func).split(".")[-1] in SINKS]
            for call in sink_calls:
                entry = {**site, "line": call.lineno, "call": name(call.func)}
                kind = next((k.value for k in call.keywords if k.arg in {"op_kind", "op_subtype"}), None)
                if kind is None and name(call.func).split(".")[-1] in {"mutate_with_feature_log", "mutate_with_minor_log"} and call.args:
                    kind = call.args[0]
                if kind is not None:
                    entry["kind_expression"] = name(kind)
                    entry["literal_kind"] = kind.value if isinstance(kind, ast.Constant) and isinstance(kind.value, str) else None
                result["calls"].append(entry)
            decorators = [name(d) for d in node.decorator_list
                          if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                          and d.func.attr in {"get", "post", "put", "patch", "delete", "websocket"}]
            if decorators:
                result["routes"].append({**site, "decorators": decorators,
                    "direct_sinks": sorted({name(c.func) for c in sink_calls}),
                    "calls": sorted({name(c.func) for c in calls})})
            for n in nodes:
                if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for target in targets:
                        if isinstance(target, ast.Attribute) and target.attr in {"design", "assembly", "feature_log"}:
                            result["direct_state_assignments"].append({**site, "line": n.lineno, "target": name(target)})
            if node.name in {"_edit_dispatch_run", "_replay_minor_op", "_replay_assembly_op"}:
                branches = set()
                for n in nodes:
                    if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id in {"op_kind", "op_subtype"}:
                        for comparator in n.comparators:
                            branches.update(constants(comparator))
                result["dispatch"][node.name] = {**site, "literal_branches": sorted(branches)}
    result["counts"] = {key: len(result[key]) for key in ("calls", "routes", "direct_state_assignments")}
    return result


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2, sort_keys=True))
