"""Hairpin / self-dimer checker (backend/core/hairpin_dimer.py + its route)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.hairpin_dimer import (
    Conditions,
    check_design,
    dimer,
    hairpin,
    linker_strand_sequence,
)
from backend.core.lattice import (
    assign_overhang_connection_names,
    generate_linker_topology,
)
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    OverhangConnection,
    OverhangSpec,
    Strand,
    StrandType,
    TmSettings,
    Vec3,
)

client = TestClient(app)

# 8-bp GC stem, T4 loop: a hairpin far above 30 °C, and self-complementary
# enough to dimerise.
STRONG = "GCGCGCGCTTTTGCGCGCGCTT"
# (AC)n has no Watson–Crick self-complement: no hairpin, no self-dimer.
BENIGN = "ACACACACACACACACACACAC"
COND = Conditions()


def _rc(seq: str) -> str:
    return seq.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]


def _oh_helix(hid: str, x: float, n: int) -> Helix:
    return Helix(
        id=hid,
        axis_start=Vec3(x=x, y=0.0, z=0.0),
        axis_end=Vec3(x=x, y=0.0, z=n * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=n,
        grid_pos=(0, int(x)),
    )


def _oh_domain(hid: str, oid: str, n: int) -> Domain:
    return Domain(
        helix_id=hid,
        start_bp=0,
        end_bp=n - 1,
        direction=Direction.FORWARD,
        overhang_id=oid,
    )


def _seed(seq_a=STRONG, seq_b=BENIGN, *, linker_type=None, bridge="CCCAAA") -> Design:
    """Two single-overhang strands (A, B), optionally joined by a linker."""
    base = _demo_design()
    n = 22
    ha, hb = _oh_helix("h_a", 2, n), _oh_helix("h_b", 5, n)
    sa = Strand(id="s_a", domains=[_oh_domain("h_a", "ovhg_h_a_0_5p", n)])
    sb = Strand(id="s_b", domains=[_oh_domain("h_b", "ovhg_h_b_0_3p", n)])
    oa = OverhangSpec(
        id="ovhg_h_a_0_5p", helix_id="h_a", strand_id="s_a", sequence=seq_a
    )
    ob = OverhangSpec(
        id="ovhg_h_b_0_3p", helix_id="h_b", strand_id="s_b", sequence=seq_b
    )
    d = base.model_copy(
        update={
            "helices": [*base.helices, ha, hb],
            "strands": [*base.strands, sa, sb],
            "overhangs": [oa, ob],
        }
    )
    if linker_type is None:
        return d
    conn = OverhangConnection(
        overhang_a_id=oa.id,
        overhang_a_attach="free_end",
        overhang_b_id=ob.id,
        overhang_b_attach="free_end",
        linker_type=linker_type,
        length_value=len(bridge),
        length_unit="bp",
        bridge_sequence=bridge,
    )
    d = assign_overhang_connection_names(
        d.model_copy(update={"overhang_connections": [conn]})
    )
    return generate_linker_topology(d, d.overhang_connections[0])


def _by_key(report: dict) -> dict:
    return {c["key"]: c for c in report["checks"]}


# ── Sequence-level thermodynamics ────────────────────────────────────────────


def test_hairpin_tm_is_the_unimolecular_two_state_midpoint():
    """For a unimolecular transition Tm = ΔH/ΔS, independent of concentration."""
    hit = hairpin(STRONG, COND)
    assert hit is not None and hit["tm"] > 30.0
    assert hit["tm"] == pytest.approx(hit["dh"] * 1000.0 / hit["ds"] - 273.15, abs=0.5)
    assert hit["structure"][-1] == STRONG  # slash diagram + the sequence line


def test_hairpin_tm_is_concentration_independent_but_dimer_tm_is_not():
    lo, hi = Conditions(conc_nM=50.0), Conditions(conc_nM=5000.0)
    assert hairpin(STRONG, lo)["tm"] == pytest.approx(
        hairpin(STRONG, hi)["tm"], abs=0.01
    )
    assert dimer(STRONG, STRONG, hi)["tm"] > dimer(STRONG, STRONG, lo)["tm"] + 1.0


def test_monovalent_salt_stabilises_both_structures():
    lo = Conditions(na_mM=10.0, mg_mM=0.0)
    hi = Conditions(na_mM=500.0, mg_mM=0.0)
    assert hairpin(STRONG, hi)["tm"] > hairpin(STRONG, lo)["tm"]
    assert dimer(STRONG, STRONG, hi)["tm"] > dimer(STRONG, STRONG, lo)["tm"]


def test_origami_magnesium_stabilises_relative_to_idt_default_salt():
    """10 mM Mg²⁺ screens more than 50 mM Na⁺, so structures melt higher."""
    idt = Conditions(na_mM=50.0, mg_mM=0.0, conc_nM=250.0)
    assert hairpin(STRONG, COND)["tm"] > hairpin(STRONG, idt)["tm"] + 5.0
    assert dimer(STRONG, STRONG, COND)["tm"] > dimer(STRONG, STRONG, idt)["tm"]


def test_conditions_reject_a_cation_free_buffer():
    """primer3 returns Tm = -273 °C with no cation — refuse instead."""
    with pytest.raises(ValueError):
        Conditions(na_mM=0.0, mg_mM=0.0)


def test_sequence_without_self_complement_forms_nothing():
    assert hairpin(BENIGN, COND) is None
    assert dimer(BENIGN, BENIGN, COND) is None
    assert hairpin("T" * 30, COND) is None


def test_hairpin_beyond_the_60nt_thal_limit_is_found_by_windowing():
    """primer3 aligns ≤60 nt; a stem–loop near the 3' end of a 100-mer must
    still be found, with the offset locating it in the full sequence."""
    core = "GCGCGCGCTTTTGCGCGCGC"
    seq = "T" * 70 + core + "T" * 10
    hit = hairpin(seq, COND)
    assert hit is not None and hit["tm"] > 80.0
    start = seq.index(core)
    assert hit["offset"] <= start
    assert start + len(core) <= hit["offset"] + 60


def test_self_dimer_of_two_long_copies_is_found_by_windowing():
    """Both copies > 60 nt (the case primer3 refuses outright)."""
    seq = "T" * 50 + "GGCGCGCGCGCC" + "T" * 50
    hit = dimer(seq, seq, COND)
    assert hit is not None and hit["tm"] > 30.0


def test_n_bases_split_the_analysis_into_defined_runs():
    hit = hairpin("NNNN" + STRONG + "NNNN", COND)
    assert hit is not None and hit["offset"] >= 4
    assert hairpin("N" * 20, COND) is None
    assert dimer("N" * 20, "N" * 20, COND) is None


# ── Design scoping ───────────────────────────────────────────────────────────


def test_flags_only_structures_above_threshold():
    report = check_design(_seed())
    checks = _by_key(report)
    a, b = checks["overhang:ovhg_h_a_0_5p"], checks["overhang:ovhg_h_b_0_3p"]
    assert a["flagged"] and a["max_tm"] > 30.0 and a["strand_id"] == "s_a"
    assert not b["flagged"] and b["max_tm"] is None
    assert report["summary"] == {
        "checked": 2,
        "flagged": 1,
        "critical": 1,
        "unsequenced": 0,
    }
    assert report["threshold_c"] == 30.0 and report["design_id"] == "demo"


def test_severity_tiers_warning_above_30_critical_above_50():
    """Amber ⚠ for 30 < Tm ≤ 50 °C, red ⚠ above 50 °C (origami buffer)."""
    moderate = "ACGTAGCGTGTCTCCC"  # hairpin Tm ≈ 42.5 °C at 10 mM Mg²⁺
    report = check_design(_seed(seq_a=STRONG, seq_b=moderate))
    checks = _by_key(report)
    a, b = checks["overhang:ovhg_h_a_0_5p"], checks["overhang:ovhg_h_b_0_3p"]
    assert a["severity"] == "critical" and a["max_tm"] > 50.0
    assert b["severity"] == "warning" and 30.0 < b["max_tm"] <= 50.0
    assert report["severe_threshold_c"] == 50.0
    assert report["summary"]["flagged"] == 2 and report["summary"]["critical"] == 1
    unflagged = check_design(_seed(seq_b=BENIGN))
    assert _by_key(unflagged)["overhang:ovhg_h_b_0_3p"]["severity"] is None


def test_critical_threshold_is_strict_and_adjustable():
    tm = check_design(_seed())["checks"][0]["max_tm"]
    assert check_design(_seed(), severe_c=tm)["checks"][0]["severity"] == "warning"
    assert (
        check_design(_seed(), severe_c=tm - 0.01)["checks"][0]["severity"] == "critical"
    )


def test_threshold_is_strict_greater_than():
    tm = check_design(_seed())["checks"][0]["max_tm"]
    assert not check_design(_seed(), threshold_c=tm)["checks"][0]["flagged"]
    assert check_design(_seed(), threshold_c=tm - 0.01)["checks"][0]["flagged"]


def test_default_conditions_are_origami_folding_buffer():
    """No NaCl, 10 mM MgCl2, 200 nM oligo — independent of design.tm_settings
    (which keeps driving the sub-domain Tm annotations)."""
    d = _seed()
    a = check_design(d)
    b = check_design(d.model_copy(update={"tm_settings": TmSettings(na_mM=500.0)}))
    assert a["conditions"] == {
        "na_mM": 0.0,
        "mg_mM": 10.0,
        "dntp_mM": 0.0,
        "conc_nM": 200.0,
        "temp_c": 37.0,
    }
    assert a["checks"] == b["checks"]


def test_ss_linker_strand_is_complement_bridge_complement():
    """Watson–Crick antiparallel: a complement domain binding the whole overhang
    reads, 5'→3', as the overhang's reverse complement."""
    d = _seed(linker_type="ss", bridge="CCCAAA")
    (linker,) = [s for s in d.strands if s.strand_type == StrandType.LINKER]
    assert linker_strand_sequence(d, linker) == _rc(STRONG) + "CCCAAA" + _rc(BENIGN)
    entry = _by_key(check_design(d))[f"linker:{linker.id}"]
    assert entry["flagged"]  # RC of the strong hairpin is itself a strong hairpin
    assert entry["overhang_ids"] == ["ovhg_h_a_0_5p", "ovhg_h_b_0_3p"]
    assert entry["inputs"]["bridge"] == "CCCAAA"
    # Staleness contract: the frontend (hairpin_dimer_report.domainsSignature)
    # rebuilds this exact string from strand.domains.
    cid = entry["connection_id"]
    assert entry["inputs"]["domains"] == (
        f"h_a:21:0:REVERSE|__lnk__{cid}:0:5:FORWARD|h_b:21:0:REVERSE"
    )


def test_ds_linker_bridge_halves_are_mutually_complementary():
    d = _seed(linker_type="ds", bridge="CCCAAAGT")
    halves = {}
    for s in d.strands:
        if s.strand_type != StrandType.LINKER:
            continue
        seq, pos = linker_strand_sequence(d, s), 0
        for dom in s.domains:
            span = abs(dom.end_bp - dom.start_bp) + 1
            if dom.helix_id.startswith("__lnk__"):
                halves[s.id[-1]] = seq[pos : pos + span]
            pos += span
    assert halves["a"] == "CCCAAAGT"
    assert halves["b"] == _rc(halves["a"])


def test_partial_scope_checks_only_the_named_overhang_and_its_linkers():
    d = _seed(linker_type="ss")
    keys = set(_by_key(check_design(d, overhang_ids=["ovhg_h_b_0_3p"])))
    assert "overhang:ovhg_h_b_0_3p" in keys
    assert "overhang:ovhg_h_a_0_5p" not in keys
    assert any(k.startswith("linker:") for k in keys)  # the linker binds B


def test_two_overhangs_on_one_strand_get_a_cross_dimer():
    """5' tail of one copy × 3' tail of another copy — a strand self-dimer
    even though neither tail structures on its own."""
    base = _demo_design()
    n = 16
    x, y = "ACACACACACACACAC", "GTGTGTGTGTGTGTGT"  # y = rc(x)
    s = Strand(
        id="s_two",
        domains=[
            _oh_domain("h_p", "ovhg_h_p_0_5p", n),
            _oh_domain("h_q", "ovhg_h_q_0_3p", n),
        ],
    )
    d = base.model_copy(
        update={
            "helices": [*base.helices, _oh_helix("h_p", 2, n), _oh_helix("h_q", 5, n)],
            "strands": [*base.strands, s],
            "overhangs": [
                OverhangSpec(
                    id="ovhg_h_p_0_5p", helix_id="h_p", strand_id="s_two", sequence=x
                ),
                OverhangSpec(
                    id="ovhg_h_q_0_3p", helix_id="h_q", strand_id="s_two", sequence=y
                ),
            ],
        }
    )
    checks = _by_key(check_design(d))
    assert not checks["overhang:ovhg_h_p_0_5p"]["flagged"]
    assert not checks["overhang:ovhg_h_q_0_3p"]["flagged"]
    pair = checks["overhang_pair:ovhg_h_p_0_5p|ovhg_h_q_0_3p"]
    assert pair["flagged"] and pair["strand_id"] == "s_two"


def test_unsequenced_and_partial_overhangs():
    d = _seed(seq_a=None, seq_b="NNNN" + STRONG[4:])
    checks = _by_key(check_design(d))
    a, b = checks["overhang:ovhg_h_a_0_5p"], checks["overhang:ovhg_h_b_0_3p"]
    assert a["status"] == "unsequenced" and not a["flagged"]
    assert a["sequence"] == "N" * 22  # N-padded to the backing domain
    assert b["status"] == "partial"


def test_short_defined_overhang_is_checked_not_unsequenced():
    """A 3-nt overhang (real designs have them) is sequenced; it just cannot
    form structure — it must not be reported as unsequenced."""
    d = _seed(seq_a="CTG" + "N" * 19)
    d = d.model_copy(
        update={
            "overhangs": [
                o.model_copy(update={"sequence": "CTG"}) for o in d.overhangs
            ],
            "strands": [
                s.model_copy(
                    update={"domains": [s.domains[0].model_copy(update={"end_bp": 2})]}
                )
                if s.id in ("s_a", "s_b")
                else s
                for s in d.strands
            ],
        }
    )
    report = check_design(d)
    assert {c["status"] for c in report["checks"]} == {"checked"}
    assert report["summary"] == {
        "checked": 2,
        "flagged": 0,
        "critical": 0,
        "unsequenced": 0,
    }


def test_reference_and_auxiliary_overhangs_are_skipped():
    d = _seed()
    d = d.model_copy(
        update={
            "strands": [
                s.model_copy(update={"is_reference": True}) if s.id == "s_a" else s
                for s in d.strands
            ],
            "overhangs": [
                o.model_copy(update={"auxiliary_endpoint": True})
                if o.id == "ovhg_h_b_0_3p"
                else o
                for o in d.overhangs
            ],
        }
    )
    assert check_design(d)["checks"] == []


# ── HTTP ─────────────────────────────────────────────────────────────────────


def test_route_is_read_only_and_matches_core():
    d = _seed(linker_type="ss")
    design_state.set_design(d)
    before = design_state.get_or_404()
    r = client.post("/api/design/hairpin-dimer-check")
    assert r.status_code == 200, r.text
    assert r.json()["checks"] == check_design(d)["checks"]
    assert design_state.get_or_404() is before  # no mutation, no undo entry

    r = client.post(
        "/api/design/hairpin-dimer-check",
        json={"overhang_ids": ["ovhg_h_a_0_5p"], "threshold_c": 150.0},
    )
    body = r.json()
    assert body["scope"] == "partial" and body["summary"]["flagged"] == 0
    raised = client.post(
        "/api/design/hairpin-dimer-check", json={"severe_threshold_c": 150.0}
    ).json()
    assert raised["severe_threshold_c"] == 150.0
    assert {c["severity"] for c in raised["checks"] if c["flagged"]} == {"warning"}

    idt = client.post(
        "/api/design/hairpin-dimer-check",
        json={"na_mM": 50, "mg_mM": 0, "conc_nM": 250},
    ).json()
    assert idt["conditions"]["na_mM"] == 50 and idt["conditions"]["mg_mM"] == 0
    bad = client.post("/api/design/hairpin-dimer-check", json={"mg_mM": 0})
    assert bad.status_code == 422


def test_generate_all_reports_generated_overhang_ids():
    design_state.set_design(_seed(seq_a=None, seq_b=None))
    r = client.post("/api/design/generate-overhang-sequences")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["generated_overhang_ids"]) == [
        "ovhg_h_a_0_5p",
        "ovhg_h_b_0_3p",
    ]
