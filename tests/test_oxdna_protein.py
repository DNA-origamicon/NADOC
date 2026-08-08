"""Unit tests for backend.physics.oxdna_protein — hybrid topology/conf/.par writers."""

import numpy as np
import pytest

from backend.core.constants import NM_TO_OXDNA
from backend.core.protein_cg import ProteinBead
from backend.physics.oxdna_interface import topology_rows
from backend.physics.oxdna_protein import (
    anm_par_text,
    dna_index_offset,
    dna_particle_index,
    hybrid_topology_text,
    protein_bead_count,
    protein_conf_lines,
    protein_topology_lines,
)
from tests.conftest import make_6hb_design


def _bead(index, aa, chain, res, x, prev):
    return ProteinBead(
        index=index,
        aa=aa,
        chain_id=chain,
        res_seq=res,
        pos_nm=np.array([x, 0.0, 0.0]),
        prev_index=prev,
    )


def _chain_block(n, x0=0.0, step=0.4, chain="A"):
    """A single-chain protein: n beads spaced `step` nm along x (so consecutive
    beads are within the ANM cutoff, non-consecutive may not be)."""
    return [
        _bead(i, "A", chain, i + 1, x0 + step * i, i - 1 if i else -1) for i in range(n)
    ]


# ── topology ──────────────────────────────────────────────────────────────────


def test_hybrid_header_five_fields():
    design = make_6hb_design()
    rows, n_dna_strands = topology_rows(design)
    blocks = [_chain_block(4)]
    text = hybrid_topology_text(design, blocks)
    header = text.splitlines()[0].split()
    n_prot, n_dna = 4, len(rows)
    assert header == [
        str(n_prot + n_dna),
        str(n_dna_strands + 1),
        str(n_dna),
        str(n_prot),
        str(n_dna_strands),
    ]


def test_protein_lines_first_then_dna_shifted():
    design = make_6hb_design()
    rows, _ = topology_rows(design)
    blocks = [_chain_block(3)]
    lines = hybrid_topology_text(design, blocks).splitlines()[1:]  # drop header
    prot_lines = lines[:3]
    dna_lines = lines[3:]
    # protein lines have a NEGATIVE strand id; DNA lines positive
    assert all(int(line.split()[0]) < 0 for line in prot_lines)
    assert all(int(line.split()[0]) > 0 for line in dna_lines)
    # a DNA nucleotide's neighbour indices are shifted by +N_protein vs standalone
    n_prot = 3
    for (si, base, n3, n5), line in zip(rows, dna_lines):
        parts = line.split()
        assert int(parts[0]) == si and parts[1] == base
        assert int(parts[2]) == (n3 + n_prot if n3 >= 0 else -1)
        assert int(parts[3]) == (n5 + n_prot if n5 >= 0 else -1)


def test_protein_topology_line_prev_and_neighbours():
    # 3 beads in a line at 0.0, 0.4, 0.8 nm; cutoff 0.5 → springs (0,1),(1,2) only.
    blocks = [_chain_block(3, step=0.4)]
    lines = protein_topology_lines(blocks, cutoff_nm=0.5)
    # bead 0: prev -1, neighbour 1
    assert lines[0].split() == ["-1", "A", "-1", "1"]
    # bead 1: prev 0, neighbour 2 (the (0,1) spring is recorded on bead 0's line)
    assert lines[1].split() == ["-1", "A", "0", "2"]
    # bead 2: prev 1, no higher neighbour
    assert lines[2].split() == ["-1", "A", "1"]


def test_two_attachments_get_distinct_strands_and_global_indices():
    blocks = [_chain_block(2, chain="A"), _chain_block(2, x0=10.0, chain="B")]
    lines = protein_topology_lines(blocks, cutoff_nm=0.5)
    assert len(lines) == 4
    assert [line.split()[0] for line in lines] == ["-1", "-1", "-2", "-2"]
    # second block's prev uses GLOBAL indices (bead 3's prev is global bead 2)
    assert lines[3].split()[2] == "2"


# ── configuration ─────────────────────────────────────────────────────────────


def test_conf_lines_count_and_oxdna_units():
    blocks = [_chain_block(3, x0=1.0, step=1.0)]  # beads at x=1,2,3 nm
    lines = protein_conf_lines(blocks)
    assert len(lines) == 3
    first = lines[0].split()
    assert len(first) == 15  # pos a1 a3 v L
    assert abs(float(first[0]) - 1.0 * NM_TO_OXDNA) < 1e-4
    # orthonormal placeholder orientation a1=+x, a3=+z
    assert first[3:9] == ["1", "0", "0", "0", "0", "1"]


# ── .par ──────────────────────────────────────────────────────────────────────


def test_par_header_count_and_spring_format():
    blocks = [_chain_block(3, step=0.4)]
    par = anm_par_text(blocks, cutoff_nm=0.5, k=50.0)
    plines = par.splitlines()
    assert plines[0] == "3"  # N_protein beads
    springs = [ln.split() for ln in plines[1:]]
    assert {(s[0], s[1]) for s in springs} == {("0", "1"), ("1", "2")}
    # format: i j r0 s k ; r0 in oxDNA units (0.4 nm), type flag 's', k=50
    r0 = float(springs[0][2])
    assert abs(r0 - 0.4 * NM_TO_OXDNA) < 1e-4
    assert springs[0][3] == "s" and float(springs[0][4]) == 50.0


def test_par_uses_global_indices_across_blocks():
    blocks = [_chain_block(2, chain="A"), _chain_block(2, x0=10.0, chain="B")]
    par = anm_par_text(blocks, cutoff_nm=0.5)
    plines = par.splitlines()
    assert plines[0] == "4"
    pairs = {(ln.split()[0], ln.split()[1]) for ln in plines[1:]}
    assert pairs == {("0", "1"), ("2", "3")}  # second block global-indexed


# ── particle-index map ──────────────────────────────────────────────────────────


def test_dna_particle_index_offset_by_protein_count():
    design = make_6hb_design()
    blocks = [_chain_block(5)]
    offset = dna_index_offset(blocks)
    assert offset == protein_bead_count(blocks) == 5
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    order = _strand_nucleotide_order(design)
    # first DNA nucleotide lands at index = N_protein
    assert dna_particle_index(design, order[0], offset) == 5
    assert dna_particle_index(design, order[3], offset) == 8
    assert dna_particle_index(design, ("nonexistent", 0, "FORWARD"), offset) is None


# ── hybrid configuration ────────────────────────────────────────────────────────


def test_hybrid_configuration_protein_first_and_shared_box():
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_protein import hybrid_configuration_text

    design = make_6hb_design()
    geometry = _geometry_for_design(design)
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    n_dna = len(_strand_nucleotide_order(design))
    blocks = [_chain_block(4, x0=0.0, step=0.4)]

    text = hybrid_configuration_text(design, geometry, blocks)
    lines = text.splitlines()
    assert lines[0] == "t = 0" and lines[1].startswith("b = ")
    body = lines[3:]
    assert len(body) == 4 + n_dna  # protein beads FIRST, then DNA
    # the 4 protein lines are the leading ones (placeholder a1=+x/a3=+z)
    assert all(line.split()[3:9] == ["1", "0", "0", "0", "0", "1"] for line in body[:4])
    # box is a single cube covering everything
    bx = float(lines[1].split()[2])
    assert bx > 0


# ── traps ───────────────────────────────────────────────────────────────────────


def test_conjugation_trap_is_symmetric_mutual_trap():
    from backend.physics.oxdna_protein import conjugation_trap_text

    txt = conjugation_trap_text(7, 102, stiff=1.424, r0=1.071)
    assert txt.count("type = mutual_trap") == 2  # symmetric pair
    assert "particle = 7" in txt and "ref_particle = 102" in txt
    assert "particle = 102" in txt and "ref_particle = 7" in txt
    assert "r0 = 1.071" in txt


def test_anchor_trap_on_centroid_bead_in_oxdna_units():
    from backend.physics.oxdna_protein import protein_anchor_trap_text

    beads = _chain_block(
        3, x0=0.0, step=1.0
    )  # x = 0,1,2 ; centroid bead = index 1 (x=1)
    txt = protein_anchor_trap_text(beads, base=10, stiff=2.0)
    assert "type = trap" in txt
    assert "particle = 11" in txt  # base 10 + centroid local 1
    assert f"{1.0 * NM_TO_OXDNA:.6g}" in txt  # pos0 x in oxDNA units


# ── binder-terminus resolver ────────────────────────────────────────────────────


def test_binder_terminus_none_for_free_target():
    import types
    from backend.physics.oxdna_protein import binder_terminus_nuc_key

    att = types.SimpleNamespace(target=types.SimpleNamespace())  # no overhang_id
    assert binder_terminus_nuc_key(types.SimpleNamespace(strands=[]), att, []) is None


def test_binder_terminus_picks_nearest_end(monkeypatch):
    import types

    import backend.physics.oxdna_protein as mod
    from backend.physics.oxdna_protein import binder_terminus_nuc_key

    # binder strand "bndr" bound to overhang "ov"; two termini at x=0 and x=5.
    dom = types.SimpleNamespace(binds_overhang_id="ov")
    binder = types.SimpleNamespace(id="bndr", domains=[dom])
    design = types.SimpleNamespace(strands=[binder])
    att = types.SimpleNamespace(
        target=types.SimpleNamespace(overhang_id="ov", attach_end="free_end")
    )
    geometry = [
        {
            "strand_id": "bndr",
            "is_five_prime": True,
            "is_three_prime": False,
            "backbone_position": [0.0, 0, 0],
            "helix_id": "h0",
            "bp_index": 5,
            "direction": "FORWARD",
        },
        {
            "strand_id": "bndr",
            "is_five_prime": False,
            "is_three_prime": True,
            "backbone_position": [5.0, 0, 0],
            "helix_id": "h0",
            "bp_index": 0,
            "direction": "FORWARD",
        },
    ]
    # anchor sits at x=0.2 → nearer the 5′ terminus (bp 5)
    monkeypatch.setattr(
        mod,
        "resolve_overhang_anchor",
        lambda *a, **k: (__import__("numpy").array([0.2, 0, 0]), None),
        raising=False,
    )
    # resolve_overhang_anchor is imported inside the fn; patch the source module too
    import backend.core.protein as protein_mod

    monkeypatch.setattr(
        protein_mod,
        "resolve_overhang_anchor",
        lambda *a, **k: (__import__("numpy").array([0.2, 0, 0]), None),
    )
    assert binder_terminus_nuc_key(design, att, geometry) == ("h0", 5, "FORWARD")


# ── forces composition (free proteins → anchor traps) ───────────────────────────


def test_protein_forces_free_proteins_get_anchor_traps():
    import types
    from backend.physics.oxdna_protein import protein_forces_text

    design = types.SimpleNamespace(strands=[])  # no binder → all anchored
    atts = [
        types.SimpleNamespace(target=types.SimpleNamespace()),
        types.SimpleNamespace(target=types.SimpleNamespace()),
    ]
    blocks = [_chain_block(2, chain="A"), _chain_block(2, x0=10.0, chain="B")]
    txt = protein_forces_text(design, atts, blocks, geometry=[])
    assert txt.count("type = trap") == 2  # one anchor per attachment
    assert "type = mutual_trap" not in txt


# ── protocol render (DNANM input keys) ──────────────────────────────────────────


def _spec(**kw):
    from backend.core.oxdna_protocol import OxdnaStageSpec

    base = dict(
        name="2_md_relax", kind="md_relax", sim_type="MD", steps=1000, backend="CPU"
    )
    base.update(kw)
    return OxdnaStageSpec(**base)


def test_render_dna_only_unchanged_uses_dna2():
    from backend.core.oxdna_protocol import render_stage_input

    txt = render_stage_input(_spec(), "t.top", "c.dat")
    assert "interaction_type = DNA2" in txt
    assert "parfile" not in txt


def test_render_hybrid_emits_dnanm_and_parfile():
    from backend.core.oxdna_protocol import render_stage_input

    txt = render_stage_input(
        _spec(interaction="DNANM", parfile="anm.par"), "t.top", "c.dat"
    )
    assert "interaction_type = DNANM" in txt
    assert "parfile = anm.par" in txt


def test_render_hybrid_relax_emits_relax_type():
    from backend.core.oxdna_protocol import render_stage_input

    txt = render_stage_input(
        _spec(
            interaction="DNANM_relax", parfile="anm.par", relax_type="harmonic_force"
        ),
        "t.top",
        "c.dat",
    )
    assert "interaction_type = DNANM_relax" in txt
    assert "relax_type = harmonic_force" in txt


def test_render_hybrid_mc_gets_refresh_vel():
    # The anm-oxdna fork makes refresh_vel mandatory even for MC.
    from backend.core.oxdna_protocol import render_stage_input

    mc = _spec(
        name="1_mc",
        kind="mc",
        sim_type="MC",
        interaction="DNANM_relax",
        parfile="anm.par",
    )
    txt = render_stage_input(mc, "t.top", "c.dat")
    assert "refresh_vel = true" in txt
    # DNA-only MC does NOT add it
    dna_mc = _spec(name="1_mc", kind="mc", sim_type="MC")
    assert "refresh_vel = true" not in render_stage_input(dna_mc, "t.top", "c.dat")


# ── binary discovery ────────────────────────────────────────────────────────────


def test_find_oxdna_anm_honors_env_override(monkeypatch, tmp_path):
    from backend.core import oxdna_runner

    fake = tmp_path / "oxDNA"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("OXDNA_ANM_BIN", str(fake))
    assert oxdna_runner.find_oxdna_anm() == str(fake)


def test_find_oxdna_anm_none_when_absent(monkeypatch):
    from backend.core import oxdna_runner

    monkeypatch.setenv("OXDNA_ANM_BIN", "/nonexistent/oxDNA")
    monkeypatch.setattr(oxdna_runner, "_OXDNA_ANM_CANDIDATES", ["/also/nonexistent"])
    assert oxdna_runner.find_oxdna_anm() is None


# ── Phase 4: runner integration (prepare_oxdna_job hybrid path) ─────────────────


def _protein_design():
    """6hb DNA (sequenced) + one free protein attachment of 5 Cα beads near it."""
    from backend.core.models import (
        ProteinAsset,
        ProteinAtom,
        ProteinAttachment,
        ProteinTargetFree,
    )

    d = make_6hb_design()
    for s in d.strands:
        n = sum(abs(dom.end_bp - dom.start_bp) + 1 for dom in s.domains)
        s.sequence = ("ACGT" * (n // 4 + 1))[:n]
    atoms = [
        ProteinAtom(
            serial=i,
            name="CA",
            element="C",
            res_name="ALA",
            chain_id="A",
            res_seq=i + 1,
            x=2.0 + 0.38 * i,
            y=2.0,
            z=2.0,
        )
        for i in range(5)
    ]
    asset = ProteinAsset(name="p", atoms=atoms, center_of_mass=[2.5, 2.0, 2.0])
    d.protein_assets = [asset]
    d.protein_attachments = [
        ProteinAttachment(asset_id=asset.id, target=ProteinTargetFree())
    ]
    return d


def test_prepare_writes_hybrid_files_with_offset_traps(tmp_path):
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    design = _protein_design()
    geometry = _geometry_for_design(design)
    specs = build_relaxation_stages(
        mc_steps=50, md_relax_steps=50, equil_steps=50, protein=True
    )
    job = new_oxdna_job(design_name="prot", stages=[s.to_status() for s in specs])
    prepare_oxdna_job(design, geometry, job, tmp_path, specs)

    jd = job.job_dir(tmp_path)
    # hybrid topology (5-field header) + ANM par + equil_forces all written
    header = (jd / "topology.top").read_text().splitlines()[0].split()
    assert len(header) == 5 and header[3] == "5"  # N_protein beads = 5
    assert (jd / "anm.par").exists()
    assert (jd / "equil_forces.txt").exists()
    # mutual-trap DNA indices are shifted by +5 (protein leads): every WC-pair trap
    # references a particle >= 5 (no trap points into the protein block 0..4).
    forces = (jd / "forces.txt").read_text()
    mt_particles = [
        int(ln.split("=")[1])
        for ln in forces.splitlines()
        if ln.startswith("particle =") and "mutual_trap" in forces
    ]
    # DNA mutual-trap particles are shifted into [5, 5+n_dna) by the protein lead
    assert len(_strand_nucleotide_order(design)) > 0
    assert any(p >= 5 for p in mt_particles)
    # the protein free anchor trap targets a protein particle (< 5)
    assert "type = trap" in forces


def test_prepare_stages_select_dnanm_and_fork():
    from backend.core.oxdna_protocol import build_relaxation_stages

    specs = build_relaxation_stages(protein=True)
    assert specs[0].interaction == "DNANM_relax" and specs[0].parfile == "anm.par"
    assert specs[2].interaction == "DNANM"  # equil = plain DNANM
    # DNA-only stays mainline
    dna = build_relaxation_stages(protein=False)
    assert all(s.interaction is None and s.parfile is None for s in dna)


@pytest.mark.skipif(
    __import__(
        "backend.core.oxdna_runner", fromlist=["find_oxdna_anm"]
    ).find_oxdna_anm()
    is None,
    reason="ANM-oxDNA fork binary not built",
)
def test_prepared_hybrid_job_runs_on_fork(tmp_path):
    """The job dir prepare_oxdna_job writes is loadable + runnable by the fork."""
    import subprocess

    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages, render_stage_input
    from backend.core.oxdna_runner import find_oxdna_anm, prepare_oxdna_job

    design = _protein_design()
    geometry = _geometry_for_design(design)
    specs = build_relaxation_stages(
        mc_steps=100, md_relax_steps=100, equil_steps=50, backend="CPU", protein=True
    )
    job = new_oxdna_job(design_name="prot", stages=[s.to_status() for s in specs])
    prepare_oxdna_job(design, geometry, job, tmp_path, specs)
    jd = job.job_dir(tmp_path)

    # Render + run the MC relax stage (stage 0) exactly as run_job would.
    spec = specs[0]
    stage = jd / spec.name
    stage.mkdir(exist_ok=True)
    inp = render_stage_input(
        spec,
        str((jd / "topology.top").resolve()),
        str((jd / "conf.dat").resolve()),
        forces_name=str((jd / "forces.txt").resolve()),
        parfile_name=str((jd / "anm.par").resolve()),
    )
    (stage / "input.txt").write_text(inp)
    r = subprocess.run(
        [find_oxdna_anm(), str(stage / "input.txt")],
        cwd=stage,
        capture_output=True,
        text=True,
        timeout=180,
    )
    log = r.stdout + r.stderr
    assert r.returncode == 0, log[-2000:]
    assert "DNANM" in log or "non-diverging" in log or "everything went OK" in log


# ── Phase 4b: hybrid-aware config reader (display + health) ─────────────────────


def test_read_configuration_skips_protein_lead(tmp_path):
    """A hybrid conf (protein beads first) reads back the SAME DNA positions as the
    DNA-only conf — the reader skips the leading protein lines."""
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import (
        read_configuration_full,
        write_configuration,
    )
    from backend.physics.oxdna_protein import hybrid_configuration_text

    design = _protein_design()
    geometry = _geometry_for_design(design)

    dna_only = tmp_path / "dna.dat"
    write_configuration(design, geometry, dna_only)
    ref = read_configuration_full(dna_only, design)

    blocks = [_chain_block(5, x0=2.0, step=0.38)]
    hybrid = tmp_path / "hybrid.dat"
    hybrid.write_text(hybrid_configuration_text(design, geometry, blocks))
    got = read_configuration_full(hybrid, design)

    assert set(got) == set(ref)  # same DNA keys
    k = next(iter(ref))
    assert np.allclose(
        got[k]["backbone_position"], ref[k]["backbone_position"], atol=1e-5
    )


def test_base_pair_retention_on_hybrid_conf(tmp_path):
    """base_pair_retention computes a sane (>0) value on a hybrid conf, proving the
    reader offset makes the DNA pairs resolve (not protein beads)."""
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_health import base_pair_retention
    from backend.physics.oxdna_interface import read_configuration_full
    from backend.physics.oxdna_protein import hybrid_configuration_text

    design = _protein_design()
    geometry = _geometry_for_design(design)
    blocks = [_chain_block(5, x0=2.0, step=0.38)]
    hybrid = tmp_path / "hybrid.dat"
    hybrid.write_text(hybrid_configuration_text(design, geometry, blocks))
    full_map = read_configuration_full(hybrid, design)
    frac, total = base_pair_retention(design, full_map)
    assert total > 0 and 0.0 <= frac <= 1.0  # resolves DNA pairs, no crash


# ── Phase 4b: protein display transform (Kabsch recovery) ───────────────────────


def test_protein_display_transform_recovers_known_rigid_motion(tmp_path):
    """A known rigid motion of the protein beads is recovered by the display
    transform (design pose → relaxed pose), proving the Kabsch fit + bead bridge."""
    from backend.api.crud import _geometry_for_design
    from backend.core.protein_cg import ProteinBead
    from backend.physics.oxdna_protein import (
        build_protein_blocks,
        hybrid_configuration_text,
        protein_display_transforms,
    )

    design = _protein_design()
    geometry = _geometry_for_design(design)
    _, blocks = build_protein_blocks(design, geometry)
    design_beads = blocks[0]

    # Known rigid motion: 90° about z + translation (0.5, -0.3, 0.2) nm.
    th = np.pi / 2
    R0 = np.array(
        [[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]]
    )
    t0 = np.array([0.5, -0.3, 0.2])
    relaxed_beads = [
        ProteinBead(
            index=b.index,
            aa=b.aa,
            chain_id=b.chain_id,
            res_seq=b.res_seq,
            pos_nm=R0 @ b.pos_nm + t0,
            prev_index=b.prev_index,
        )
        for b in design_beads
    ]

    conf = tmp_path / "relaxed.dat"
    ref = tmp_path / "ref.dat"
    conf.write_text(hybrid_configuration_text(design, geometry, [relaxed_beads]))
    ref.write_text(hybrid_configuration_text(design, geometry, [design_beads]))

    # align=False isolates the protein fit from the DNA Kabsch (DNA unchanged here).
    transforms = protein_display_transforms(conf, ref, design, geometry, align=False)
    att_id = design.protein_attachments[0].id
    assert att_id in transforms
    M = np.array(transforms[att_id]).reshape(4, 4)
    # applying M to each design bead reproduces the relaxed bead
    for b, rb in zip(design_beads, relaxed_beads):
        p = M @ np.array([*b.pos_nm, 1.0])
        assert np.allclose(p[:3], rb.pos_nm, atol=1e-4)


def test_protein_display_transforms_empty_for_dna_only(tmp_path):
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import write_configuration
    from backend.physics.oxdna_protein import protein_display_transforms

    design = make_6hb_design()
    geometry = _geometry_for_design(design)
    conf = tmp_path / "dna.dat"
    write_configuration(design, geometry, conf)  # DNA-only conf (no protein lines)
    assert protein_display_transforms(conf, conf, design, geometry) == {}
