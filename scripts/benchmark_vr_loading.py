"""Paired VR export benchmark with exact wire-output parity; no workspace writes.

Run: uv run python -m scripts.benchmark_vr_loading --baseline <revision>
Synthetic geometry measures serialization only, not molecular construction or FPS.
"""

import argparse
import ast
import hashlib
import json
import statistics
import subprocess
import time
from types import SimpleNamespace as NS

from backend.api import routes_vr as vr


def fixture(residues):
    nucleotides = [
        dict(
            strand_id="s1", domain_index=0, helix_id="h1", bp_index=i,
            direction="FORWARD", is_five_prime=i == 0,
            backbone_position=[1, 2, i * .334],
            base_position=[1.2, 2, i * .334],
            base_normal=[1, 0, 0], axis_tangent=[0, 0, 1],
        )
        for i in range(residues)
    ]
    atoms = [
        NS(name=f"C{k}", x=1 + k * .01, y=2., z=i * .334,
           strand_id="s1", helix_id="h1", bp_index=i, direction="FORWARD",
           residue="DA", element="C")
        for i in range(residues) for k in range(20)
    ]
    design = NS(
        strands=[NS(id="s1", is_scaffold=True, color=None, sequence="A" * residues)],
        cluster_transforms=[],
    )
    model = NS(atoms=atoms, bonds=[(i, i + 1) for i in range(len(atoms) - 1)])
    return design, nucleotides, model


def baseline_function(revision):
    path = "backend/api/routes_vr.py"
    source = subprocess.check_output(["git", "show", f"{revision}:{path}"], text=True)
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "_serialize_scene")
    scope = vars(vr).copy()
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), scope)
    return scope[node.name]


def measure(function, values, representation):
    design, nucleotides, model = values
    digest = hashlib.sha256()

    def write(line):
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")

    start = time.perf_counter()
    manifest = function(design, nucleotides, [], representation=representation,
                        atomistic_model=model, line_writer=write)
    return time.perf_counter() - start, digest.hexdigest(), manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--residues", nargs="+", type=int, default=[300, 1500])
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    before = baseline_function(args.baseline)
    for residues in args.residues:
        values = fixture(residues)
        for representation in ("full", "ballstick"):
            reference = measure(before, values, representation)
            candidate = measure(vr._serialize_scene, values, representation)
            assert reference[1:] == candidate[1:]
            times = [[], []]
            for repeat in range(args.repeats):
                for index in ([0, 1] if repeat % 2 == 0 else [1, 0]):
                    result = measure((before, vr._serialize_scene)[index], values,
                                     representation)
                    assert result[1:] == reference[1:]
                    times[index].append(result[0])
            old, new = map(statistics.median, times)
            print(json.dumps(dict(
                atoms=len(values[2].atoms), initial_representation=representation,
                before_s=old, after_s=new, speedup=old / new,
                exact_wire_and_manifest=True, sha256=reference[1],
                baseline=args.baseline, repeats=args.repeats,
            )), flush=True)


if __name__ == "__main__":
    main()
