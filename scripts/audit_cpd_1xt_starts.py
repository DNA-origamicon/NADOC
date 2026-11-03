"""Same-frame visual and numeric comparison of the isolated 1xT investigation."""

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from scipy.spatial.distance import cdist
from backend.core.atomistic import build_atomistic_model, VDW_RADIUS
from backend.core.base_keys import atom_base_key
from backend.core.cpd_conversion import CORE_PATH
from backend.core.cpd_product import (
    _segment_intersects_triangle,
    _ordered_product_ring_keys,
)
from backend.core.models import Design
from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.core.photoproduct_psf_audit import parse_psf_atoms, parse_psf_index_section
from backend.parameterization.photoproduct_candidate_context import (
    _pdb_coordinates,
    _namd_binary_coordinates,
)
from scripts.investigate_cpd_1xt_starts import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root
    provenance = json.loads((root / "provenance.json").read_text())
    keys = provenance["keys"]
    snapshot = root / "input_snapshot.json"
    assert (
        hashlib.sha256(snapshot.read_bytes()).hexdigest() == provenance["input_sha256"]
    )
    design = Design.from_json(snapshot.read_text())
    model = build_atomistic_model(design)
    atoms_by_address = {f"{atom_base_key(a)}:{a.name}": a for a in model.atoms}
    summary = {}
    for core in json.loads(CORE_PATH.read_text())["products"]:
        folder = root / core["id"]
        definition = load_chemical_definition("TT-CPD", core["stereochemistry"])
        stages = [
            json.loads((folder / "current_preview.json").read_text()),
            json.loads((folder / "candidate_preview.json").read_text()),
        ]
        numeric = {}
        for tag in [
            "namd",
            "namd-10000",
            "namd-neighbor-backbones-2000",
            "namd-neighbor-backbones",
        ]:
            out = folder / tag
            psf = (out / "context.psf").read_text()
            atoms = parse_psf_atoms(psf)
            xyz = _namd_binary_coordinates(out / "minimized.coor", len(atoms))
            initial = _pdb_coordinates(out / "context.pdb")
            lookup = {(a.segid, a.resid, a.name): i for i, a in enumerate(atoms)}
            # Segment ordering follows _write_segment_pdbs. Read chain->segid from PDB.
            segs = {
                line[21]: line[72:76].strip()
                for line in (out / "context.pdb").read_text().splitlines()
                if line.startswith("ATOM")
            }

            def index(address):
                a = atoms_by_address[address]
                return lookup[
                    (segs[a.chain_id], str(a.seq_num), charmm_atom_name(a.name))
                ]

            ends = []
            for key in keys:
                a = next(a for a in model.atoms if atom_base_key(a) == key)
                ends.append((segs[a.chain_id], str(a.seq_num)))
            endpoint = np.array([(a.segid, a.resid) in ends for a in atoms])
            heavy = np.array([a.mass > 2 for a in atoms])
            fixed = np.array(
                [
                    float(line[60:66]) > 0
                    for line in (out / "fixed.pdb").read_text().splitlines()
                    if line.startswith(("ATOM", "HETATM"))
                ]
            )
            mobile = ~fixed
            bonds = [
                (a - 1, b - 1) for a, b in parse_psf_index_section(psf, "!NBOND", 2)
            ]
            neighbors = [set() for _ in atoms]
            for a, b in bonds:
                neighbors[a].add(b)
                neighbors[b].add(a)
            selected = np.where(mobile & heavy)[0]
            other = np.where(heavy)[0]
            dist = cdist(xyz[selected], xyz[other])
            contacts = []
            min_ratio = float("inf")
            for ai, a in enumerate(selected):
                excluded = (
                    neighbors[a] | {v for n in neighbors[a] for v in neighbors[n]} | {a}
                )
                for bi in range(len(other)):
                    b = other[bi]
                    if b in excluded or (mobile[b] and b < a):
                        continue
                    radii = 10 * (
                        VDW_RADIUS.get(atoms[a].name[0], 0.16)
                        + VDW_RADIUS.get(atoms[b].name[0], 0.16)
                    )
                    min_ratio = min(min_ratio, float(dist[ai, bi] / radii))
                    if dist[ai, bi] >= 2.0:
                        continue
                    contacts.append(
                        {
                            "a": int(a),
                            "b": int(b),
                            "distance_A": float(dist[ai, bi]),
                            "identities": [
                                list(atoms[a].identity),
                                list(atoms[b].identity),
                            ],
                        }
                    )
            attachment = [
                float(np.linalg.norm(xyz[a] - xyz[b]))
                for a, b in bonds
                if endpoint[a] != endpoint[b]
            ]
            relevant = [
                (a, b)
                for a, b in bonds
                if (mobile[a] or mobile[b]) and heavy[a] and heavy[b]
            ]
            stretched = [
                {
                    "a": int(a),
                    "b": int(b),
                    "length_A": float(np.linalg.norm(xyz[a] - xyz[b])),
                }
                for a, b in relevant
                if np.linalg.norm(xyz[a] - xyz[b]) > 2
            ]

            def resolve(addr):
                e, n = addr.split(":")
                return lookup[(*ends[int(e) - 1], charmm_atom_name(n))]

            ring = xyz[[resolve(k) for k in _ordered_product_ring_keys(definition)]]
            triangles = [(ring[0], ring[1], ring[2]), (ring[0], ring[2], ring[3])]
            piercings = [
                (a, b)
                for a, b in bonds
                if not (endpoint[a] or endpoint[b])
                and any(
                    _segment_intersects_triangle(xyz[a], xyz[b], t) for t in triangles
                )
            ]
            report = json.loads((out / "report.json").read_text())
            numeric[tag] = {
                "minimum_mobile_heavy_vdw_ratio": min_ratio,
                "endpoint_backbone_attachments_A": attachment,
                "heavy_contacts_under_2A": contacts,
                "heavy_bonds_over_2A": stretched,
                "cpd_ring_piercings": piercings,
                "chirality_passed": report["chirality_after"]["passed"],
                "fixed_max_displacement_A": report["max_fixed_displacement_A"],
                "engine_passed": report["engine"]["passed"],
                "mobile_heavy_max_displacement_from_repaired_A": float(
                    np.linalg.norm(
                        xyz[mobile & heavy] - initial[mobile & heavy], axis=1
                    ).max()
                ),
            }
            preview = json.loads((folder / "current_preview.json").read_text())
            preview["positions"] = [
                (xyz[index(k)] / 10).tolist() for k in preview["atom_keys"]
            ]
            write(out / "preview.json", preview)
            if tag in ["namd-10000", "namd-neighbor-backbones"]:
                stages.append(preview)
            if tag == "namd-neighbor-backbones":
                # Canonical coordinates are anchored to unchanged flanking bases,
                # not to world axes or to the mobile sugars. Endpoint order matters.
                roles = {}
                anchors = []
                for e, (segid, resid) in enumerate(ends, 1):
                    roles[(segid, resid)] = f"endpoint-{e}"
                    for delta, side in [(-1, "5prime"), (1, "3prime")]:
                        identity = (segid, str(int(resid) + delta))
                        roles[identity] = f"flank-{e}-{side}"
                        n = "N9" if (*identity, "N9") in lookup else "N1"
                        anchors.append(lookup[(*identity, n)])
                anchor_xyz = xyz[anchors]
                origin = anchor_xyz.mean(axis=0)
                x = anchor_xyz[1] - anchor_xyz[0]
                x /= np.linalg.norm(x)
                y = anchor_xyz[2:].mean(axis=0) - anchor_xyz[:2].mean(axis=0)
                y -= x * (x @ y)
                y /= np.linalg.norm(y)
                axes = np.array([x, y, np.cross(x, y)]).T
                assert np.linalg.det(axes) > 0.999999
                local = (xyz - origin) @ axes / 10
                records = [
                    {
                        "role": roles[(a.segid, a.resid)],
                        "name": a.name,
                        "position_nm": local[i].tolist(),
                        "mobile": bool(mobile[i]),
                    }
                    for i, a in enumerate(atoms)
                    if (a.segid, a.resid) in roles
                ]
                seed = {
                    "schema": "nadoc.experimental-cpd-1xt-seed.v1",
                    "stereochemistry": core["stereochemistry"],
                    "qualification": "single-context vacuum candidate; not a universal template or production asset",
                    "endpoint_order": provenance["keys"],
                    "world_origin_A": origin.tolist(),
                    "local_axes_in_world": axes.tolist(),
                    "atoms": records,
                    "metrics": numeric[tag],
                    "source_sha256": {
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [
                            out / "context.psf",
                            out / "minimized.coor",
                            out / "minimize.namd",
                        ]
                    },
                }
                write(folder / "local_seed.json", seed)
        summary[core["stereochemistry"]] = numeric
        points = np.concatenate([np.array(s["positions"]) for s in stages]) * 10
        center = points.mean(0)
        span = np.ptp(points, axis=0).max() / 2 + 1
        fig = plt.figure(figsize=(12, 10))
        titles = [
            "Current base-only fit",
            "Rigid-core attachment repair",
            "10k steps: inserted residues mobile",
            "10k: + flanking sugars/backbone",
        ]
        for col, (s, title) in enumerate(zip(stages, titles), 1):
            ax = fig.add_subplot(2, 2, col, projection="3d")
            p = np.array(s["positions"]) * 10
            ax.add_collection3d(
                Line3DCollection(
                    [[p[a], p[b]] for a, b in s["bonds"]],
                    colors="#777777",
                    linewidths=0.8,
                )
            )
            ax.add_collection3d(
                Line3DCollection(
                    [[p[a], p[b]] for a, b in s["crosslinks"]],
                    colors="#d22aa0",
                    linewidths=3,
                )
            )
            colors = [
                "#db643b" if selected else "#4682b4" for selected in s["selected"]
            ]
            ax.scatter(*p.T, c=colors, s=10, depthshade=False)
            if col == 4:
                baseline = np.array(stages[0]["positions"]) * 10
                ax.add_collection3d(
                    Line3DCollection(
                        [
                            [a, b]
                            for a, b in zip(baseline, p)
                            if np.linalg.norm(a - b) > 0.1
                        ],
                        colors="#2d9b4d",
                        linewidths=0.65,
                        alpha=0.6,
                    )
                )
            ax.set(
                xlim=(center[0] - span, center[0] + span),
                ylim=(center[1] - span, center[1] + span),
                zlim=(center[2] - span, center[2] + span),
            )
            ax.set_box_aspect((1, 1, 1), zoom=1.4)
            ax.view_init(25, -55)
            ax.set_axis_off()
            ax.set_title(title, fontsize=10)
        fig.suptitle(
            core["stereochemistry"]
            + " — identical world frame and scale; magenta: CPD bonds; green: displacements",
            fontsize=12,
        )
        fig.tight_layout()
        fig.savefig(folder / "comparison.png", dpi=180)
        plt.close(fig)
    write(root / "audit.json", summary)
    for stereo, stages in summary.items():
        for tag, r in stages.items():
            print(
                stereo,
                tag,
                "attachments",
                np.round(r["endpoint_backbone_attachments_A"], 2),
                "contacts<2A",
                len(r["heavy_contacts_under_2A"]),
                "bonds>2A",
                len(r["heavy_bonds_over_2A"]),
                "piercings",
                len(r["cpd_ring_piercings"]),
            )


if __name__ == "__main__":
    main()
