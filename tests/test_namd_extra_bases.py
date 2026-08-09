"""N3 — crossover extra bases + linkers in the atomistic/NAMD path, and shared
descriptor emission from an MD frame that contains those inserts.

Two properties, both a *comparable prediction* (not "it ran"):

**Part A — the atomistic model materializes the inserts + their linker.**  A
crossover carrying ``extra_bases="TT"`` must add exactly its inserts to the
heavy-atom model that feeds NAMD: two full DT residues (ribose + base), each
tagged with the crossover-insert identity (``crossover_id`` + ``extra_base_k``),
threaded inline in the owning chain, and joined by real phosphodiester linker
atoms (O3′/P/O5′).  The pre-existing atomistic tests only assert the *negative*
(a direct crossover adds no hidden bases); nothing pinned the positive build, so
a regression in ``_build_extra_base_atoms`` / ``_thread_inserts_inline`` would
ship silently.

**Part B — the NAMD shared-descriptor source is robust to inserts in the MD
frame.**  ``md_rmsf`` keys crossover inserts as ``("__xb__", crossover_id, k)`` —
i.e. a *string* ``bp_index`` (see :func:`backend.core.atomistic_to_nadoc.md_pkey`).
:func:`build_namd_shape_source` must emit descriptors + an RMSF profile from such a
frame without crashing, dropping the ssDNA inserts from BOTH the shape core and the
RMSF profile (they have no dsDNA-core column), so the emitted descriptors are
IDENTICAL to the insert-free frame.  Before the N3 fix ``_rmsf_profile`` did
``int(p["bp_index"])`` unconditionally and raised ``ValueError`` on the first insert
— the N4 gold-override column would crash on any design with a linker.  This is the
same str-vs-int class ``md_pkey`` already records having crashed the live display.
"""

from __future__ import annotations

import pytest

from backend.api.skip_twist_tuning import core_reference_geometry
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_to_nadoc import _XB_SENTINEL
from backend.core.lattice import make_bundle_design
from backend.core.models import Crossover, Direction, HalfCrossover, NucleotideTransform
from backend.core.namd_shape_source import build_namd_shape_source

_RIBOSE = {"C1'", "C2'", "C3'", "C4'", "O4'"}
_LINKER = {"O3'", "P", "O5'"}


def _design(extra_bases):
    """Two coaxial helices joined by one crossover, optionally carrying inserts."""
    d = make_bundle_design([(0, 0), (0, 1)], length_bp=21, plane="XY")
    xo = Crossover(
        id="xo_extra",
        half_a=HalfCrossover(
            helix_id=d.helices[0].id, index=6, strand=Direction.FORWARD
        ),
        half_b=HalfCrossover(
            helix_id=d.helices[1].id, index=6, strand=Direction.REVERSE
        ),
        extra_bases=extra_bases,
    )
    return d.model_copy(update={"crossovers": [xo]})


def _residues(model):
    return {(a.chain_id, a.seq_num) for a in model.atoms}


# ── Part A: the atomistic model includes the insert + linker atoms ────────────


def test_model_grows_by_exactly_the_insert_count():
    """extra_bases="TT" adds exactly two residues vs the direct-crossover model."""
    direct = build_atomistic_model(_design(None))
    twoins = build_atomistic_model(_design("TT"))
    assert len(_residues(twoins)) - len(_residues(direct)) == 2


def test_inserts_tagged_with_crossover_identity():
    """Each insert carries (crossover_id, extra_base_k); "TT" -> k in {0, 1}."""
    model = build_atomistic_model(_design("TT"))
    xb = [a for a in model.atoms if a.crossover_id is not None]
    assert xb, "no extra-base atoms materialized"
    assert {a.crossover_id for a in xb} == {"xo_extra"}
    assert sorted({a.extra_base_k for a in xb}) == [0, 1]


def test_saved_insert_pose_is_the_atomistic_and_namd_builder_starting_coordinate():
    """The shared builder used by display and ``build_namd_package`` applies the
    authored pose to every atom in exactly one inserted residue."""
    bare_design = _design("TT")
    bare = build_atomistic_model(bare_design)
    pose = NucleotideTransform(
        kind="extra_base", crossover_id="xo_extra", extra_base_k=1,
        pivot=[0, 0, 0], translation=[0.4, -0.2, 0.7], rotation=[0, 0, 0, 1],
    )
    moved = build_atomistic_model(
        bare_design.model_copy(update={"nucleotide_transforms": [pose]})
    )
    for before, after in zip(bare.atoms, moved.atoms, strict=True):
        if before.crossover_id == "xo_extra" and before.extra_base_k == 1:
            assert [after.x-before.x, after.y-before.y, after.z-before.z] == pytest.approx([0.4, -0.2, 0.7])
        else:
            assert [after.x, after.y, after.z] == pytest.approx([before.x, before.y, before.z])


def test_each_insert_is_a_full_residue_with_linker():
    """Every insert is a complete DT residue: ribose ring + base + O3'/P/O5' linker."""
    model = build_atomistic_model(_design("TT"))
    xb = [a for a in model.atoms if a.crossover_id is not None]
    by_k: dict[int, set[str]] = {}
    for a in xb:
        by_k.setdefault(a.extra_base_k, set()).add(a.name)
    assert set(by_k) == {0, 1}
    for k, names in by_k.items():
        assert _RIBOSE <= names, f"insert {k} missing ribose atoms: {_RIBOSE - names}"
        assert _LINKER <= names, f"insert {k} missing linker atoms: {_LINKER - names}"
        assert "N1" in names, f"insert {k} missing pyrimidine base ring"
        assert {a.residue for a in xb if a.extra_base_k == k} == {"DT"}


def test_inserts_are_threaded_inline_in_the_owning_chain():
    """Inserts get contiguous seq_nums inside their chain (no gap) — the inline
    threading pass, not appended off the end with a hole between."""
    model = build_atomistic_model(_design("TT"))
    xb = [a for a in model.atoms if a.crossover_id is not None]
    chain = {a.chain_id for a in xb}
    assert len(chain) == 1, "both inserts should ride one owning chain"
    (ch,) = chain
    seqs = sorted({a.seq_num for a in model.atoms if a.chain_id == ch})
    assert seqs == list(range(seqs[0], seqs[-1] + 1)), (
        "chain residue numbering has a gap"
    )
    insert_seqs = sorted({a.seq_num for a in xb})
    assert len(insert_seqs) == 2 and insert_seqs[1] - insert_seqs[0] == 1


def test_seeded_insert_keeps_canonical_backbone_bonds():
    """An oxDNA-seeded insert (``xb_pos_override`` set → the scipy bridge-minimisation
    is skipped) must still have CANONICAL intra-residue backbone bonds.

    Regression pin for the 24hb 4 fs blocker: the glycosidic rotation used to exclude
    the phosphate group {P,OP1,OP2,O5'} on the assumption the skipped minimisation would
    re-place it, so an overridden insert stranded O5'/P → O5'-C5' stretched to ~6 A
    (0.6 nm), a fatal 4 fs RATTLE start.  Measured on the seeded 24hb_1xT package built by
    the pre-fix code: 384 O5'-C5' bonds at ~6.1 A.  The fix rotates the phosphate rigidly
    with its own sugar for an overridden insert.  See NAMD_4FS_RATTLE_RESEARCH.md."""
    import numpy as np

    ov = {
        ("xo_extra", 0): np.array([2.0, 1.0, 3.0])
    }  # arbitrary relaxed backbone pos (nm)
    model = build_atomistic_model(_design("T"), xb_pos_override=ov)
    pos = {
        a.name: np.array([a.x, a.y, a.z])
        for a in model.atoms
        if a.crossover_id == "xo_extra" and a.extra_base_k == 0
    }
    assert {"P", "O5'", "C5'", "C4'"} <= set(pos), "insert missing backbone atoms"

    def blen(n1, n2):
        return float(np.linalg.norm(pos[n1] - pos[n2]))

    # Canonical B-DNA intra-residue backbone bonds are ~0.14-0.16 nm; the pre-fix bug
    # produced ~0.6 nm.  0.20 nm cleanly separates healed from stranded.
    o5_c5 = blen("O5'", "C5'")
    p_o5 = blen("P", "O5'")
    c5_c4 = blen("C5'", "C4'")
    assert o5_c5 < 0.20, (
        f"O5'-C5' = {o5_c5:.3f} nm — phosphate stranded (should be ~0.144)"
    )
    assert p_o5 < 0.20, f"P-O5' = {p_o5:.3f} nm"
    assert c5_c4 < 0.20, f"C5'-C4' = {c5_c4:.3f} nm"


# ── Part B: descriptors emit from an MD frame that CONTAINS the inserts ────────


def _md_frame(core, *, with_inserts):
    """An md_rmsf-shaped positions list: the dsDNA-core columns (int bp_index) plus,
    optionally, the two ssDNA inserts md_rmsf emits as ("__xb__", crossover_id, k)
    with a *string* bp_index and a large fluctuation."""
    frame = [
        {
            "helix_id": p["helix_id"],
            "bp_index": p["bp_index"],
            "direction": p["direction"],
            "backbone_position": list(p["backbone_position"]),
            "rmsf": 0.12,
        }
        for p in core
    ]
    if with_inserts:
        for k, direction in ((0, "FORWARD"), (1, "FORWARD")):
            frame.append(
                {
                    "helix_id": _XB_SENTINEL,
                    "bp_index": "xo_extra",
                    "direction": direction,
                    "backbone_position": [88.0 + k, 88.0, 88.0],
                    "rmsf": 9.0,
                }
            )
    return frame


def test_descriptors_emit_from_a_frame_containing_inserts():
    """build_namd_shape_source yields non-None descriptors from a frame that
    includes the ssDNA inserts — the "computable from an MD frame" pin."""
    core = core_reference_geometry(_design("TT"))
    frame = _md_frame(core, with_inserts=True)
    src = build_namd_shape_source(frame, core, rmsf_positions=frame)
    assert src["engine"] == "namd"
    assert src["descriptors"] is not None


def test_inserts_dropped_from_shape_core_and_rmsf_profile():
    """The string-keyed inserts appear in NEITHER the shape core NOR the RMSF
    profile — both are keyed to the dsDNA core (int bp_index)."""
    core = core_reference_geometry(_design("TT"))
    frame = _md_frame(core, with_inserts=True)
    src = build_namd_shape_source(frame, core, rmsf_positions=frame)
    assert all(isinstance(p["bp_index"], int) for p in src["shape_frame"])
    assert all(isinstance(p["bp_index"], int) for p in src["rmsf"])
    # The wild insert fluctuation (9.0 nm) never leaks into the profile.
    assert all(p["rmsf_nm"] < 1.0 for p in src["rmsf"])


def test_descriptors_identical_with_and_without_inserts_in_the_frame():
    """The comparable prediction: dropping the inserts means the emitted shape
    descriptors are byte-identical to the insert-free frame — the inserts do not
    perturb the cross-engine metric."""
    core = core_reference_geometry(_design("TT"))
    clean = build_namd_shape_source(_md_frame(core, with_inserts=False), core)
    dirty = build_namd_shape_source(_md_frame(core, with_inserts=True), core)
    assert clean["descriptors"] is not None
    assert clean["descriptors"] == dirty["descriptors"]


def test_rmsf_profile_survives_string_insert_keys():
    """RED before the N3 fix: _rmsf_profile did int(p['bp_index']) and raised
    ValueError on the ('__xb__', crossover_id, k) insert key.  The RMSF profile
    must build (dropping the inserts) rather than crash."""
    core = core_reference_geometry(_design("TT"))
    frame = _md_frame(core, with_inserts=True)
    src = build_namd_shape_source(frame, core, rmsf_positions=frame)
    assert src["rmsf"] is not None
    # Every dsDNA-core column with a fluctuation sample is represented.
    assert len(src["rmsf"]) == len(core)
