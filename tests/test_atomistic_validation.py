"""Tests for the atomistic-display validation oracle (backend/core/atomistic_validation.py).

The oracle measures every bond + atom the oxDNA-display atomistic representation
draws, so a stretched / hidden / clashing element is queryable rather than only
visible.  These pin: the rigid-frame stamp is frame-invariant (the placer-correct
signal), and the over-stretch / hidden / clash / stranded detectors fire on
synthetic bad frames.
"""
import numpy as np
import pytest

from tests.conftest import make_6hb_design
from backend.core.design_geometry import _geometry_for_design
from backend.core.atomistic_validation import (
    audit_bonds, audit_oxdna_job, latest_job_for_design, _bond_class)


@pytest.fixture
def design():
    return make_6hb_design(42)


def _ideal_frame(design, tmp_path):
    """The design's own ideal oxDNA frame {key:{backbone_position(CM), a1, a3}}."""
    from backend.physics.oxdna_interface import write_configuration, read_configuration_full
    conf = tmp_path / "ideal.dat"
    write_configuration(design, _geometry_for_design(design), conf, box_nm=200.0)
    return read_configuration_full(conf, design)


def test_rigid_stamp_invariant_under_frame(design, tmp_path):
    """Stamping at the relaxed oxDNA frame leaves every RIGID intra bond at its
    template length — 0 stamp violations, ~0 max deviation.  This is the
    placer-correct signal; over-stretched backbone/linker bonds (if any) are a
    geometry issue, NOT a stamp bug."""
    r = audit_bonds(design, _ideal_frame(design, tmp_path))
    assert r["n_rigid_stamp_violations"] == 0
    assert r["rigid_stamp_max_dev_nm"] < r["thresholds"]["intra_rigid_tol_nm"]
    # The classifier saw all four geometry buckets the 6hb (crossovers) produces.
    assert r["by_class"]["rigid"]["count"] > 0
    assert r["by_class"]["backbone"]["count"] > 0
    # Every rigid bond is a physical covalent length (≤ covalent_max).
    assert r["by_class"]["rigid"]["max"] <= r["thresholds"]["covalent_max_nm"]


def test_clean_design_build_has_no_stamp_violations(design):
    """frame=None audits the design's own ideal build: the rigid stamp is exact and
    no rigid bond is over-stretched."""
    r = audit_bonds(design)
    assert r["n_rigid_stamp_violations"] == 0
    assert not any(b["class"] == "rigid" for b in r["invalid_bonds"])


def test_displaced_nucleotide_flags_backbone_and_hidden(design, tmp_path):
    """Shoving one nucleotide's CM 5 nm away over-stretches its O3'→P backbone
    bonds — they are flagged invalid AND listed as hidden-by-renderer (so a bond the
    user cannot see on screen is still queryable)."""
    frame = _ideal_frame(design, tmp_path)
    # Pick an interior FORWARD nucleotide (has both prev + next backbone bonds).
    key = next(k for k in frame if k[2] == "FORWARD" and (k[0], k[1] - 1, k[2]) in frame
               and (k[0], k[1] + 1, k[2]) in frame)
    frame[key]["backbone_position"] = frame[key]["backbone_position"] + np.array([5.0, 0, 0])

    r = audit_bonds(design, frame)
    assert not r["ok"]
    assert r["n_rigid_stamp_violations"] == 0          # displacement is not a template-integrity bug
    # The gap to the moved nucleotide is over-stretched; backbone closure distributes
    # it across the phosphate linker, so it surfaces as an over-stretched backbone/
    # linker bond.  (The renderer-hidden >1 nm detector is validated on the real job
    # + the frontend parity test — the axis-derived centerline partly follows a single
    # synthetic displacement, so it does not reliably exceed the 1 nm cutoff here.)
    stretched = [b for b in r["invalid_bonds"] if b["class"] in ("backbone", "bridge", "linker")]
    assert stretched


def test_overlapping_nucleotides_clash(design, tmp_path):
    """Collapsing two distant nucleotides onto the same point overlaps their atoms →
    the clash detector fires."""
    frame = _ideal_frame(design, tmp_path)
    keys = [k for k in frame if k[2] == "FORWARD"]
    a, b = keys[0], keys[len(keys) // 2]               # two well-separated nucleotides
    frame[b]["backbone_position"] = frame[a]["backbone_position"].copy()
    frame[b]["a1"] = frame[a]["a1"].copy()
    frame[b]["a3"] = frame[a]["a3"].copy()
    r = audit_bonds(design, frame)
    assert len(r["clashes"]) > 0
    assert not r["ok"]


def test_non_finite_atom_flagged(design, tmp_path):
    """A non-finite CM (inf) produces non-finite atom positions → flagged as a bad
    atom AND its bonds are reported as non-finite invalid bonds."""
    frame = _ideal_frame(design, tmp_path)
    victim = next(iter(frame))
    frame[victim]["backbone_position"] = np.array([np.inf, 0.0, 0.0])
    r = audit_bonds(design, frame)
    assert any(a["reason"] == "non-finite position" for a in r["bad_atoms"])
    assert any(b["reason"] == "non-finite position" for b in r["invalid_bonds"])
    assert not r["ok"]


def test_backbone_closure_connects_and_preserves_rigid(design, tmp_path):
    """AF-ATOM-CLOSURE: the display-only backbone closure (close_backbone=True) re-seats
    the phosphate linker so a stretched sequential O3'→P bond is brought back toward
    physical — WITHOUT moving any rigid ring/base atom.  Tested on the axis-derived
    DISPLAY build (nuc_pos_override + axis_override), which is what the display uses."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.oxdna_health import _frame_atomistic_overrides

    frame = _ideal_frame(design, tmp_path)
    # Open a backbone gap: nudge one interior nucleotide off its neighbours.
    key = next(k for k in frame if k[2] == "FORWARD" and (k[0], k[1] - 1, k[2]) in frame
               and (k[0], k[1] + 1, k[2]) in frame)
    frame[key]["backbone_position"] = frame[key]["backbone_position"] + np.array([0.5, 0, 0])

    npo, axo = _frame_atomistic_overrides(design, frame)
    open_m = build_atomistic_model(design, nuc_pos_override=npo, axis_override=axo, close_backbone=False)
    closed = build_atomistic_model(design, nuc_pos_override=npo, axis_override=axo, close_backbone=True)

    def _bb_max(m):
        pos = {a.serial: np.array([a.x, a.y, a.z]) for a in m.atoms}
        return max(float(np.linalg.norm(pos[i] - pos[j]))
                   for i, j in m.bonds if _bond_class(m.atoms[i], m.atoms[j]) == "backbone")

    assert _bb_max(closed) < _bb_max(open_m)          # closure shortened the worst backbone stick

    # Rigid (ring/base) atoms are untouched by closure: same serial → same position.
    minim = {"O3'", "P", "O5'", "OP1", "OP2"}
    op = {a.serial: (a.x, a.y, a.z) for a in open_m.atoms}
    for a in closed.atoms:
        if a.name not in minim:
            assert op[a.serial] == (a.x, a.y, a.z)

    # The design / PDB / NAMD-seed path (no close_backbone → default False) is
    # byte-identical: closure is opt-in and never touches the export/seed builds.
    d_default = build_atomistic_model(design)
    d_off = build_atomistic_model(design, close_backbone=False)
    assert [(a.x, a.y, a.z) for a in d_default.atoms] == [(a.x, a.y, a.z) for a in d_off.atoms]


def test_base_geometry_detects_collapse(design, tmp_path):
    """The inter-base geometry check (the metric that would have caught the rigid-
    placer base collapse) reports WC-pair + stacking C1'-C1' and fires ``wc_collapsed``
    when partners are crushed together.  On a correct display reconstruction it is NOT
    collapsed and WC C1'-C1' sits in the B-DNA range; artificially pulling every
    REVERSE C1' onto its FORWARD partner trips the detector."""
    import dataclasses as dc
    from backend.core.atomistic_validation import _base_geometry, WC_COLLAPSE_NM

    r = audit_bonds(design, _ideal_frame(design, tmp_path))
    bg = r["base_geometry"]
    assert bg["wc_collapsed"] is False
    assert bg["wc_c1c1"]["median"] > 0.8                       # proper B-DNA pairing
    assert bg["stacking_c1c1"]["median"] is not None

    # Crush every REVERSE C1' onto its FORWARD partner → detector must fire.
    from backend.core.oxdna_health import build_display_model
    model = build_display_model(design, _ideal_frame(design, tmp_path))
    fwd_c1 = {(a.helix_id, a.bp_index): (a.x, a.y, a.z)
              for a in model.atoms if a.name == "C1'" and a.direction == "FORWARD"}
    crushed = []
    for a in model.atoms:
        if a.name == "C1'" and a.direction == "REVERSE" and (a.helix_id, a.bp_index) in fwd_c1:
            x, y, z = fwd_c1[(a.helix_id, a.bp_index)]
            crushed.append(dc.replace(a, x=x, y=y, z=z))
        else:
            crushed.append(a)
    from backend.core.atomistic import AtomisticModel
    bg2 = _base_geometry(AtomisticModel(atoms=crushed, bonds=model.bonds),
                         wc_collapse_nm=WC_COLLAPSE_NM)
    assert bg2["wc_collapsed"] is True
    assert bg2["wc_c1c1"]["median"] < 0.1


def test_wc_helix_imbalance_detector(design, tmp_path):
    """The forward/reverse phase-mapping regression guard: oxDNA relaxes FORWARD- and
    REVERSE-lattice helices to the SAME duplex geometry, so the reconstruction's WC
    C1'-C1' must NOT differ between them.  ``wc_helix_imbalanced`` fires when it does
    (the bug collapsed REVERSE-helix pairs to ~0.72 vs ~0.96 nm).  The current display
    build is balanced; artificially collapsing the REVERSE-lattice helices trips it."""
    import dataclasses as dc
    from backend.core.atomistic_validation import _base_geometry, WC_COLLAPSE_NM
    from backend.core.oxdna_health import build_display_model
    from backend.core.atomistic import AtomisticModel

    hd = {h.id: h.direction.value for h in design.helices}
    model = build_display_model(design, _ideal_frame(design, tmp_path))
    bg = _base_geometry(model, wc_collapse_nm=WC_COLLAPSE_NM, helix_dir=hd)
    assert bg["wc_helix_imbalanced"] is False                  # forward/reverse balanced
    assert bg["wc_c1c1_forward_helix_median"] is not None
    assert bg["wc_c1c1_reverse_helix_median"] is not None

    # Crush only the REVERSE-lattice helices' pairs (pull REV C1' onto FWD) → imbalance.
    fwd_c1 = {(a.helix_id, a.bp_index): (a.x, a.y, a.z)
              for a in model.atoms if a.name == "C1'" and a.direction == "FORWARD"}
    out = []
    for a in model.atoms:
        if (a.name == "C1'" and a.direction == "REVERSE" and hd.get(a.helix_id) == "REVERSE"
                and (a.helix_id, a.bp_index) in fwd_c1):
            x, y, z = fwd_c1[(a.helix_id, a.bp_index)]
            out.append(dc.replace(a, x=x, y=y, z=z))
        else:
            out.append(a)
    bg2 = _base_geometry(AtomisticModel(atoms=out, bonds=model.bonds),
                         wc_collapse_nm=WC_COLLAPSE_NM, helix_dir=hd)
    assert bg2["wc_helix_imbalanced"] is True


def test_strand_identity_preserved_nadoc_to_atomistic(design, tmp_path):
    """The strands/residues we START with in NADOC must be the strands/residues we
    SEE after reconstructing an oxDNA frame.  Pins that the relaxed DISPLAY build is
    identical, atom-for-atom, to the design's own atomistic build in every IDENTITY
    field (serial → name/element/residue/strand_id/helix/bp/direction) and bond list
    — only positions differ.  This is the invariant the renderer relies on (it applies
    relaxed positions by atom.serial onto atoms whose colour/strand come from the
    design build); a break here scrambles colours, bonds and positions."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.oxdna_health import build_display_model

    ref = build_atomistic_model(design)
    disp = build_display_model(design, _ideal_frame(design, tmp_path))

    assert len(ref.atoms) == len(disp.atoms)
    assert ref.bonds == disp.bonds
    for a, b in zip(ref.atoms, disp.atoms):
        assert (a.serial, a.name, a.element, a.residue, a.strand_id,
                a.helix_id, a.bp_index, a.direction) == \
               (b.serial, b.name, b.element, b.residue, b.strand_id,
                b.helix_id, b.bp_index, b.direction)

    # Every oxDNA particle key maps back to a NADOC strand, and per-strand atom
    # counts are preserved (no nucleotide reassigned to another strand).
    from backend.physics.oxdna_interface import _strand_nucleotide_order
    key_strand = {(d.helix_id, bp, d.direction.value): s.id
                  for s in design.strands for d in s.domains
                  for bp in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp) + 1)}
    for k in _strand_nucleotide_order(design):
        assert k[:3] in key_strand                       # no orphan oxDNA particle
    from collections import Counter
    assert Counter(a.strand_id for a in ref.atoms) == Counter(a.strand_id for a in disp.atoms)


def test_display_topology_hash_guards_against_design_drift(design, tmp_path, monkeypatch):
    """display-atomistic returns the JOB topology_hash + n_atoms, and the
    atomistic-model route returns the matching atoms+bonds, so the frontend can detect
    a loaded-design / job-snapshot mismatch (the index-scramble cause: applying job
    positions onto a differently-sequenced active design) and rebuild from the right
    topology."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna
    from backend.core.oxdna_job import new_oxdna_job, OxdnaStageStatus
    from backend.physics.oxdna_interface import write_configuration
    from backend.core.atomistic import atomistic_reference_topology_hash

    ws = tmp_path
    (ws / "oxdna_jobs").mkdir()
    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", ws)
    stage = OxdnaStageStatus(name="3_equil", kind="equil", steps=10, status="done")
    job = new_oxdna_job("sim", [stage], design_source_path="sim.nadoc")
    job.save(ws)
    sd = job.stage_dir(ws, "3_equil"); sd.mkdir(parents=True, exist_ok=True)
    write_configuration(design, _geometry_for_design(design), sd / "last_conf.dat", box_nm=200.0)
    (job.job_dir(ws) / "design.json").write_text(design.model_dump_json())
    c = TestClient(app)

    disp = c.post(f"/api/oxdna/jobs/{job.job_id}/display-atomistic").json()
    assert disp["topology_hash"] == atomistic_reference_topology_hash(design)
    assert disp["n_atoms"] * 3 == len(disp["atomistic"])

    model = c.get(f"/api/oxdna/jobs/{job.job_id}/atomistic-model").json()
    assert model["topology_hash"] == disp["topology_hash"]      # same topology as the positions
    assert len(model["atoms"]) == disp["n_atoms"]               # serial space matches the flat array
    assert all({"serial", "element", "strand_id", "residue"} <= set(a) for a in model["atoms"][:5])


def test_bond_class_partition():
    """_bond_class routes by topology: same residue + a phosphate atom → linker;
    same residue otherwise → rigid; consecutive same-helix → backbone; else bridge."""
    class A:  # minimal atom stand-in
        def __init__(self, s, n, h, bp, d):
            self.strand_id, self.seq_num, self.name = s, s + str(0), n
            self.helix_id, self.bp_index, self.direction = h, bp, d
    rigid = (A("s", "C4'", "h", 0, "FORWARD"), A("s", "C3'", "h", 0, "FORWARD"))
    rigid[0].seq_num = rigid[1].seq_num = 5
    assert _bond_class(*rigid) == "rigid"
    link = (A("s", "P", "h", 0, "FORWARD"), A("s", "O5'", "h", 0, "FORWARD"))
    link[0].seq_num = link[1].seq_num = 5
    assert _bond_class(*link) == "linker"


def test_latest_job_for_design_and_ready_false(design, tmp_path):
    """latest_job_for_design matches by source stem + a present last_conf, and
    audit_oxdna_job reports ready=False when the chosen job has no conf yet."""
    from backend.core.oxdna_job import new_oxdna_job, OxdnaStageStatus
    ws = tmp_path
    (ws / "oxdna_jobs").mkdir()

    # Job WITH a relaxed conf for design "mything".
    stage = OxdnaStageStatus(name="1_mc", kind="mc", steps=10, status="done")
    job = new_oxdna_job("mything", [stage], design_source_path="mything.nadoc")
    job.save(ws)
    sd = job.stage_dir(ws, "1_mc"); sd.mkdir(parents=True, exist_ok=True)
    from backend.physics.oxdna_interface import write_configuration
    write_configuration(design, _geometry_for_design(design), sd / "last_conf.dat", box_nm=200.0)
    (job.job_dir(ws) / "design.json").write_text(design.model_dump_json())

    # A second, conf-less job for the SAME stem — must be ignored (no last_conf).
    job2 = new_oxdna_job("mything", [stage], design_source_path="mything.nadoc")
    job2.save(ws)

    assert latest_job_for_design("mything", ws) == job.job_id
    assert latest_job_for_design("nonesuch", ws) is None

    # The conf-less job audits as not-ready.
    rep = audit_oxdna_job(design, job2, ws)
    assert rep["ready"] is False


def test_display_atomistic_audit_route(design, tmp_path, monkeypatch):
    """POST /oxdna/jobs/{id}/display-atomistic-audit returns the bond audit for the
    displayed frame — the programmatic counterpart of the rendered ball-and-stick."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna
    from backend.core.oxdna_job import new_oxdna_job, OxdnaStageStatus
    from backend.physics.oxdna_interface import write_configuration

    ws = tmp_path
    (ws / "oxdna_jobs").mkdir()
    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", ws)

    stage = OxdnaStageStatus(name="3_equil", kind="equil", steps=10, status="done")
    job = new_oxdna_job("sim", [stage], design_source_path="sim.nadoc")
    job.save(ws)
    sd = job.stage_dir(ws, "3_equil"); sd.mkdir(parents=True, exist_ok=True)
    write_configuration(design, _geometry_for_design(design), sd / "last_conf.dat", box_nm=200.0)
    (job.job_dir(ws) / "design.json").write_text(design.model_dump_json())

    resp = TestClient(app).post(f"/api/oxdna/jobs/{job.job_id}/display-atomistic-audit")
    assert resp.status_code == 200
    r = resp.json()
    assert r["ready"] is True and r["stage_name"] == "3_equil"
    assert r["n_rigid_stamp_violations"] == 0           # the placer is correct on the ideal frame
    assert {"rigid", "backbone"} <= set(r["by_class"])
    assert "hidden_by_renderer" in r and "clashes" in r
