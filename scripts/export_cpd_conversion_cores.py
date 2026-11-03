"""Extract portable base-only authoring cores from the four archived MVP starts.

No force-field assets or simulation qualifications are promoted by this export.
"""
import hashlib
import json
from pathlib import Path

from backend.core.photoproduct_chemistry import audit_product_chirality, load_chemical_definition


def export(root, output):
    products = []
    for stereo in ("cis-syn", "trans-syn-I", "trans-syn-II", "cis-anti-I"):
        definition = load_chemical_definition("TT-CPD", stereo)
        folder = "cgenff-cis-syn-geometry-v1" if stereo == "cis-syn" else "cgenff-dna-geometry-v1"
        start = "start-1" if stereo == "cis-anti-I" else "repaired-start-1"
        source = root / folder / definition["id"] / start / "seed.pdb"
        graph = source.parent.parent / "graph.json"
        endpoints = json.loads(graph.read_text())["endpoints"]
        coordinates = {}
        for line in source.read_text().splitlines():
            if not line.startswith("ATOM") or int(line[22:26]) not in endpoints:
                continue
            name = line[12:16].strip()
            if name == "C5M":
                name = "C7"
            coordinates[f"{endpoints.index(int(line[22:26])) + 1}:{name}"] = [float(line[i:i+8]) * .1 for i in (30, 38, 46)]
        assert audit_product_chirality(definition, coordinates)["passed"], stereo
        products.append({"id": definition["id"], "stereochemistry": stereo,
                         "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                         "graph_sha256": hashlib.sha256(graph.read_bytes()).hexdigest(), "source_residues": endpoints,
                         "coordinates": coordinates})
    output.write_text(json.dumps({"schema": "nadoc.cpd-manual-cores.v1", "units": "nm",
        "qualification": "MVP starting conformers for manual visual construction; fixed-backbone fits are not simulation qualified.",
        "products": products}, indent=2) + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.archive_root, args.output)
