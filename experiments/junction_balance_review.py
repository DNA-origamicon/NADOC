"""Isolated, derived O5' frame-bisector comparison; never promotes placement."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import html
import json
from pathlib import Path

import numpy as np

from backend.core import atomistic, design_geometry
from backend.core.constants import BDNA_MINOR_GROOVE_ANGLE_RAD
from backend.core.deformation import effective_helix_for_geometry
from backend.core.measured_positioning import FULL_REP
from backend.core.models import Design
from backend.core.molecular_placement_audit import (
    _affected_serials,
    _defect_serials,
    _model_diagnostics,
)
from experiments.mrdna_frame_review_figure import junction_defects, render_plate

ROOT = Path(__file__).resolve().parents[1]
OFFSET = (
    FULL_REP.backbone_fwd.azimuth_deg + FULL_REP.backbone_rev.azimuth_deg
) / 2 - np.degrees(BDNA_MINOR_GROOVE_ANGLE_RAD) / 2


@contextmanager
def candidate_roll():
    """Process-local diagnostic only; restore both consumers even on failure."""
    old = (
        design_geometry.ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG,
        atomistic._ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG,
    )
    try:
        design_geometry.ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG = OFFSET
        atomistic._ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG = OFFSET
        yield
    finally:
        (
            design_geometry.ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG,
            atomistic._ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG,
        ) = old


def xyz(model):
    return np.array([[a.x, a.y, a.z] for a in model.atoms])


def compare(design, phase, fast, *, candidate_design=None):
    current = atomistic.build_atomistic_model(design, fast_bridges=fast)
    if candidate_design is None:
        with candidate_roll():
            candidate = atomistic.build_atomistic_model(design, fast_bridges=fast)
    else:
        candidate = atomistic.build_atomistic_model(candidate_design, fast_bridges=fast)
    identity = lambda a: (
        a.strand_id,
        a.helix_id,
        a.bp_index,
        a.direction,
        a.copy_k,
        a.crossover_id,
        a.extra_base_k,
        a.name,
    )
    assert [identity(a) for a in current.atoms] == [
        identity(a) for a in candidate.atoms
    ]
    assert current.bonds == candidate.bonds
    models = dict(current=current, candidate=candidate)
    diagnostics = {s: _model_diagnostics(design, m) for s, m in models.items()}
    affected, displacement = _affected_serials(
        current, candidate, diagnostics["current"], diagnostics["candidate"]
    )
    points = {s: xyz(m) for s, m in models.items()}
    junctions = []
    for i, j in current.bonds:
        if current.atoms[i].helix_id == current.atoms[j].helix_id:
            continue
        lengths = {s: float(np.linalg.norm(p[i] - p[j])) for s, p in points.items()}
        junctions.append(
            dict(
                serials=[i, j],
                identities=[identity(current.atoms[i]), identity(current.atoms[j])],
                length_nm={"reference": lengths["current"], **lengths},
                max_endpoint_displacement_nm=float(
                    max(
                        np.linalg.norm(points["candidate"][k] - points["current"][k])
                        for k in (i, j)
                    )
                ),
                defects={
                    s: junction_defects(m, diagnostics[s], (i, j))
                    for s, m in models.items()
                },
            )
        )
    return {
        "phase_deg": phase,
        "read_only": True,
        "ready_for_review": False,
        "figure_title": f"O5′ frame bisector — {'Viewer' if fast else 'Export'}, phase {phase}°\nCurrent offset 14.600°; isolated candidate 14.625°. Native topology unchanged.",
        "affected_atom_serials": affected,
        "displacement": displacement,
        "junctions": junctions,
        "defect_atom_serials": {s: _defect_serials(d) for s, d in diagnostics.items()},
        **{
            s: {
                **atomistic.atomistic_to_json(m),
                "atoms": [asdict(a) for a in m.atoms],
                "diagnostics": diagnostics[s],
            }
            for s, m in models.items()
        },
    }


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "Examples/2hb_xover_val.nadoc"
    original = Design.model_validate_json(source.read_text())
    snapshot = original.model_dump_json()
    rows = []
    for phase in range(0, 360, 10):
        design = original.model_copy(deep=True)
        design.helices = [
            effective_helix_for_geometry(h, original).model_copy(
                update={
                    "grid_pos": None,
                    "phase_offset": effective_helix_for_geometry(
                        h, original
                    ).phase_offset
                    + np.radians(phase),
                }
            )
            for h in original.helices
        ]
        for fast, kind in ((True, "viewer"), (False, "export")):
            bundle = compare(design, phase, fast)
            if phase == 0:
                np.testing.assert_allclose(
                    xyz(atomistic.build_atomistic_model(original, fast_bridges=fast)),
                    np.array(
                        [[a["x"], a["y"], a["z"]] for a in bundle["current"]["atoms"]]
                    ),
                    rtol=0,
                    atol=1e-12,
                )
            filename = f"{kind}-{phase:03d}.json.gz"
            with gzip.open(output / filename, "wt") as stream:
                json.dump(bundle, stream, separators=(",", ":"))
            row = {
                "phase_deg": phase,
                "builder": kind,
                "artifact": filename,
                "displacement": {
                    k: v for k, v in bundle["displacement"].items() if k != "vectors"
                },
                "diagnostics": {
                    s: bundle[s]["diagnostics"] for s in ("current", "candidate")
                },
                "junctions": bundle["junctions"],
            }
            rows.append(row)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in row.items()
                        if k not in ("diagnostics", "junctions")
                    }
                ),
                flush=True,
            )
    from tests.test_junction_balance import _junction_arc_deltas

    fixtures = []
    for name in ("workspace/2x3x100_Sq_test.nadoc", "workspace/6hb_e_test.nadoc"):
        design = Design.model_validate_json((ROOT / name).read_text())
        before = _junction_arc_deltas(design, junction_balance=True)
        with candidate_roll():
            after = _junction_arc_deltas(design, junction_balance=True)
        fixtures.append(
            {
                "source": name,
                "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                "current_deltas_nm": before,
                "candidate_deltas_nm": after,
            }
        )
    assert original.model_dump_json() == snapshot
    report = {
        "current_offset_deg": 14.6,
        "candidate_offset_deg": float(OFFSET),
        "derivation": "Mean O5' azimuth (8.23° + 171.02°)/2 minus the construction groove bisector 150°/2 = 14.625°. No fixture fit.",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "rows": rows,
        "fixtures": fixtures,
        "production_unchanged": True,
        "ready_for_review": False,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2))
    build_review(output, report)
    return report


def build_review(output, report):
    rows = report["rows"]
    chosen = [rows[0], rows[1]]
    for kind in ("viewer", "export"):
        subset = [r for r in rows if r["builder"] == kind]
        for side in ("current", "candidate"):
            for field in ("clashes", "piercings"):
                key = lambda r: (
                    r["diagnostics"][side]["n_clashes"]
                    if field == "clashes"
                    else r["diagnostics"][side]["piercing"]["n_pierced"]
                )
                for row in (min(subset, key=key), max(subset, key=key)):
                    if row not in chosen:
                        chosen.append(row)
        for row in (
            max(subset, key=lambda r: r["displacement"]["max_nm"]),
            max(subset, key=lambda r: r["diagnostics"]["candidate"]["n_clashes"]
                - r["diagnostics"]["current"]["n_clashes"]),
        ):
            if row not in chosen:
                chosen.append(row)
    sections = []
    for row in chosen:
        with gzip.open(output / row["artifact"], "rt") as stream:
            bundle = json.load(stream)
        png = row["artifact"].replace(".json.gz", ".png")
        render_plate(bundle, output / png)
        table = "".join(
            f"<tr><td>{j['serials']}</td><td>{j['length_nm']['current']:.8f}</td><td>{j['length_nm']['candidate']:.8f}</td><td>{j['length_nm']['candidate'] - j['length_nm']['current']:+.8f}</td><td>{j['max_endpoint_displacement_nm']:.8f}</td>"
            + "".join(
                f"<td>{len(j['defects']['current'][kind])} → {len(j['defects']['candidate'][kind])}</td>"
                for kind in ("clashes", "piercings")
            )
            + "</tr>"
            for j in bundle["junctions"]
        )
        sections.append(
            f"<h2>{row['builder']} phase {row['phase_deg']}°</h2><img src='{png}'><p><a href='{row['artifact']}'>Exact atoms, bonds, rings and displacement vectors</a></p><table><tr><th>Bond serials</th><th>Current nm</th><th>Candidate nm</th><th>Δ length nm</th><th>Endpoint displacement nm</th><th>Clashes</th><th>Piercings</th></tr>{table}</table>"
        )
    (output / "review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>O5′ frame bisector review</title><style>body{font:16px system-ui;max-width:1500px;margin:auto;padding:2rem}img{width:100%}td,th{padding:.4rem;border:1px solid #aaa}table{border-collapse:collapse}</style><h1>O5′ frame bisector: isolated molecular candidate</h1><p>Current is the unchanged native Viewer/Export atom placement. Candidate applies a further −0.025° roll about every helix axis, using the same atom templates, topology and linker builders. This changes molecular placement and requires explicit approval.</p><ol><li>Load Examples/2hb_xover_val.nadoc; retain all four covalent interhelix bonds and all 2,800 atoms.</li><li>Current: build native atoms with the shared 14.600° template-frame offset.</li><li>Candidate diagnostic: use 14.625° in both native Full and atomistic frame projection. No lattice phase constant, atom template, detector threshold or golden changes.</li><li>Engineering controls: sweep the diagnostic helix frames through 0–350° in 10° steps for both Viewer and Export. Phase zero must reproduce native atoms exactly. These are diagnostic constructions, not authored feature-log operations.</li></ol><p>"
        + html.escape(report["derivation"])
        + "</p><p>Blue is Current; magenta is Candidate; yellow vectors show actual displacement. Inspect the highlighted contacts and rings as well as the per-junction bond deltas. No physical validity is inferred from equal arc lengths.</p>"
        + "".join(sections[:2])
        + "<details><summary>Engineering controls: contacts, piercings and maximum displacement</summary>"
        + "".join(sections[2:])
        + "</details>"
        + "<p><a href='summary.json'>All 72 phase/builder cases and both full-design junction measurements</a></p>"
    )
    return output / "review.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if args.render_only:
        build_review(args.output, json.loads((args.output / "summary.json").read_text()))
    else:
        build(args.output)
