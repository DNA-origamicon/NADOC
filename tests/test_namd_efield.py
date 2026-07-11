"""N1 — NAMD native electric field (``eFieldOn`` / ``eField``) oracle.

The bright line is NOT "the conf contains a block".  It is the PROPERTY that NAMD
applies to every nucleotide **exactly the shared cross-engine load** — the same
force-per-nucleotide ``field_pN`` along ``dir`` that oxDNA puts on each bead
(``string`` force), LAMMPS puts on each bead (``fix addforce``) and CanDo puts on each
duplex axis node (×2 backbones, ``FEM_FIELD_CHARGES_PER_NODE``).

NAMD's guarantee is ``F_i = q_i · eField`` (force in kcal·mol⁻¹·Å⁻¹, ``eField`` in
kcal·mol⁻¹·Å⁻¹·e⁻¹, per atom, using the atom's CHARMM partial charge).  The net force on
a nucleotide residue is therefore ``(Σ_i q_i) · eField = q_res · eField``.  So the load
is proven comparable by two facts, neither of which needs a GPU:

  (a) the emitted ``eField`` vector inverts to ``field_pN · dir̂`` under ``q_res = −1 e``
      (unit conversion + the antiparallel sign of a negative backbone charge), and
  (b) the REAL psfgen-built PSF gives every INTERNAL DNA residue a net charge of exactly
      −1.000 e — so ``q_res`` is not a fiction but the force field's own value
      (the same one ``namd_solvate._count_dna_charge`` uses to neutralise the box).

(a) is fast; (b) is slow (real psfgen).  Together they establish the *applied load*.

Measured, not assumed: psfgen's 5TER/3TER hydroxyl patches leave a strand's first residue
at −0.47 e and its last at −0.53 e (they sum to −1.00, one phosphate), so a strand of N
nucleotides carries −(N−1) e — its exact phosphate count.  NAMD therefore applies slightly
less TOTAL force than oxDNA's uniform per-bead ``field_pN``; that is NAMD being right and
oxDNA approximating, and the tests below pin both numbers so nobody "fixes" it later by
rescaling eField (which would corrupt the internal per-nucleotide load the engines share).

The remaining half of the bright line — the *response* — is the SLOW real-NAMD run below:
a DIFFERENTIAL pair of zero-temperature runs (field on vs field off) from the same
minimised structure with one strand fixed.  Differencing cancels every non-field force to
leading order, so the free strand's centre-of-mass displacement difference must lie ALONG
the requested direction with the magnitude ``½·(F_net/M)·t²`` predicted by the charges NAMD
actually carries — a real prediction NAMD can falsify, not a conf-text assertion.
"""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from backend.core.md_protocols import (
    KCAL_MOL_A_IN_PN,
    NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E,
    _min_conf,
    _segment_conf,
    build_remote_resume_conf,
    mgh_slow_release_segments,
    namd_efield_vector,
)
from tests.conftest import make_minimal_design

# ── helpers ───────────────────────────────────────────────────────────────────


def _first_spec():
    return mgh_slow_release_segments("demo")[1][0]


def _conf_efield_vector(text: str) -> tuple[float, float, float]:
    """Parse the ``eField x y z`` line back out of a conf."""
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "eField":
            return (float(parts[1]), float(parts[2]), float(parts[3]))
    raise AssertionError("no eField line in conf")


def _force_pn_on_nucleotide(efield_vec) -> np.ndarray:
    """Invert NAMD's own guarantee: F = q_res · eField, kcal·mol⁻¹·Å⁻¹ → pN."""
    return (
        NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E * np.asarray(efield_vec, dtype=float)
    ) * KCAL_MOL_A_IN_PN


# ── unit conversion: the load the field actually applies ──────────────────────


def test_unit_constant_matches_first_principles():
    """1 kcal·mol⁻¹·Å⁻¹ in pN, derived independently of the module."""
    expect = 4184.0 / 6.02214076e23 / 1e-10 * 1e12
    assert KCAL_MOL_A_IN_PN == pytest.approx(expect, rel=1e-12)
    assert KCAL_MOL_A_IN_PN == pytest.approx(69.4769, abs=1e-3)
    # A DNA nucleotide is one phosphate: the CHARMM net residue charge (see
    # namd_solvate._count_dna_charge, which counts exactly one P per nucleotide).
    assert NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E == -1.0


@pytest.mark.parametrize(
    "field",
    [None, {}, {"field_pN": 0.0, "dir": [0, 1, 0]}, {"field_pN": 5.0, "dir": [0, 0, 0]}],
)
def test_no_field_is_an_exact_no_op(field):
    """Absent / zero magnitude / zero direction → no field at all (RED guard)."""
    assert namd_efield_vector(field) is None


def test_efield_vector_applies_exactly_field_pn_per_nucleotide_along_dir():
    """THE ORACLE: NAMD's F = q·E on the emitted vector reproduces the shared load.

    This is the cross-engine equality — the very same ``field_pN`` per nucleotide that
    oxDNA applies per bead.  It also pins the SIGN: the backbone charge is negative, so
    the emitted eField must point ANTIPARALLEL to the requested force direction.
    """
    for dir_raw, field_pN in (
        ([0.0, 1.0, 0.0], 2.0),
        ([3.0, 4.0, 0.0], 7.5),  # non-unit direction → must be normalised
        ([-1.0, 0.0, 2.0], 0.13),
    ):
        vec = namd_efield_vector({"field_pN": field_pN, "dir": dir_raw})
        assert vec is not None
        dir_hat = np.asarray(dir_raw, float) / np.linalg.norm(dir_raw)

        force_pn = _force_pn_on_nucleotide(vec)
        # magnitude AND direction: the nucleotide is pushed along +dir with |F| = field_pN
        np.testing.assert_allclose(force_pn, field_pN * dir_hat, rtol=1e-9, atol=1e-12)

        # sign: negative charge ⇒ eField antiparallel to the force the user asked for
        assert float(np.dot(np.asarray(vec, float), dir_hat)) < 0.0


def test_efield_vector_is_linear_in_magnitude():
    a = np.asarray(namd_efield_vector({"field_pN": 1.0, "dir": [0, 0, 1]}), float)
    b = np.asarray(namd_efield_vector({"field_pN": 3.0, "dir": [0, 0, 1]}), float)
    np.testing.assert_allclose(b, 3.0 * a, rtol=1e-12)


def test_efield_accepts_the_persisted_force_pn_spelling():
    """oxDNA job records persist ``force_pN``; the descriptor uses ``field_pN``."""
    v1 = namd_efield_vector({"field_pN": 2.0, "dir": [0, 1, 0]})
    v2 = namd_efield_vector({"force_pN": 2.0, "dir": [0, 1, 0]})
    assert v1 == v2


# ── conf emission ─────────────────────────────────────────────────────────────


def test_segment_conf_emits_efield_only_with_a_field():
    spec = _first_spec()
    box = (100.0, 100.0, 100.0)
    field = {"field_pN": 2.0, "dir": [0.0, 1.0, 0.0]}

    with_field = _segment_conf(spec, "demo", box, False, field=field)
    assert "eFieldOn           on" in with_field
    np.testing.assert_allclose(
        _force_pn_on_nucleotide(_conf_efield_vector(with_field)),
        [0.0, 2.0, 0.0],
        atol=1e-9,
    )

    without = _segment_conf(spec, "demo", box, False)
    assert "eField" not in without


def test_min_conf_emits_efield_only_with_a_field():
    box = (100.0, 100.0, 100.0)
    field = {"field_pN": 1.5, "dir": [1.0, 0.0, 0.0]}

    with_field = _min_conf("demo_min", "demo", box, False, 4800, 0.5, field=field)
    assert "eFieldOn           on" in with_field
    np.testing.assert_allclose(
        _force_pn_on_nucleotide(_conf_efield_vector(with_field)), [1.5, 0.0, 0.0], atol=1e-9
    )

    without = _min_conf("demo_min", "demo", box, False, 4800, 0.5)
    assert "eField" not in without


def test_zero_field_conf_is_byte_identical_to_no_field():
    """A zero-magnitude field must not perturb the conf at all."""
    spec = _first_spec()
    box = (100.0, 100.0, 100.0)
    assert _segment_conf(spec, "demo", box, False, field={"field_pN": 0.0, "dir": [0, 1, 0]}) == (
        _segment_conf(spec, "demo", box, False)
    )


def test_remote_resume_preserves_the_field():
    """A mid-segment cluster resume must not silently drop the field."""
    spec = _first_spec()
    conf = _segment_conf(
        spec, "demo", (100.0, 100.0, 100.0), False,
        field={"field_pN": 2.0, "dir": [0.0, 1.0, 0.0]},
        anchors_file="restraints_anchors.pdb",
    )
    resumed = build_remote_resume_conf(
        conf, segment_name=spec.name, restart_step=100, total_steps=spec.steps
    )
    assert "eFieldOn           on" in resumed
    assert _conf_efield_vector(resumed) == _conf_efield_vector(conf)
    assert "fixedAtoms         on" in resumed


# ── production confs: the field (and its required anchors) must reach the run ──


def test_production_confs_carry_field_and_anchors():
    """A field is only physically meaningful in the unrestrained run.

    ``_conservative_production_conf`` / ``_seed_production_conf`` are hand-rolled writers
    that previously dropped BOTH the anchors and the field — an unanchored uniform force
    just streams the whole structure across the box (COM drift), so this is load-bearing,
    not cosmetic.
    """
    from backend.api.routes_md import (
        _conservative_production_conf,
        _seed_production_conf,
    )

    spec = _first_spec()
    box = (100.0, 100.0, 100.0)
    field = {"field_pN": 2.0, "dir": [0.0, 0.0, 1.0]}

    for text in (
        _conservative_production_conf(
            spec, "demo", box, False, anchors_file="restraints_anchors.pdb", field=field
        ),
        _seed_production_conf(
            spec, "demo", box, False, 100, anchors_file="restraints_anchors.pdb", field=field
        ),
    ):
        assert "fixedAtoms         on" in text
        assert "fixedAtomsFile     restraints_anchors.pdb" in text
        assert "eFieldOn           on" in text
        np.testing.assert_allclose(
            _force_pn_on_nucleotide(_conf_efield_vector(text)), [0.0, 0.0, 2.0], atol=1e-9
        )

    plain = _conservative_production_conf(spec, "demo", box, False)
    assert "eField" not in plain and "fixedAtoms" not in plain


# ── API guards: physics/engine facts, enforced before a job is ever prepared ───


def _post_create(**kw):
    from fastapi.testclient import TestClient

    from backend.api.main import app

    body = {"field": {"field_pN": 2.0, "dir": [0, 1, 0]}, **kw}
    return TestClient(app).post("/api/md/jobs", json=body)


def test_field_without_anchor_is_allowed(monkeypatch):
    """An unanchored uniform force just streams the structure across the box (COM
    drift) — the UI warns, but the anchor guard no longer fires.  We stub the engine
    probe (the next check after the removed guard) so the request stops there
    deterministically, proving it reached PAST where the anchor 400 used to be."""
    import backend.api.routes_md as rm

    monkeypatch.setattr(rm, "find_namd", lambda: (_ for _ in ()).throw(RuntimeError("no namd here")))
    r = _post_create(anchors=None)
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "no namd here" in detail   # reached the engine probe ⇒ anchor guard did not fire
    assert "anchor" not in detail


def test_field_with_multi_gpu_is_rejected():
    """NAMD 3: 'EField is not compatible with multi-GPU GPUresident'."""
    r = _post_create(anchors=[{"kind": "base", "helix_id": 0, "bp_index": 0}], devices="0,1")
    assert r.status_code == 400
    assert "multi-gpu" in r.json()["detail"].lower()


@pytest.mark.parametrize("bad", [
    {"field_pN": "x", "dir": [0, 1, 0]},
    {"field_pN": 1.0, "dir": [1, 0]},
    {"field_pN": 1.0, "dir": 5},
])
def test_malformed_field_is_a_400_not_a_500(bad):
    r = _post_create(field=bad, anchors=[{"kind": "base", "helix_id": 0, "bp_index": 0}])
    assert r.status_code == 400
    assert "malformed field spec" in r.json()["detail"].lower()


def test_no_field_skips_both_guards(monkeypatch):
    """RED guard: the anchor/device rules must fire ONLY when a real field is present.

    A zero-magnitude field is not a field, so an unanchored multi-GPU job must sail past
    both guards.  We stub the engine probe (the next check after the guards) so the request
    stops there deterministically — proving it reached PAST the guards, and never spawning
    a real background prep on a dev box that has NAMD installed.
    """
    import backend.api.routes_md as rm
    from fastapi.testclient import TestClient

    from backend.api.main import app

    monkeypatch.setattr(rm, "find_namd", lambda: (_ for _ in ()).throw(RuntimeError("no namd here")))

    for field in (None, {"field_pN": 0.0, "dir": [0, 1, 0]}):
        r = TestClient(app).post("/api/md/jobs", json={"field": field, "devices": "0,1"})
        assert r.status_code == 400
        detail = r.json()["detail"].lower()
        assert "no namd here" in detail   # reached the engine probe ⇒ guards did not fire
        assert "anchor" not in detail
        assert "multi-gpu" not in detail


# ── prep-time guard: anchors that RESOLVE to nothing must not run an unanchored field ──


def test_field_with_unresolvable_anchors_is_allowed_at_prep(tmp_path, monkeypatch, caplog):
    """A stale/ssDNA-only anchor scope resolves to zero residues.  That's no longer a
    hard error — the field is prepared anchorless (the UI warns about the COM drift)."""
    import backend.core.namd_solvate as ns

    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)

    from backend.core.md_protocols import prepare_mgh_slow_release

    design = make_minimal_design(helix_length_bp=8)
    stale = [{"kind": "strand", "id": "no-such-strand-id"}]
    job_dir = tmp_path / "job"
    job_dir.mkdir()

    with caplog.at_level("WARNING"):
        prepare_mgh_slow_release(
            design, job_dir, ion_conc_mM=0.0, mg_conc_mM=0.0, salt_mode="custom",
            fast=False, anchors=stale, field={"field_pN": 2.0, "dir": [0, 1, 0]},
        )
    assert any("drift" in r.message.lower() for r in caplog.records), \
        "expected a COM-drift warning when the field's anchors resolve to nothing"


def test_local_resume_conf_preserves_field_and_anchors(tmp_path):
    """The LOCAL runner keeps its own _RESUME_DROP list, hand-duplicated from
    md_protocols'. Pin it so a future edit to one list can't silently drop the field."""
    from backend.core import namd_runner

    spec = _first_spec()
    conf = _segment_conf(
        spec, "demo", (100.0, 100.0, 100.0), False,
        field={"field_pN": 2.0, "dir": [0.0, 1.0, 0.0]},
        anchors_file="restraints_anchors.pdb",
    )
    package_dir, output_dir = tmp_path / "pkg", tmp_path / "pkg" / "output"
    output_dir.mkdir(parents=True)
    (package_dir / f"{spec.name}.conf").write_text(conf)
    for ext in ("coor", "vel", "xsc"):
        (output_dir / f"{spec.name}.restart.{ext}").write_bytes(b"")

    base = namd_runner._write_resume_conf(package_dir, output_dir, spec.name, 100, spec.steps)
    resumed = (package_dir / f"{base}.conf").read_text()
    assert "eFieldOn           on" in resumed
    assert _conf_efield_vector(resumed) == _conf_efield_vector(conf)
    assert "fixedAtoms         on" in resumed


# ── real psfgen: q_res = −1 e is the force field's value, not our assumption ───


def _fake_solvate(_pdb_text, _padding_nm, _tmpdir, progress=None, *, water_shell_nm=None):
    """Stand-in for gmx solvation (mirrors test_namd_anchors): psfgen still runs for real,
    so the PSF whose charges we read below is the genuine CHARMM topology."""
    import backend.core.namd_solvate as ns
    from backend.core.namd_solvate import _Water

    ns._emit(progress, "solvate", None, "fake solvate")
    waters = [_Water(i * 0.31, 0, 0, i * 0.31, 0.1, 0, i * 0.31, -0.1, 0) for i in range(2000)]
    return waters, (12.0, 12.0, 12.0)


@pytest.mark.slow
def test_prepare_writes_efield_end_to_end_and_psf_charge_is_minus_one(tmp_path, monkeypatch):
    """SLOW: real psfgen → every ladder conf carries the field, and the REAL PSF's
    per-DNA-residue net charge is exactly −1 e, which is what makes the emitted
    eField vector deliver ``field_pN`` per nucleotide."""
    import backend.core.namd_solvate as ns

    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)

    from backend.core.md_protocols import prepare_mgh_slow_release

    design = make_minimal_design(helix_length_bp=8)
    anchors = [{"kind": "strand", "id": design.strands[0].id}]
    field = {"field_pN": 2.0, "dir": [0.0, 1.0, 0.0]}

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    _sub, stem, segments = prepare_mgh_slow_release(
        design, job_dir, ion_conc_mM=0.0, mg_conc_mM=0.0, salt_mode="custom",
        fast=False, anchors=anchors, field=field,
    )

    pkg = next((job_dir / "package").iterdir())
    manifest = json.loads((pkg / "manifest.json").read_text())

    # every conf in the ladder (minimisation + all segments) carries the field
    confs = [pkg / f"{manifest['minimization']['name']}.conf"]
    confs += [pkg / f"{s.name}.conf" for s in segments]
    for c in confs:
        text = c.read_text()
        assert "eFieldOn           on" in text, c.name
        np.testing.assert_allclose(
            _force_pn_on_nucleotide(_conf_efield_vector(text)), [0.0, 2.0, 0.0], atol=1e-9
        )

    assert manifest["field"]["field_pN"] == 2.0
    assert manifest["field"]["dir"] == [0.0, 1.0, 0.0]
    assert manifest["field"]["charge_per_nucleotide_e"] == -1.0


def _psf_strand_residue_charges(psf_text: str) -> dict[str, list[tuple[int, float]]]:
    """Net charge per DNA residue, grouped by segid and ordered by resid."""
    from backend.core.md_charge import parse_psf_atoms

    dna = {"ADE", "THY", "GUA", "CYT"}
    per_res: dict[tuple[str, int], float] = {}
    for a in parse_psf_atoms(psf_text):
        if a.resname.upper() not in dna:
            continue
        key = (a.segid, int(a.resid))
        per_res[key] = per_res.get(key, 0.0) + a.charge
    out: dict[str, list[tuple[int, float]]] = {}
    for (segid, resid), q in per_res.items():
        out.setdefault(segid, []).append((resid, q))
    for lst in out.values():
        lst.sort()
    return out


@pytest.mark.slow
def test_real_psf_charges_pin_the_conversion_and_the_terminal_deficit():
    """(b) — the force field's OWN charges, from a real psfgen build.

    Internal nucleotide = −1.000 e exactly ⇒ it feels exactly ``field_pN`` under the
    emitted eField.  Termini are 5TER/3TER hydroxyls and together carry one phosphate, so
    a strand carries −(N−1) e.  RED guard against a future "let's rescale eField so the
    total matches oxDNA" change.
    """
    from backend.core.namd_topology import build_charmm_psfgen_topology

    design = make_minimal_design(helix_length_bp=8)
    build = build_charmm_psfgen_topology(design)
    strands = _psf_strand_residue_charges(build.psf_text)
    assert strands, "no DNA residues parsed from the PSF"

    for segid, residues in strands.items():
        n = len(residues)
        assert n >= 3, f"{segid} too short to have an interior"
        interior = [q for _, q in residues[1:-1]]
        for q in interior:
            assert q == pytest.approx(-1.0, abs=1e-4), f"{segid} interior residue {q}"

        first_q, last_q = residues[0][1], residues[-1][1]
        # 5TER + 3TER hydroxyls together carry exactly one phosphate's charge
        assert first_q + last_q == pytest.approx(-1.0, abs=1e-3)
        assert first_q == pytest.approx(-0.47, abs=1e-2)
        assert last_q == pytest.approx(-0.53, abs=1e-2)

        # strand total == its phosphate count == −(N−1)
        total = sum(q for _, q in residues)
        assert total == pytest.approx(-(n - 1), abs=1e-3)


# ── real NAMD: the RESPONSE property (anchor holds, free deflects along field) ─

_FF_DIR = Path(__file__).resolve().parents[1] / "backend" / "data" / "forcefield"

#: 1 pN / amu, expressed in Å·fs⁻².  Derived here from SI constants ONLY (no production
#: constant), so the real-NAMD magnitude check below is independent of KCAL_MOL_A_IN_PN:
#:   1 pN = 1e-12 N; 1 amu = 1.66053906660e-27 kg  ⇒  a [m/s²] = F/m
#:   → Å·fs⁻²: × 1e10 Å/m × (1e-15 s/fs)² = × 1e-20
_ACCEL_PN_PER_AMU = 1e-12 / 1.66053906660e-27 * 1e-20


def _read_namd_coor(path: Path) -> np.ndarray:
    """NAMD binary .coor → (n, 3) Å (int32 count, then little-endian float64 xyz)."""
    raw = path.read_bytes()
    n = struct.unpack("<i", raw[:4])[0]
    return np.array(struct.unpack(f"<{3 * n}d", raw[4:4 + 24 * n])).reshape(n, 3)


def _probe_header(dt_fs: float) -> str:
    """Non-periodic, zero-temperature, frictionless NAMD conf preamble."""
    return f"""\
structure          dna.psf
coordinates        dna.pdb
paraTypeCharmm     on
parameters         {_FF_DIR}/par_all36_na.prm
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         8.0
cutoff             10.0
pairlistdist       12.0
rigidBonds         none
timestep           {dt_fs:g}
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
outputEnergies     1000
binaryrestart      no
temperature        0
"""


@pytest.mark.slow
def test_real_namd_run_holds_anchor_and_accelerates_free_strand_along_field(tmp_path):
    """SLOW: real NAMD. A falsifiable prediction, not a conf-text assertion.

    Two zero-temperature, frictionless runs from the SAME minimised structure with one
    strand held by ``fixedAtoms`` — one with the field, one without.  Differencing the free
    strand's centre of mass cancels every non-field force to leading order, leaving the
    field's own impulse.  NAMD must then reproduce, from its own atomic charges:

      * the anchored atoms do not move AT ALL (the ``fixedAtoms`` guarantee), and
      * ΔCOM = ½ · (q_free · eField / M_free) · t², i.e. the free strand accelerates
        ALONG the requested force direction with the predicted magnitude.

    The second assertion is what makes the field *comparable*: it pins the unit conversion,
    the −1 e per phosphate, and the antiparallel sign simultaneously.  Get any of them
    wrong and the observed displacement misses (or reverses).
    """
    from backend.core.md_charge import parse_psf_atoms
    from backend.core.namd_runner import find_namd
    from backend.core.namd_topology import build_charmm_psfgen_topology

    try:
        namd_bin = find_namd()
    except RuntimeError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"NAMD not available: {exc}")

    field_pN, dir_ = 500.0, np.array([0.0, 1.0, 0.0])
    steps, dt_fs = 200, 1.0

    design = make_minimal_design(helix_length_bp=8)
    build = build_charmm_psfgen_topology(design)
    (tmp_path / "dna.psf").write_text(build.psf_text)
    (tmp_path / "dna.pdb").write_text(build.pdb_text)

    atoms = parse_psf_atoms(build.psf_text)
    segids = sorted({a.segid for a in atoms})
    assert len(segids) == 2, "probe expects a two-strand duplex"
    fixed_mask = np.array([a.segid == segids[0] for a in atoms])
    free_mask = ~fixed_mask
    charge = np.array([a.charge for a in atoms])
    mass = np.array([a.mass for a in atoms])

    # fixedAtoms marker PDB: B=1 on every atom of the anchored strand
    out, i = [], 0
    for ln in build.pdb_text.splitlines():
        if ln.startswith(("ATOM", "HETATM")):
            ln = ln[:60] + f"{1.00 if fixed_mask[i] else 0.00:6.2f}" + ln[66:]
            i += 1
        out.append(ln)
    (tmp_path / "fixed.pdb").write_text("\n".join(out) + "\n")

    efield = namd_efield_vector({"field_pN": field_pN, "dir": dir_.tolist()})
    fixed_block = "fixedAtoms         on\nfixedAtomsFile     fixed.pdb\nfixedAtomsCol      B\n"

    (tmp_path / "min.conf").write_text(
        _probe_header(dt_fs) + "outputName         min\nminimize           500\n"
    )
    for tag, field_block in (
        ("off", ""),
        ("on", "eFieldOn           on\neField             {:.8g} {:.8g} {:.8g}\n".format(*efield)),
    ):
        (tmp_path / f"dyn_{tag}.conf").write_text(
            _probe_header(dt_fs) + fixed_block + field_block
            + f"outputName         dyn_{tag}\nbinCoordinates     min.coor\nrun                {steps}\n"
        )

    for name in ("min", "dyn_off", "dyn_on"):
        proc = subprocess.run([namd_bin, f"{name}.conf"], cwd=tmp_path,
                              capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, f"{name} failed:\n{proc.stdout[-2500:]}"

    start = _read_namd_coor(tmp_path / "min.coor")
    off = _read_namd_coor(tmp_path / "dyn_off.coor")
    on = _read_namd_coor(tmp_path / "dyn_on.coor")

    # (1) fixedAtoms: the anchored strand is bit-for-bit immobile, field or not
    assert np.abs(on[fixed_mask] - start[fixed_mask]).max() == 0.0
    assert np.abs(off[fixed_mask] - start[fixed_mask]).max() == 0.0

    # (2) the field's impulse on the free strand, isolated by differencing
    m_free = mass[free_mask]
    com = lambda p: (p[free_mask] * m_free[:, None]).sum(0) / m_free.sum()  # noqa: E731
    delta = com(on) - com(off)                                   # Å

    # 8-nt strand carries exactly 7 phosphates → −7 e (the terminal-deficit fact above)
    q_free = charge[free_mask].sum()
    assert q_free == pytest.approx(-7.0, abs=1e-6)

    # The prediction is stated in the SHARED DESCRIPTOR's own units and never touches the
    # emitted eField vector: 7 phosphates × field_pN, along +dir.  This closes the loop —
    # a wrong KCAL_MOL_A_IN_PN would scale `efield` (and hence NAMD's real force) without
    # scaling this, so the magnitude assertion would fail.  n_phosphates comes from NAMD's
    # own PSF charges, not from our per-nucleotide constant.
    n_phosphates = abs(q_free)
    force_pn = n_phosphates * field_pN                           # pN, along +dir
    accel = force_pn * _ACCEL_PN_PER_AMU / m_free.sum()          # Å·fs⁻²
    predicted_mag = 0.5 * accel * (steps * dt_fs) ** 2           # Å

    # direction: along +dir (a sign error would point it at −dir)
    assert float(delta @ dir_) > 0.0
    assert float(delta @ dir_ / np.linalg.norm(delta)) > 0.99

    # magnitude: within 10 % of ½·a·t² (residual is the O(t⁴) force-change correction)
    assert np.linalg.norm(delta) == pytest.approx(predicted_mag, rel=0.10)
