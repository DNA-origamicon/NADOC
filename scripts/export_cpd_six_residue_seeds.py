"""Package the reviewed 1xT six-residue candidates as portable authoring seeds."""

import hashlib
import json
from pathlib import Path


def export(root, output):
    products = []
    for source in sorted(root.glob("tt-*/local_seed.json")):
        seed = json.loads(source.read_text())
        metrics = seed["metrics"]
        if not (
            metrics["chirality_passed"]
            and metrics["engine_passed"]
            and not metrics["heavy_contacts_under_2A"]
            and not metrics["cpd_ring_piercings"]
        ):
            raise ValueError(f"Unqualified seed: {source}")
        products.append(
            {
                "stereochemistry": seed["stereochemistry"],
                "atoms": seed["atoms"],
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "metrics": metrics,
            }
        )
    if len(products) != 4:
        raise ValueError("Expected four reviewed isomers")
    output.write_text(
        json.dumps(
            {
                "schema": "nadoc.cpd-six-residue-seeds.v1",
                "units": "nm",
                "qualification": "Locally minimized 1xT starting geometry; provisional parameters, vacuum; not simulation qualified.",
                "products": products,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    export(a.root, a.output)
