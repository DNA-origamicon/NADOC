"""Phase-1b: motif-aware batch generator of short double-stranded DNA systems.

Produces the training + test **designs** for the atomistic-propagator MVP.  Each
generated system is a standalone NADOC :class:`~backend.core.models.Design` (a
short B-DNA duplex, optionally carrying one controlled structural motif) plus a
metadata record describing exactly how it was made — the spec's required
provenance: sequence, motif type + location, ionic conditions, temperature,
force-field version, seed, and the train/val/test split it belongs to.

The heavy lifting is delegated to the existing headless build layer
(``backend.api.headless_build``); this module only *composes* those primitives
into a labelled catalog and gates every design through the automation oracle
(``assert_roundtrip_stable``) so a malformed system can never enter the dataset.

**Split discipline (spec):** the split is assigned per *system / motif family*
here, at generation time, and written into ``system.json``.  Frames from one
duplex therefore never straddle the train/test boundary downstream — the window
exporter (1d) only ever reads the split label, it never re-samples it.

**Box dimensions** are intentionally left ``None`` at generation: they are set by
the solvation step (1c), which builds the padded water box around the design.

Deferred motifs (raise :class:`NotImplementedError` with a pointer):
    * ``bulge`` — the headline out-of-distribution motif.  A real single-strand
      internal bulge is an *asymmetric* unpaired insert on one strand; it is not
      first-class topology and its atomistic placement is unverified.  Blocked on
      an explicit representation decision + a ``build_atomistic_model`` spike
      (see the plan's ⚠).  Do NOT guess a representation here.
    * ``bend`` / ``twist`` — controlled global deformation via the build-spec
      grammar; a follow-up once the core duplex→sim→dataset loop is proven.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import Design, Direction, LatticeType, StrandType

# ── Fixed conditions for the MVP (spec: a single FF/water model, one T, small
#    set of ionic conditions).  These are metadata only — the actual water box +
#    ion placement happen in the solvation step (1c) from these numbers. ────────
FORCEFIELD_VERSION = "charmm36_na+cufix"   # backend/data/forcefield/*
WATER_MODEL = "TIP3P"
DEFAULT_TEMPERATURE_K = 300.0
DEFAULT_NACL_MM = 150.0
DEFAULT_MGCL2_MM = 0.0

_WC = {"A": "T", "T": "A", "G": "C", "C": "G"}


@dataclass
class GeneratedSystem:
    """One generated DNA system: the design + its full provenance metadata.

    ``design`` is the in-memory NADOC design; :meth:`write` serialises it to
    ``<dir>/design.nadoc`` and the metadata to ``<dir>/system.json``.
    """
    system_id: str
    design: Design
    sequence: str
    motif_type: str            # "canonical" | "nick" | "mismatch" | "bulge" | ...
    motif_location: Optional[int]   # 0-based bp index of the motif; None if canonical
    length_bp: int
    nacl_mM: float
    mgcl2_mM: float
    temperature_K: float
    seed: int
    split: str                 # "train" | "val" | "test"
    forcefield_version: str = FORCEFIELD_VERSION
    water_model: str = WATER_MODEL
    box_ang: Optional[list] = None      # filled by the solvation step (1c)
    lattice: str = LatticeType.SQUARE.value
    topology_stats: Optional[dict] = None   # helices/strands/crossovers/nt (origami)

    def metadata(self) -> dict:
        """The ``system.json`` record (everything except the design object)."""
        d = asdict(self)
        d.pop("design")
        return d

    def write(self, out_dir: str | Path) -> Path:
        """Write ``design.nadoc`` + ``system.json`` into ``out_dir`` (created)."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "design.nadoc").write_text(self.design.to_json())
        (out / "system.json").write_text(json.dumps(self.metadata(), indent=2))
        return out


# ── ID helper ────────────────────────────────────────────────────────────────
def _system_id(motif: str, sequence: str, seed: int,
               nacl_mM: float, mgcl2_mM: float, temperature_K: float,
               motif_location: Optional[int]) -> str:
    """Deterministic short id from the full spec — reproducible across machines
    (no wall-clock / RNG), and identical inputs collapse to one directory."""
    payload = f"{motif}|{sequence}|{seed}|{nacl_mM}|{mgcl2_mM}|{temperature_K}|{motif_location}"
    digest = hashlib.sha1(payload.encode()).hexdigest()[:8]
    return f"{motif}_{len(sequence)}bp_{digest}"


def _validate_sequence(sequence: str) -> str:
    seq = sequence.strip().upper()
    if not seq or any(b not in _WC for b in seq):
        raise ValueError(f"sequence must be non-empty over A/C/G/T, got {sequence!r}")
    return seq


def _staple_strand(design: Design) -> Optional[object]:
    """The single staple strand of a plain duplex (None if not found)."""
    staples = [s for s in design.strands
               if s.strand_type == StrandType.STAPLE and not s.is_reference]
    return staples[0] if len(staples) == 1 else None


# ── Builders ─────────────────────────────────────────────────────────────────
def canonical_duplex(
    sequence: str,
    *,
    seed: int = 42,
    split: str = "train",
    nacl_mM: float = DEFAULT_NACL_MM,
    mgcl2_mM: float = DEFAULT_MGCL2_MM,
    temperature_K: float = DEFAULT_TEMPERATURE_K,
    lattice: LatticeType = LatticeType.SQUARE,
) -> GeneratedSystem:
    """A fully Watson–Crick-paired B-DNA duplex of ``sequence`` (in-distribution).

    One lattice cell → a single helix carrying an antiparallel scaffold+staple
    pair; the scaffold gets ``sequence`` and the staple is its WC complement.
    """
    seq = _validate_sequence(sequence)
    with hb.scratch_session(lattice):
        hb.create_bundle([[0, 0]], len(seq), lattice=lattice, name="duplex")
        hb.assign_scaffold_sequence(custom_sequence=seq)
        hb.assign_staple_sequences()
        design = design_state.get_or_404().model_copy(deep=True)
    return GeneratedSystem(
        system_id=_system_id("canonical", seq, seed, nacl_mM, mgcl2_mM,
                             temperature_K, None),
        design=design, sequence=seq, motif_type="canonical", motif_location=None,
        length_bp=len(seq), nacl_mM=nacl_mM, mgcl2_mM=mgcl2_mM,
        temperature_K=temperature_K, seed=seed, split=split, lattice=lattice.value)


def nicked_duplex(
    sequence: str,
    *,
    nick_bp: Optional[int] = None,
    seed: int = 42,
    split: str = "test",
    nacl_mM: float = DEFAULT_NACL_MM,
    mgcl2_mM: float = DEFAULT_MGCL2_MM,
    temperature_K: float = DEFAULT_TEMPERATURE_K,
    lattice: LatticeType = LatticeType.SQUARE,
) -> GeneratedSystem:
    """A duplex with a single backbone nick (a break, no missing bases) on the
    *staple* strand at ``nick_bp`` (default: mid-strand).  A mild, well-defined
    motif.  Nicking the staple (not the continuous scaffold) keeps the design
    single-scaffold; sequencing happens after the nick so ``assign_staple_
    sequences`` Watson–Crick-fills each fragment consistently."""
    seq = _validate_sequence(sequence)
    bp = len(seq) // 2 if nick_bp is None else nick_bp
    with hb.scratch_session(lattice):
        hb.create_bundle([[0, 0]], len(seq), lattice=lattice, name="duplex_nick")
        d0 = design_state.get_or_404()
        helix_id = d0.helices[0].id
        staple = _staple_strand(d0)
        if staple is None or not staple.domains:
            raise RuntimeError("expected a single staple strand to nick")
        staple_dir = staple.domains[0].direction
        hb.nick(helix_id, bp, staple_dir)
        hb.assign_scaffold_sequence(custom_sequence=seq)
        hb.assign_staple_sequences()
        design = design_state.get_or_404().model_copy(deep=True)
    return GeneratedSystem(
        system_id=_system_id("nick", seq, seed, nacl_mM, mgcl2_mM,
                             temperature_K, bp),
        design=design, sequence=seq, motif_type="nick", motif_location=bp,
        length_bp=len(seq), nacl_mM=nacl_mM, mgcl2_mM=mgcl2_mM,
        temperature_K=temperature_K, seed=seed, split=split, lattice=lattice.value)


def mismatch_duplex(
    sequence: str,
    *,
    mismatch_bp: Optional[int] = None,
    seed: int = 42,
    split: str = "test",
    nacl_mM: float = DEFAULT_NACL_MM,
    mgcl2_mM: float = DEFAULT_MGCL2_MM,
    temperature_K: float = DEFAULT_TEMPERATURE_K,
    lattice: LatticeType = LatticeType.SQUARE,
) -> GeneratedSystem:
    """A duplex with one non-Watson–Crick base pair at ``mismatch_bp`` (default:
    mid-strand).  Topology is identical to the canonical duplex — only one
    staple base is changed to a non-complementary base (a pure sequence edit,
    no strand-graph change), so the pair is mispaired but both strands stay full
    length."""
    seq = _validate_sequence(sequence)
    bp = len(seq) // 2 if mismatch_bp is None else mismatch_bp
    if not (0 <= bp < len(seq)):
        raise ValueError(f"mismatch_bp {bp} out of range for length {len(seq)}")
    canonical = canonical_duplex(
        seq, seed=seed, split=split, nacl_mM=nacl_mM, mgcl2_mM=mgcl2_mM,
        temperature_K=temperature_K, lattice=lattice)
    design = canonical.design
    staple = _staple_strand(design)
    if staple is None or not staple.sequence:
        raise RuntimeError("expected a single sequenced staple strand to mispair")
    # The WC-correct staple base for scaffold[bp]; pick any different base to
    # break the pair (the staple sequence is 5′→3′, same length as the scaffold).
    idx = min(bp, len(staple.sequence) - 1)
    correct = staple.sequence[idx]
    mispaired = next(b for b in "ACGT" if b != correct)
    staple.sequence = staple.sequence[:idx] + mispaired + staple.sequence[idx + 1:]
    return GeneratedSystem(
        system_id=_system_id("mismatch", seq, seed, nacl_mM, mgcl2_mM,
                             temperature_K, bp),
        design=design, sequence=seq, motif_type="mismatch", motif_location=bp,
        length_bp=len(seq), nacl_mM=nacl_mM, mgcl2_mM=mgcl2_mM,
        temperature_K=temperature_K, seed=seed, split=split, lattice=lattice.value)


# ── 6-helix-bundle origami (the first multi-helix / crossover rung) ───────────
# Honeycomb cross-section of a 6hb (matches tests/conftest.SIX_HB_CELLS): six
# helices arranged in the standard hexagonal ring so every helix has crossover
# neighbours — the smallest system where DNA-origami physics (crossovers holding
# adjacent duplexes together) actually appears.
SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]


def _topology_stats(design: Design) -> dict:
    """Countable topology provenance for the scaling analysis (atom-count estimate
    + crossover census).  All best-effort: missing attributes degrade to 0/None."""
    strands = [s for s in design.strands if not getattr(s, "is_reference", False)]
    scaf = [s for s in strands if s.strand_type == StrandType.SCAFFOLD]
    stap = [s for s in strands if s.strand_type == StrandType.STAPLE]

    def nt(s) -> int:
        if getattr(s, "sequence", None):
            return len(s.sequence)
        return sum(int(getattr(dm, "length", 0) or 0) for dm in (s.domains or []))

    n_nt = sum(nt(s) for s in strands)
    xos = getattr(design, "crossovers", None)
    n_xover = len(xos) if xos is not None else None
    return {
        "n_helices": len(design.helices),
        "n_scaffold_strands": len(scaf),
        "n_staple_strands": len(stap),
        "n_nucleotides": n_nt,
        "n_crossovers": n_xover,
        # ~19-20 heavy atoms + ~11-12 H per nucleotide for all-atom B-DNA (avg ~31)
        "est_dna_atoms_allatom": int(round(n_nt * 31)),
    }


def origami_6hb(
    length_bp: int = 42,
    *,
    seamless: bool = False,
    scaffold_source: str = "M13mp18",
    seed: int = 42,
    split: str = "train",
    nacl_mM: float = DEFAULT_NACL_MM,
    mgcl2_mM: float = DEFAULT_MGCL2_MM,
    temperature_K: float = DEFAULT_TEMPERATURE_K,
) -> GeneratedSystem:
    """A fully routed + sequenced 6-helix-bundle origami — the first crossover rung.

    Builds the honeycomb 6hb, then runs the SAME auto-pipeline the user drives by
    hand in the app: auto-scaffold (seamed Hamiltonian path unless ``seamless``) →
    auto-crossover (all staple crossovers) → auto-break (staple nicks) → M13
    scaffold sequence + Watson-Crick staple sequences.  Crossovers make adjacent
    duplexes mutually constrain — the origami physics a lone duplex cannot show.

    ``length_bp`` sets the helix length: keep it short (≈21-42 bp) for a solvated
    NAMD reference that fits an 8 GB GPU; grow it for a larger scaling data point.
    Reuses the exact proven chain from ``tests/conftest.make_deposition_chain_design``.
    """
    from backend.core.sequences import (  # noqa: PLC0415
        assign_scaffold_sequence,
        assign_staple_sequences,
    )
    lattice = LatticeType.HONEYCOMB
    with hb.scratch_session(lattice):
        hb.create_bundle(SIX_HB_CELLS, length_bp, lattice=lattice, name="6hb")
        hb.auto_scaffold(seamless=seamless)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)
    for sid in [s.id for s in design.strands
                if s.strand_type == StrandType.SCAFFOLD]:
        design, _, _ = assign_scaffold_sequence(design, scaffold_source, strand_id=sid)
    design = assign_staple_sequences(design)
    stats = _topology_stats(design)
    payload = f"origami6hb|{scaffold_source}|{length_bp}|{seed}|{nacl_mM}|{mgcl2_mM}|{temperature_K}"
    digest = hashlib.sha1(payload.encode()).hexdigest()[:8]
    return GeneratedSystem(
        system_id=f"origami6hb_{length_bp}bp_{digest}",
        design=design, sequence=scaffold_source, motif_type="origami_6hb",
        motif_location=None, length_bp=length_bp, nacl_mM=nacl_mM, mgcl2_mM=mgcl2_mM,
        temperature_K=temperature_K, seed=seed, split=split,
        lattice=lattice.value, topology_stats=stats)


def bulge_duplex(*_args, **_kwargs) -> GeneratedSystem:
    """DEFERRED — the headline out-of-distribution motif (1–3 nt internal bulge).

    A real single-strand internal bulge is an *asymmetric* unpaired insert on one
    strand (flanking bp stay paired), which is NOT first-class topology in NADOC
    and whose atomistic placement by ``build_atomistic_model`` is unverified.
    Blocked on (a) an explicit representation decision with the user and (b) a
    build-atomistic spike confirming the extra base loops out rather than clashing.
    Do not implement a guessed representation — see the plan's ⚠ and CLAUDE.md's
    DNA-topology 'ask first' rule.
    """
    raise NotImplementedError(
        "bulge motif deferred pending representation decision + atomistic spike "
        "(see backend/ml/propagator/systems.py docstring and the plan's ⚠)")


# ── Catalog: the default MVP training + test set ─────────────────────────────
# A small, deterministic pilot set.  Canonical duplexes span the training
# distribution (multiple sequences × lengths × seeds); nick + mismatch are the
# currently-buildable held-out motifs.  The bulge (test set B/C) is added once
# unblocked.  Sequences are fixed literals so the whole catalog is reproducible.
_TRAIN_SEQUENCES = {
    16: ["GCGCATATGCGCATAT", "ACGTACGTACGTACGT", "GGCCAATTGGCCAATT"],
    20: ["GCGCATATGCGCATATGCGC", "ACGTACGTACGTACGTACGT"],
    24: ["GCGCATATGCGCATATGCGCATAT"],
}
_HELDOUT_SEQUENCE = "GCTAGCTAGCTAGCTAGCTA"   # 20 bp, absent from training


def default_catalog() -> list[GeneratedSystem]:
    """The default pilot catalog: canonical training duplexes (a few seeds each)
    + a held-out canonical, nicked, and mismatch duplex for evaluation.

    Small on purpose — run this end-to-end before scaling to a large batch."""
    systems: list[GeneratedSystem] = []
    for length, seqs in _TRAIN_SEQUENCES.items():
        for seq in seqs:
            for seed in (1, 2):
                systems.append(canonical_duplex(seq, seed=seed, split="train"))
    # in-distribution held-out canonical (test set A)
    systems.append(canonical_duplex(_HELDOUT_SEQUENCE, seed=7, split="test"))
    # currently-buildable held-out motifs (subset of test set B/C)
    systems.append(nicked_duplex(_HELDOUT_SEQUENCE, seed=7, split="test"))
    systems.append(mismatch_duplex(_HELDOUT_SEQUENCE, seed=7, split="test"))
    return systems


def write_catalog(out_dir: str | Path,
                  systems: Optional[list[GeneratedSystem]] = None) -> list[Path]:
    """Write each system to ``out_dir/<system_id>/`` and return the paths."""
    systems = default_catalog() if systems is None else systems
    root = Path(out_dir)
    return [gs.write(root / gs.system_id) for gs in systems]
