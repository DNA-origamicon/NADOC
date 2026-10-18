"""Isolated 1xT CPD seed investigation. Never modifies a design or production assets.

Run from repository root with uv run python -m scripts.investigate_cpd_1xt_starts.
Output coordinates are diagnostic only, in nm. Force-field runs are optional.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import resolve_base_keys
from backend.core.cpd_conversion import CORE_PATH, prepare_conversion
from backend.core.cpd_design import minimize_attachment_bonds
from backend.core.models import Design
from backend.core.photoproduct_chemistry import load_chemical_definition


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--design", type=Path, default=Path("workspace/2hb_1xT_CPD.nadoc")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    design = Design.from_json(args.design.read_text())
    (args.output / "input_snapshot.json").write_bytes(args.design.read_bytes())
    if design.photoproduct_junctions:
        raise ValueError("Investigation requires an unconverted design")
    keys = [f"__xb__:{x.id}:0" for x in design.crossovers if x.extra_bases == "T"]
    if len(keys) != 2:
        raise ValueError("Expected precisely two single-T crossover inserts")
    model = build_atomistic_model(design)
    endpoints, errors = resolve_base_keys(design, keys, atomistic_model=model)
    assert not errors
    write(
        args.output / "provenance.json",
        {
            "input": str(args.design.resolve()),
            "input_sha256": hashlib.sha256(args.design.read_bytes()).hexdigest(),
            "cores_sha256": hashlib.sha256(CORE_PATH.read_bytes()).hexdigest(),
            "keys": keys,
            "qualification": "isolated diagnostic; no production admission",
            "moving": "two complete inserted nucleotides; all other atoms fixed",
        },
    )
    for core in json.loads(CORE_PATH.read_text())["products"]:
        stereo = core["stereochemistry"]
        folder = args.output / core["id"]
        folder.mkdir()
        definition = load_chemical_definition("TT-CPD", stereo)
        template = {k: np.array(v) for k, v in core["coordinates"].items()}
        _, preview = prepare_conversion(design, keys, stereo)
        current = {
            f"{i}:{n}": np.array(v)
            for i, e in enumerate(endpoints, 1)
            for n, v in e.atom_positions_nm.items()
        }
        for i, e in enumerate(endpoints, 1):
            for address, xyz in zip(preview["atom_keys"], preview["positions"]):
                if address.startswith(e.key + ":"):
                    current[f"{i}:{address[len(e.key) + 1 :]}"] = np.array(xyz)
        links = [
            (b["atom_1"], b["atom_2"]) for b in definition["graph_delta"]["bonds_added"]
        ]
        placed, report = minimize_attachment_bonds(
            model, endpoints, current, template=template, crosslinks=links
        )
        write(folder / "repair_report.json", report)
        write(folder / "coordinates.json", {k: v.tolist() for k, v in placed.items()})
        # Keep the actual same-frame context and atom mapping for review/replay.
        candidate = copy.deepcopy(preview)
        for j, address in enumerate(preview["atom_keys"]):
            for i, e in enumerate(endpoints, 1):
                if address.startswith(e.key + ":"):
                    candidate["positions"][j] = placed[
                        f"{i}:{address[len(e.key) + 1 :]}"
                    ].tolist()
        write(folder / "current_preview.json", preview)
        write(folder / "candidate_preview.json", candidate)
        print(
            stereo,
            json.dumps(
                {
                    k: report[k]
                    for k in ["after_nm", "remaining_strain", "clashes_after"]
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
