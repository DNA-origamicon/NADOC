"""Reproduce the pinned experimental CPD simulation assets from the reviewed local packages."""

import hashlib, json
from pathlib import Path


def main():
    root = Path(
        ".development-artifacts/cpd-cis-anti-i-bounded-sensitivity-v1/minimum-viable-candidates-v4"
    )
    out = Path("backend/data/forcefield/mvp_cpds")
    out.mkdir(exist_ok=True)
    products = []
    for source in sorted(root.glob("*/manifest.json")):
        m = json.loads(source.read_text())
        pid = m["product"]
        dest = out / pid
        dest.mkdir(exist_ok=True)
        for f in m["files"]:
            raw = (source.parent / f["file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == f["sha256"]
            (dest / f["file"]).write_bytes(raw)
        definition = json.loads(
            (source.parent / "chemical_definition.json").read_text()
        )
        spec = {
            "schema": "nadoc.photoproduct-topology-audit-spec.v1",
            "product_id": pid,
            "expected_product_atoms": [],
            "crosslinks": [],
            "impropers_added": [],
            "impropers_removed": [],
        }
        ref = lambda n: n[0] + ":" + n[1:]
        for line in (dest / "patch.rtf").read_text().splitlines():
            x = line.split("!")[0].split()
            if not x:
                continue
            if x[0] == "ATOM":
                spec["expected_product_atoms"].append(
                    {"atom": ref(x[1]), "type": x[2], "charge": float(x[3])}
                )
            if x[0] == "BOND":
                spec["crosslinks"].append([ref(n) for n in x[1:]])
            if x[0] == "IMPR":
                spec["impropers_added"].append([ref(n) for n in x[1:]])
            if x[:2] == ["DELETE", "IMPR"]:
                spec["impropers_removed"].append([ref(n) for n in x[2:]])
        (dest / "topology_audit.json").write_text(json.dumps(spec, indent=2) + "\n")
        (dest / "qualification.json").write_text(source.read_text())
        (dest / "chemical_definition.json").write_text(
            json.dumps(definition, indent=2) + "\n"
        )
        assets = {}
        for kind, name in [
            ("topology", "patch.rtf"),
            ("parameters", "overlay.prm"),
            ("topology_audit_spec", "topology_audit.json"),
            ("qualification", "qualification.json"),
            ("chemical_definition", "chemical_definition.json"),
            ("transfer_records", "transfer_records.json"),
        ]:
            assets[kind] = {
                "path": str((dest / name).relative_to(out.parent)),
                "sha256": hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            }
        assets["topology"]["patch_name"] = "XCPD"
        products.append(
            {
                "id": pid,
                "product": "TT-CPD",
                "stereochemistry": definition["stereochemistry"],
                "assets": assets,
            }
        )
    parent = next(
        p for p in m["required_parent_sha256"] if p.endswith("par_all36_cgenff.prm")
    )
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.experimental-cpd-simulation.v1",
                "qualification": "provisional numerical MVP; not physically validated or generally released",
                "products": products,
                "cgenff_parent": {
                    "source_path": parent,
                    "sha256": m["required_parent_sha256"][parent],
                },
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
