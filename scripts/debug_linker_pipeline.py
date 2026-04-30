#!/usr/bin/env python3
"""End-to-end debugger for the Overhang Connections linker pipeline.

Loads a .nadoc fixture, drives the live FastAPI app via TestClient (so it
exercises the same code path as the running backend), and reports on:

  1. Topology — which strands/helices were created with the LINKER tag.
  2. Complement domains — for ds linkers, asserts each linker strand has a
     domain on the real overhang helix at the same bp range, antiparallel
     direction.
  3. Geometry — calls GET /design/geometry and verifies that the complement
     nucleotides come back tagged strand_type='linker' so the 3D view will
     render them.

Run:
    uv run python scripts/debug_linker_pipeline.py [fixture.nadoc]

Default fixture is workspace/linker_test.nadoc.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design

DEFAULT_FIXTURE = Path("workspace/linker_test.nadoc")


def banner(s: str) -> None:
    print(f"\n{'─' * 4} {s} {'─' * (74 - len(s))}")


def err(s: str) -> None:
    print(f"  \033[31m✗ {s}\033[0m")


def ok(s: str) -> None:
    print(f"  \033[32m✓ {s}\033[0m")


def info(s: str) -> None:
    print(f"    {s}")


def load_fixture(path: Path) -> Design:
    text = path.read_text()
    design = Design.from_json(text)
    # Drop any pre-existing linker artifacts so we test from a clean baseline.
    design = design.copy_with(
        helices=[h for h in design.helices if not h.id.startswith("__lnk__")],
        strands=[s for s in design.strands if not s.id.startswith("__lnk__")],
        overhang_connections=[],
    )
    return design


def show_overhangs(design: Design) -> None:
    banner("OVERHANGS IN FIXTURE")
    for o in design.overhangs:
        end = "5p" if o.id.endswith("_5p") else "3p" if o.id.endswith("_3p") else "?"
        # Find the parent strand domain that carries this overhang_id.
        dom = None
        for s in design.strands:
            for d in s.domains:
                if d.overhang_id == o.id:
                    dom = (s.id, d)
                    break
            if dom:
                break
        if dom:
            sid, d = dom
            info(
                f"{o.label or '?':>5}  id={o.id}  end={end}  "
                f"strand={sid}  helix={d.helix_id}  bp={d.start_bp}..{d.end_bp}  dir={d.direction.value}"
            )
        else:
            err(f"{o.label or '?'}  id={o.id}  HAS NO DOMAIN — complement creation will be skipped!")


def post_connection(client: TestClient, **payload) -> dict | None:
    r = client.post("/api/design/overhang-connections", json=payload)
    if r.status_code != 201:
        err(f"POST returned {r.status_code}: {r.json().get('detail', r.text)}")
        return None
    return r.json()["design"]


def show_linker_strands(design_dict: dict, conn_id: str) -> list[dict]:
    prefix = f"__lnk__{conn_id}"
    strands = [s for s in design_dict["strands"] if s["id"].startswith(prefix)]
    helices = [h for h in design_dict["helices"] if h["id"].startswith(prefix)]
    info(f"linker strands: {len(strands)}    linker (virtual) helices: {len(helices)}")
    for s in strands:
        info(f"  strand id={s['id']}  type={s['strand_type']}  color={s['color']}  domains={len(s['domains'])}")
        for i, d in enumerate(s["domains"]):
            virt = "(virtual __lnk__)" if d["helix_id"].startswith("__lnk__") else "(real OH helix)"
            info(
                f"    [{i}] helix={d['helix_id']}  bp={d['start_bp']}..{d['end_bp']}  "
                f"dir={d['direction']}  {virt}"
            )
    return strands


def validate_complement_domain(
    design: Design, oh_id: str, linker_strand: dict,
) -> bool:
    """A ds linker strand's first domain must be the antiparallel complement of
    the named overhang on the real OH helix.
    """
    # Find the OH domain in the source design.
    oh_dom = None
    for s in design.strands:
        for d in s.domains:
            if d.overhang_id == oh_id:
                oh_dom = d
                break
        if oh_dom:
            break
    if oh_dom is None:
        err(f"No OH domain for {oh_id!r} in source design — complement creation should be skipped.")
        return False

    if not linker_strand["domains"]:
        err(f"Linker strand {linker_strand['id']!r} has no domains.")
        return False
    comp = linker_strand["domains"][0]
    issues = []
    if comp["helix_id"] != oh_dom.helix_id:
        issues.append(
            f"helix mismatch: complement on {comp['helix_id']!r}, OH on {oh_dom.helix_id!r}"
        )
    if comp["direction"] == oh_dom.direction.value:
        issues.append(
            f"direction not antiparallel: both {comp['direction']}"
        )
    # bp range — the COMPLEMENT swaps start/end relative to the OH.
    if comp["start_bp"] != oh_dom.end_bp or comp["end_bp"] != oh_dom.start_bp:
        issues.append(
            f"bp range wrong: complement {comp['start_bp']}..{comp['end_bp']}, "
            f"expected {oh_dom.end_bp}..{oh_dom.start_bp} (OH was {oh_dom.start_bp}..{oh_dom.end_bp})"
        )

    if issues:
        for i in issues:
            err(i)
        return False
    ok(f"complement on {oh_dom.helix_id} bp {oh_dom.start_bp}..{oh_dom.end_bp} dir={comp['direction']} ⊥ OH")
    return True


def validate_geometry(client: TestClient, conn_id: str, expected_strands: list[str]) -> bool:
    """Pull /design/geometry and verify each linker strand has its complement
    nucleotides emitted (real-helix domains only — the bridge is invisible).
    """
    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]
    info(f"GET /design/geometry returned {len(nucs)} nucleotides total")

    all_ok = True
    for sid in expected_strands:
        snucs = [n for n in nucs if n.get("strand_id") == sid]
        if not snucs:
            err(f"{sid}: NO nucleotides emitted — 3D view will show nothing for this strand")
            all_ok = False
            continue
        # Bridge domains live on __lnk__ helices which the geometry pipeline
        # skips, so only complement-domain nucs come back. They should all be
        # tagged strand_type=linker.
        helix_ids = {n["helix_id"] for n in snucs}
        types = {n["strand_type"] for n in snucs}
        bps = sorted({n["bp_index"] for n in snucs})
        ok(
            f"{sid}: {len(snucs)} nucs on helix(es) {sorted(helix_ids)}  "
            f"types={sorted(types)}  bp_range={bps[0]}..{bps[-1]}"
        )
        if "linker" not in types:
            err(f"  expected strand_type 'linker', got {types}")
            all_ok = False
        if any(h.startswith("__lnk__") for h in helix_ids):
            err(f"  unexpected nucs on virtual __lnk__ helix (geometry should skip these)")
            all_ok = False
    return all_ok


def probe_arc_positions(
    client: TestClient,
    conn_payload: dict,
    overhang_a_id: str, overhang_a_attach: str,
    overhang_b_id: str, overhang_b_attach: str,
    conn_id: Optional[str] = None,
) -> None:
    """Replicate the frontend overhang_link_arcs.js logic against /design/geometry
    and report whether the arc endpoints are computable. The arc anchors on the
    LINKER complement strand at the same (helix_id, bp_index) as the OH attach
    nucleotide — i.e. the antiparallel partner bead.
    """
    banner("ARC-POSITION PROBE (mirrors frontend overhang_link_arcs.js)")
    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]

    by_oh: dict[str, list] = {}
    for n in nucs:
        oh = n.get("overhang_id")
        if oh:
            by_oh.setdefault(oh, []).append(n)
    by_strand: dict[str, list] = {}
    for n in nucs:
        sid = n.get("strand_id")
        if sid:
            by_strand.setdefault(sid, []).append(n)

    for side, ovhg_id, attach in (
        ("a", overhang_a_id, overhang_a_attach),
        ("b", overhang_b_id, overhang_b_attach),
    ):
        bucket = by_oh.get(ovhg_id, [])
        info(f"overhang {ovhg_id}  attach={attach}  → {len(bucket)} nucs with overhang_id set")
        if not bucket:
            err(f"NO nucs have overhang_id={ovhg_id!r} → frontend arc cannot anchor here")
            continue
        # Frontend picks the OH attach nuc first to get (helix_id, bp_index).
        tip = next((n for n in bucket if n.get("is_five_prime") or n.get("is_three_prime")), bucket[0])
        flag = "is_five_prime" if tip.get("is_five_prime") else "is_three_prime" if tip.get("is_three_prime") else "(no terminal flag)"
        if attach == "free_end":
            oh_attach = tip
        else:
            oh_attach = max(bucket, key=lambda n: abs(n.get("bp_index", 0) - tip.get("bp_index", 0)))
        info(f"  OH attach nuc  helix={oh_attach['helix_id']}  bp={oh_attach['bp_index']}  dir={oh_attach['direction']}  flag={flag}")

        # Now hop to the linker complement strand at the same (helix, bp).
        if conn_id is None:
            err("  conn_id not supplied — cannot find linker strand")
            continue
        linker_sid = f"__lnk__{conn_id}__{side}"
        linker_nucs = by_strand.get(linker_sid, [])
        partner = next(
            (n for n in linker_nucs
             if n["helix_id"] == oh_attach["helix_id"]
             and n["bp_index"] == oh_attach["bp_index"]),
            None,
        )
        if partner is None:
            err(
                f"  no linker partner on {linker_sid} at "
                f"({oh_attach['helix_id']}, bp={oh_attach['bp_index']}) — "
                f"arc will fall back to OH bead"
            )
            target = oh_attach
        else:
            ok(
                f"  linker partner on {linker_sid}  helix={partner['helix_id']}  "
                f"bp={partner['bp_index']}  dir={partner['direction']}"
            )
            target = partner
        pos = target.get("backbone_position") or target.get("base_position")
        if pos is None:
            err("  target nuc has no backbone_position / base_position — arc cannot be drawn")
        else:
            ok(f"    arc anchor world=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")


def reset_to_baseline(design: Design) -> None:
    design_state.set_design(design)


def run_case(client: TestClient, baseline: Design, label: str, payload: dict) -> None:
    banner(f"CASE: {label}")
    reset_to_baseline(baseline)
    design_dict = post_connection(client, **payload)
    if design_dict is None:
        return
    conn = design_dict["overhang_connections"][-1]
    cid = conn["id"]
    info(f"created connection id={cid}  name={conn['name']}  type={conn['linker_type']}")
    strands = show_linker_strands(design_dict, cid)

    # Per-strand complement validation (ds only — ss has no complement).
    if conn["linker_type"] == "ds":
        banner(f"COMPLEMENT VALIDATION ({label})")
        all_ok = True
        for side, ovhg_id in (("a", payload["overhang_a_id"]), ("b", payload["overhang_b_id"])):
            sid = f"__lnk__{cid}__{side}"
            strand = next((s for s in strands if s["id"] == sid), None)
            if strand is None:
                err(f"strand {sid} missing!")
                all_ok = False
                continue
            all_ok &= validate_complement_domain(baseline, ovhg_id, strand)

    # Geometry pipeline — the actual proof that 3D will render.
    # Both ss and ds use the __a/__b strand-id convention; the only difference
    # is whether each strand also carries a bridge half (ds) or just the
    # complement domain (ss).
    banner(f"GEOMETRY ({label})")
    expected = [f"__lnk__{cid}__a", f"__lnk__{cid}__b"]
    expected = [sid for sid in expected if any(s["id"] == sid for s in strands)]
    validate_geometry(client, cid, expected)

    probe_arc_positions(
        client, payload,
        payload["overhang_a_id"], payload["overhang_a_attach"],
        payload["overhang_b_id"], payload["overhang_b_attach"],
        conn_id=cid,
    )


def main(argv: list[str]) -> int:
    fixture = Path(argv[1]) if len(argv) > 1 else DEFAULT_FIXTURE
    if not fixture.exists():
        err(f"Fixture not found: {fixture}")
        return 1
    print(f"Fixture: {fixture}")

    baseline = load_fixture(fixture)
    show_overhangs(baseline)

    client = TestClient(app)

    if len(baseline.overhangs) < 2:
        err(f"Fixture has only {len(baseline.overhangs)} overhang(s); need at least 2 to link")
        return 1

    a, b = baseline.overhangs[0], baseline.overhangs[1]
    base_payload = {
        "overhang_a_id": a.id, "overhang_a_attach": "free_end",
        "overhang_b_id": b.id, "overhang_b_attach": "root",
        "length_value": 12, "length_unit": "bp",
    }

    # ds case: forces complement domains to be created.
    run_case(client, baseline, "ds linker (free_end ↔ root)",
             {**base_payload, "linker_type": "ds"})
    # ss case: bridge only — nothing should render in 3D, but topology is valid.
    run_case(client, baseline, "ss linker (free_end ↔ root)",
             {**base_payload, "linker_type": "ss"})

    # User-flow simulation: load the original .nadoc verbatim (preserves any
    # linker strand + connection saved in the file) and confirm arc anchors.
    banner("USER-FLOW SIMULATION (load fixture verbatim, no overrides)")
    raw = Design.from_json(fixture.read_text())
    info(f"loaded fixture has  helices={len(raw.helices)}  strands={len(raw.strands)}  "
         f"overhangs={len(raw.overhangs)}  connections={len(raw.overhang_connections)}")
    saved_lnk = [s for s in raw.strands if s.id.startswith("__lnk__")]
    info(f"saved linker strands: {len(saved_lnk)}  → {[s.id for s in saved_lnk]}")
    design_state.set_design(raw)
    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]
    info(f"GET /design/geometry → {len(nucs)} total nucs after load")
    for sid in [s.id for s in saved_lnk]:
        snucs = [n for n in nucs if n.get("strand_id") == sid]
        if snucs:
            ok(f"{sid}: {len(snucs)} nucs visible to renderer")
        else:
            err(f"{sid}: 0 nucs in geometry → renderer will draw nothing for this strand")
    if raw.overhang_connections:
        for c in raw.overhang_connections:
            info(f"connection {c.name} ({c.linker_type}): "
                 f"A={c.overhang_a_id}({c.overhang_a_attach})  "
                 f"B={c.overhang_b_id}({c.overhang_b_attach})")
            probe_arc_positions(
                client, {},
                c.overhang_a_id, c.overhang_a_attach,
                c.overhang_b_id, c.overhang_b_attach,
                conn_id=c.id,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
