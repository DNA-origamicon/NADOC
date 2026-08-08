"""SNUPI reference comparator — parse the *real* SNUPI software's output and
match it, node-for-node, to our FEM mimic so every observable becomes a number.

This is the CI-safe, machine-independent half of the NADOC → real-SNUPI → mimic
loop.  It has **no** SNUPI/MATLAB-Runtime dependency and touches no machine-local
paths — the orchestration (running the compiled SNUPI binary, globbing its
timestamped OUTPUT dir) lives in ``scripts/snupi_reference_compare.py``.  Here we
keep only the pure, testable pieces:

* ``nadoc_json_to_snupi_json`` — the one caDNAno-schema fix SNUPI needs.
* PDB / XYZ / .mat parsers for SNUPI's output files.
* ``match_nodes`` — **the crux**: correspond SNUPI's ``(chain, resSeq)`` nodes to
  our ``(helix_id, global_bp)`` nodes.  Primary path is the *topological* caDNAno
  label map (``export_cadnano_with_labels``) because nodes along one helix are
  only 0.34 nm apart — a pure nearest-neighbour match cannot tell adjacent bp
  apart, and a symmetric bundle's axis centres are genuinely ambiguous.  The
  match is **order-based within each helix**; geometry is used only as a global
  sanity gate and to auto-resolve a per-helix ascending/descending flip.  A
  ``match_nodes_spatial`` fallback (centroid alignment + within-helix ordering)
  covers the label-less case and cross-checks the topological result.
* Observable math: shape RMSD (Kabsch), RMSF Pearson/Spearman, mode-shape MAC
  (the new observable — Modal Assurance Criterion vs SNUPI ground truth),
  correlation-matrix agreement.

Three-Layer Law: everything here is analysis / display only — nothing mutates
topology or geometry.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# SNUPI writes coordinates in Angstroms; NADOC works in nm.
ANGSTROM_PER_NM: float = 10.0

# SNUPI runs its NMA at 300 K (k_BT = 4.142 pN·nm) and drops the 6 rigid-body
# modes.  Verified: reconstructing NMA_RMSF from (NMA_EIG_VAL, NMA_EIG_VEC) with
# these two constants matches SNUPI's stored RMSF to <1e-3 %.  (The mimic's own
# NMA uses 298 K / 4.11 — a documented ~0.4 % systematic on RMSF magnitude.)
KBT_300K: float = 1.380649e-23 * 300.0 / 1e-21  # 4.1419 pN·nm
SNUPI_N_RIGID: int = 6
# Free-free Euler–Bernoulli fundamental bending wavenumber (cosh·cos = 1).
_EB_BETA1_L: float = 4.730040744862704

# caDNAno-schema deltas between NADOC's exporter and what SNUPI's parser expects.
# SNUPI's vstrands have empty scafLoop/stapLoop arrays and no scaf_colors key.
_SNUPI_DROP_VSTRAND_KEYS: Tuple[str, ...] = ("scaf_colors",)
_SNUPI_ADD_VSTRAND_KEYS: Tuple[str, ...] = ("scafLoop", "stapLoop")


# ══════════════════════════════════════════════════════════════════════════════
# 1. caDNAno JSON schema shim
# ══════════════════════════════════════════════════════════════════════════════


def nadoc_json_to_snupi_json(cadnano: dict) -> dict:
    """Return a copy of a NADOC caDNAno-export dict that SNUPI's parser accepts.

    SNUPI's caDNAno reader expects each vstrand to carry empty ``scafLoop`` and
    ``stapLoop`` arrays and does **not** expect a ``scaf_colors`` key (verified
    against ``~/SNUPI/EXAMPLE/*.json``).  NADOC's exporter emits ``scaf_colors``
    and omits scafLoop/stapLoop.  All other keys (row, col, num, scaf, stap,
    loop, skip, stap_colors) already match.  The original dict is left untouched.
    """
    out = copy.deepcopy(cadnano)
    for vs in out.get("vstrands", []):
        for k in _SNUPI_DROP_VSTRAND_KEYS:
            vs.pop(k, None)
        for k in _SNUPI_ADD_VSTRAND_KEYS:
            vs.setdefault(k, [])
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 2. Parsers for SNUPI output files
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class SnupiNode:
    """One SNUPI FE node parsed from a ``*_STRCT.pdb`` file.

    SNUPI writes one ``ATOM`` line per node, named ``NN``, with the chain field
    holding the helix id (``H1``, ``H2``, …) and resSeq the per-helix node index.
    With ``PDB_OB_IND 1`` the occupancy column carries the node's RMSF (nm-scale
    values already; SNUPI stores RMSF directly, not the coordinate unit).
    """

    chain: str  # e.g. "H1"
    resseq: int  # per-helix node index, 1-based
    pos: np.ndarray  # (3,) position in nm
    rmsf: Optional[float] = None  # occupancy column (RMSF) if present


def parse_snupi_pdb(path: str | Path) -> List[SnupiNode]:
    """Parse a SNUPI ``*_STRCT.pdb`` (or ``*_MODE_*.pdb``) into ordered nodes.

    SNUPI's PDB is whitespace-delimited (not strict fixed-column), e.g.::

        ATOM      1 NN   H1      1     -97.116 -46.551 -55.165 3.2

    → chain ``H1``, resSeq ``1``, xyz in Angstrom, occupancy ``3.2`` (RMSF).
    Positions are converted to nm.  Node order in the returned list is the file
    order, which SNUPI keeps identical across INIT / STT / all MODE files.
    """
    nodes: List[SnupiNode] = []
    for line in Path(path).read_text().splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        tok = line.split()
        # ATOM serial name chain resseq x y z [occ] ...
        if len(tok) < 8:
            continue
        try:
            chain = tok[3]
            resseq = int(tok[4])
            x, y, z = float(tok[5]), float(tok[6]), float(tok[7])
        except (ValueError, IndexError):
            continue
        occ: Optional[float] = None
        if len(tok) >= 9:
            try:
                occ = float(tok[8])
            except ValueError:
                occ = None
        nodes.append(
            SnupiNode(
                chain=chain,
                resseq=resseq,
                pos=np.array([x, y, z]) / ANGSTROM_PER_NM,
                rmsf=occ,
            )
        )
    return nodes


def parse_snupi_xyz(path: str | Path) -> np.ndarray:
    """Parse a SNUPI ``.xyz`` (mode / REF config) → (N, 3) positions in nm.

    Format: line 1 = atom count, line 2 = comment/blank, then ``<sym> x y z``.
    """
    lines = Path(path).read_text().splitlines()
    if not lines:
        return np.zeros((0, 3))
    try:
        n = int(lines[0].strip())
    except ValueError:
        n = 0
    pos: List[List[float]] = []
    for line in lines[2:]:
        tok = line.split()
        if len(tok) < 4:
            continue
        try:
            pos.append([float(tok[1]), float(tok[2]), float(tok[3])])
        except ValueError:
            continue
    arr = np.array(pos, dtype=float) / ANGSTROM_PER_NM
    if n and len(arr) != n:
        # Tolerate a header/body mismatch but surface it to the caller via shape.
        pass
    return arr


def parse_snupi_mode_vector(
    out_dir: str | Path, basename: str, mode: int
) -> Optional[np.ndarray]:
    """Return SNUPI mode ``mode`` (1-based) as an (N, 3) displacement field, nm.

    SNUPI saves each mode as a perturbed config ``_NMA_MODE_{k}_p.xyz`` (and
    ``_m.xyz``) around ``_NMA_MODE_REF.xyz``.  The mode shape is the difference
    ``p − REF`` (falls back to ``p − m`` if REF is absent); its overall scale is
    irrelevant because MAC normalises it.
    """
    d = Path(out_dir)
    p = d / f"{basename}_NMA_MODE_{mode}_p.xyz"
    ref = d / f"{basename}_NMA_MODE_REF.xyz"
    m = d / f"{basename}_NMA_MODE_{mode}_m.xyz"
    if not p.exists():
        return None
    pp = parse_snupi_xyz(p)
    if ref.exists():
        base = parse_snupi_xyz(ref)
    elif m.exists():
        base = parse_snupi_xyz(m)
    else:
        return None
    if pp.shape != base.shape or pp.size == 0:
        return None
    return pp - base


# SNUPI's ``*_STT.mat`` (MATLAB v7.3 / HDF5) stores the full-precision NMA data
# under these keys — verified on a real 6HB run.  The low-precision PDB occupancy
# column is a DIFFERENT quantity; always prefer NMA_RMSF here for RMSF.
_MAT_KEYS = {
    "rmsf": "NMA_RMSF",  # (n_nodes, 1) per-node RMSF, nm
    "pearson_correlation": "NMA_CORR_PEARSON",  # (n, n)
    "generalized_correlation": "NMA_CORR_GENERAL",  # (n, n)
    "eigenvalues": "NMA_EIG_VAL",  # (1, n_modes) ascending, rigid removed
    "eigenvectors": "NMA_EIG_VEC",  # (n_modes, 6*n_nodes) per-node [tx,ty,tz,rx,ry,rz]
    "node_init": "NODE_INIT",  # (6, n_nodes)
    "node_finl": "NODE_FINL",
}


def parse_snupi_nma_mat(path: str | Path) -> dict:
    """Extract full-precision NMA data from a SNUPI ``*_STT.mat``.

    Reads RMSF, the Pearson + generalized bp-bp correlation matrices, the NMA
    eigenvalues (rigid modes already removed) and the 6-DOF-per-node eigenvectors.
    SNUPI writes v7.3 (HDF5) .mat files, so this uses ``h5py`` (an optional import
    — CI never sees a .mat); a v7 file falls back to ``scipy.io.loadmat``.  A
    missing key or unreadable file yields ``{}`` (never raises).

    Returned arrays are normalised to numpy's row-major convention:
      * ``rmsf``            (n_nodes,)
      * ``pearson_correlation`` / ``generalized_correlation`` (n_nodes, n_nodes)
      * ``eigenvalues``     (n_modes,) ascending
      * ``eigenvectors``    (n_modes, 6*n_nodes); node i's translational DOFs are
        columns ``6i, 6i+1, 6i+2`` — the same layout as the mimic's ``_nma_modes``.
    """
    path = Path(path)
    out: dict = {}
    if not path.exists():
        return out
    # v7.3 (HDF5) — SNUPI's default.
    try:
        import h5py  # optional; only present on the analysis machine

        with h5py.File(str(path), "r") as f:
            for name, key in _MAT_KEYS.items():
                if key not in f:
                    continue
                arr = np.array(f[key], dtype=float)
                out[name] = arr
        return _normalise_mat(out)
    except (ImportError, OSError):
        pass
    # v7 fallback.
    try:
        from scipy.io import loadmat

        m = loadmat(str(path), squeeze_me=True, struct_as_record=False)
        for name, key in _MAT_KEYS.items():
            if key in m:
                out[name] = np.asarray(m[key], dtype=float)
    except Exception:
        return {}
    return _normalise_mat(out)


def _normalise_mat(out: dict) -> dict:
    """Fix h5py's transposed axes so downstream code sees numpy conventions."""
    if "rmsf" in out:
        out["rmsf"] = out["rmsf"].ravel()
    if "eigenvalues" in out:
        out["eigenvalues"] = out["eigenvalues"].ravel()
    ev = out.get("eigenvectors")
    if ev is not None and ev.ndim == 2:
        # Want (n_modes, 6*n_nodes).  h5py yields exactly that for SNUPI's
        # (6*n_nodes, n_modes) MATLAB array; scipy yields the MATLAB shape.
        n_modes = out.get("eigenvalues")
        if n_modes is not None and ev.shape[1] == len(n_modes):
            ev = ev.T
        out["eigenvectors"] = ev
    return out


def snupi_translational_modes(mat: dict, n_modes: int) -> List[np.ndarray]:
    """Return the lowest ``n_modes`` SNUPI mode shapes as (n_nodes, 3) fields.

    Extracts each eigenvector's translational DOFs (per-node columns 0,1,2 of the
    6-DOF block) from ``mat['eigenvectors']`` — full precision, all modes, and the
    same node ordering as the PDB/INIT node list.
    """
    ev = mat.get("eigenvectors")
    if ev is None or ev.ndim != 2:
        return []
    n_dof = ev.shape[1]
    n_nodes = n_dof // 6
    modes = []
    for m in range(min(n_modes, ev.shape[0])):
        block = ev[m, : n_nodes * 6].reshape(n_nodes, 6)
        modes.append(block[:, :3].copy())
    return modes


# ══════════════════════════════════════════════════════════════════════════════
# 3. Output-directory discovery
# ══════════════════════════════════════════════════════════════════════════════


def find_snupi_output(output_root: str | Path, basename: str) -> Optional[Path]:
    """Return the newest ``OUTPUT/<basename>_[YYMMDD_HHMMSS]/`` dir, or None.

    The timestamp sorts lexically, so ``max`` picks the most recent run.
    """
    root = Path(output_root)
    cands = sorted(root.glob(f"{basename}_[[]*[]]"))
    if not cands:
        # glob's char-class escaping is finicky; fall back to a prefix scan.
        cands = sorted(p for p in root.glob(f"{basename}_*") if p.is_dir())
    return cands[-1] if cands else None


def snupi_output_files(out_dir: str | Path, basename: str) -> dict:
    """Map the SNUPI output files we consume for a given run directory."""
    d = Path(out_dir)
    return {
        "init_pdb": d / f"{basename}_INIT_STRCT.pdb",
        "stt_pdb": d / f"{basename}_STT_STRCT.pdb",
        "stt_mat": d / f"{basename}_STT.mat",
        "stt_res_mat": d / f"{basename}_STT_RES.mat",
        "ref_xyz": d / f"{basename}_NMA_MODE_REF.xyz",
        "log": d / f"{basename}.log",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. Node correspondence (the crux)
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class NodeMatch:
    """Result of matching SNUPI nodes ↔ mimic nodes.

    ``pairs`` are ``(snupi_index, mimic_index)`` into the respective node lists.
    Consumers MUST check ``ok`` before trusting any RMSD/RMSF/MAC computed from
    the pairs — a silently-bad match poisons every downstream number.
    """

    pairs: List[Tuple[int, int]] = field(default_factory=list)
    method: str = ""
    residual_nm: float = float("nan")
    n_snupi: int = 0
    n_mimic: int = 0
    n_matched: int = 0
    chain_to_helix: Dict[str, str] = field(default_factory=dict)
    rms_per_chain: Dict[str, float] = field(default_factory=dict)
    ok: bool = False
    reason: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def n_snupi_unmatched(self) -> int:
        return self.n_snupi - self.n_matched

    @property
    def n_mimic_unmatched(self) -> int:
        return self.n_mimic - self.n_matched


def _kabsch(A: np.ndarray, B: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """Optimal proper-rotation superposition of A onto B (both (N,3), matched).

    Returns ``(R, t, rmsd)`` such that ``A @ R.T + t ≈ B``.  Proper rotation only
    (reflections are physically wrong for a chiral structure).
    """
    ca, cb = A.mean(0), B.mean(0)
    Ac, Bc = A - ca, B - cb
    U, _, Vt = np.linalg.svd(Ac.T @ Bc)
    d = np.sign(np.linalg.det(U @ Vt))
    D = np.diag([1.0, 1.0, d])
    R = (U @ D @ Vt).T
    t = cb - ca @ R.T
    rmsd = float(np.sqrt(((Ac @ R.T - Bc) ** 2).sum(1).mean()))
    return R, t, rmsd


def _mutual_nn(A: np.ndarray, B: np.ndarray, cap: float) -> List[Tuple[int, int]]:
    """Mutual nearest-neighbour pairs between rows of A and B within ``cap`` nm.

    Only used to salvage boundary nodes AFTER a good global alignment, where the
    true partner sits at the alignment residual (~0.02 nm) — far closer than the
    0.34 nm bp spacing — so a capped mutual-NN is unambiguous.  Returns index
    pairs ``(ia, ib)``.
    """
    if len(A) == 0 or len(B) == 0:
        return []
    D = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2)  # (nA, nB)
    a_to_b = D.argmin(axis=1)
    b_to_a = D.argmin(axis=0)
    pairs = []
    for ia, ib in enumerate(a_to_b):
        if b_to_a[ib] == ia and D[ia, ib] <= cap:
            pairs.append((ia, ib))
    return pairs


def match_nodes(
    snupi_nodes: Sequence[SnupiNode],
    mimic_keys: Sequence[Tuple[str, int]],
    mimic_pos: np.ndarray,
    *,
    labels: Optional[Sequence[dict]] = None,
    residual_tol_nm: float = 1.5,
    min_coverage: float = 0.98,
    salvage_cap_nm: float = 0.25,
    chain_prefix: str = "H",
) -> NodeMatch:
    """Correspond SNUPI nodes to mimic ``(helix_id, global_bp)`` nodes.

    Primary path (``labels`` from ``export_cadnano_with_labels``): map each SNUPI
    chain ``H{k+1}`` to the k-th exported vstrand, and its resSeq ``j`` to that
    vstrand's j-th duplex bp — an *ordered* correspondence, since adjacent bp are
    only 0.34 nm apart and cannot be told apart by distance.  A single global
    Kabsch then (a) auto-resolves a per-helix ascending/descending flip and
    (b) gives the residual used as a global-alignment sanity gate.  If ``labels``
    is None or the topological match fails validation, falls back to
    ``match_nodes_spatial``.

    Validation for ``ok=True``: every chain mapped to a single helix with matching
    node count, a bijective pairing, and global residual ≤ ``residual_tol_nm``.
    """
    n_s = len(snupi_nodes)
    snupi_pos = np.array([nd.pos for nd in snupi_nodes]) if n_s else np.zeros((0, 3))
    mimic_pos = np.asarray(mimic_pos, dtype=float)
    n_m = len(mimic_keys)
    result = NodeMatch(method="topological", n_snupi=n_s, n_mimic=n_m)

    if labels is None:
        return match_nodes_spatial(
            snupi_nodes,
            mimic_keys,
            mimic_pos,
            residual_tol_nm=residual_tol_nm,
            chain_prefix=chain_prefix,
        )

    mimic_index = {tuple(k): i for i, k in enumerate(mimic_keys)}

    # Group SNUPI nodes by chain, ordered by resSeq.
    by_chain: Dict[str, List[int]] = {}
    for si, nd in enumerate(snupi_nodes):
        by_chain.setdefault(nd.chain, []).append(si)
    for c in by_chain:
        by_chain[c].sort(key=lambda si: snupi_nodes[si].resseq)

    # Build per-chain candidate correspondences (mi list in ascending-base order).
    chain_blocks: List[Tuple[str, List[int], List[int]]] = []
    warnings: List[str] = []
    for lab in labels:
        chain = f"{chain_prefix}{lab['snupi_chain_index'] + 1}"
        duplex = [b for b in lab["bases"] if b.get("duplex")]
        s_idx = by_chain.get(chain, [])
        if len(s_idx) != len(duplex):
            warnings.append(
                f"{chain}: SNUPI has {len(s_idx)} nodes, topology has {len(duplex)} "
                f"duplex bp — chain left unmatched"
            )
            continue
        mi_list: List[int] = []
        missing = False
        for b in duplex:
            key = (lab["helix_id"], int(b["global_bp"]))
            mi = mimic_index.get(key)
            if mi is None:
                missing = True
                break
            mi_list.append(mi)
        if missing:
            warnings.append(f"{chain}: mimic mesh missing a mapped (helix, bp) node")
            continue
        chain_blocks.append((chain, s_idx, mi_list))
        result.chain_to_helix[chain] = lab["helix_id"]

    corr0 = [
        (si, mi) for _, s_idx, mi_list in chain_blocks for si, mi in zip(s_idx, mi_list)
    ]
    if len(corr0) < 4:
        result.reason = "too few topological pairs to align"
        result.warnings = warnings
        return match_nodes_spatial(
            snupi_nodes,
            mimic_keys,
            mimic_pos,
            residual_tol_nm=residual_tol_nm,
            chain_prefix=chain_prefix,
        )

    # Global Kabsch: align mimic onto SNUPI over the ascending correspondence.
    A = mimic_pos[[mi for _, mi in corr0]]
    B = snupi_pos[[si for si, _ in corr0]]
    R, t, _ = _kabsch(A, B)
    mimic_aln = mimic_pos @ R.T + t

    # Per-chain ascending/descending flip resolution under the global fit.
    final: List[Tuple[int, int]] = []
    for chain, s_idx, mi_list in chain_blocks:
        asc = list(zip(s_idx, mi_list))
        desc = list(zip(s_idx, list(reversed(mi_list))))

        def _rms(pl: List[Tuple[int, int]]) -> float:
            d = snupi_pos[[si for si, _ in pl]] - mimic_aln[[mi for _, mi in pl]]
            return float(np.sqrt((d * d).sum(1).mean()))

        ra, rd = _rms(asc), _rms(desc)
        chosen = asc if ra <= rd else desc
        result.rms_per_chain[chain] = round(min(ra, rd), 4)
        final.extend(chosen)

    # Re-fit on the resolved correspondence for the transform + reported residual.
    A = mimic_pos[[mi for _, mi in final]]
    B = snupi_pos[[si for si, _ in final]]
    R, t, res = _kabsch(A, B)

    # Salvage boundary nodes on the chains that had a count mismatch: a crossover
    # can attribute a few bp to a different helix in SNUPI than in NADOC's duplex
    # convention, so those chains were skipped whole.  The leftover SNUPI and
    # mimic nodes are the SAME physical bp (just relabeled), so under the now-known
    # transform a capped mutual-NN pairs them unambiguously.
    used_s = {si for si, _ in final}
    used_m = {mi for _, mi in final}
    left_s = [si for si in range(n_s) if si not in used_s]
    left_m = [mi for mi in range(n_m) if mi not in used_m]
    if left_s and left_m:
        mimic_aln_left = mimic_pos[left_m] @ R.T + t
        for ia, ib in _mutual_nn(snupi_pos[left_s], mimic_aln_left, salvage_cap_nm):
            final.append((left_s[ia], left_m[ib]))
        if final:
            A = mimic_pos[[mi for _, mi in final]]
            B = snupi_pos[[si for si, _ in final]]
            _, _, res = _kabsch(A, B)

    mis = [mi for _, mi in final]
    bijective = len(set(mis)) == len(mis)
    coverage = len(final) / n_s if n_s else 0.0
    result.pairs = final
    result.n_matched = len(final)
    result.residual_nm = round(res, 4)
    result.warnings = warnings
    if not bijective:
        result.reason = "topological pairing is not bijective (a mimic node reused)"
    elif res > residual_tol_nm:
        result.reason = (
            f"global residual {res:.2f} nm exceeds tol {residual_tol_nm} nm — "
            f"alignment suspect, match not trusted"
        )
    elif coverage < min_coverage:
        result.reason = (
            f"coverage {coverage:.1%} < {min_coverage:.0%} "
            f"({result.n_snupi_unmatched} SNUPI / {result.n_mimic_unmatched} mimic "
            f"nodes unmatched) — see warnings"
        )
    else:
        result.ok = True
        result.reason = "topological match validated" + (
            f" ({result.n_snupi_unmatched} boundary node(s) salvaged-or-dropped; "
            f"coverage {coverage:.1%})"
            if warnings
            else ""
        )
    return result


def match_nodes_spatial(
    snupi_nodes: Sequence[SnupiNode],
    mimic_keys: Sequence[Tuple[str, int]],
    mimic_pos: np.ndarray,
    *,
    residual_tol_nm: float = 1.5,
    chain_prefix: str = "H",
) -> NodeMatch:
    """Label-free fallback: establish chain↔helix by centroid alignment, then
    order nodes *within* each helix along its axis (never free nearest-neighbour,
    which fails at 0.34 nm bp spacing).

    Robust to a global rigid transform + unit scale, and to the 4 proper-rotation
    sign ambiguities of a PCA frame; it CANNOT recover which physical helix a
    symmetric bundle's chain is (that needs the topological labels) — it reports
    ``ok`` only when the alignment residual gate passes and counts are consistent.
    """
    n_s = len(snupi_nodes)
    snupi_pos = np.array([nd.pos for nd in snupi_nodes]) if n_s else np.zeros((0, 3))
    mimic_pos = np.asarray(mimic_pos, dtype=float)
    n_m = len(mimic_keys)
    result = NodeMatch(method="spatial", n_snupi=n_s, n_mimic=n_m)
    if n_s < 4 or n_m < 4:
        result.reason = "too few nodes for spatial matching"
        return result

    # Group by chain (SNUPI) and helix (mimic).
    s_by_chain: Dict[str, List[int]] = {}
    for si, nd in enumerate(snupi_nodes):
        s_by_chain.setdefault(nd.chain, []).append(si)
    m_by_helix: Dict[str, List[int]] = {}
    for mi, k in enumerate(mimic_keys):
        m_by_helix.setdefault(k[0], []).append(mi)
    # Order mimic nodes within a helix by global_bp so "along the axis" is defined.
    for h in m_by_helix:
        m_by_helix[h].sort(key=lambda mi: mimic_keys[mi][1])

    s_chains = list(s_by_chain)
    m_helices = list(m_by_helix)
    s_cent = {c: snupi_pos[s_by_chain[c]].mean(0) for c in s_chains}
    m_cent = {h: mimic_pos[m_by_helix[h]].mean(0) for h in m_helices}

    # Best global transform: center + PCA-align both centroid clouds, search the
    # 4 proper-rotation sign flips, score by count-constrained centroid NN.
    Sc = np.array([s_cent[c] for c in s_chains])
    Mc = np.array([m_cent[h] for h in m_helices])
    s_counts = np.array([len(s_by_chain[c]) for c in s_chains])
    m_counts = np.array([len(m_by_helix[h]) for h in m_helices])
    Sm, Mm = Sc.mean(0), Mc.mean(0)
    _, _, Vs = np.linalg.svd(Sc - Sm)
    _, _, Vm = np.linalg.svd(Mc - Mm)
    best = None
    for sx in (1, -1):
        for sy in (1, -1):
            sz = sx * sy  # keep det(+1)
            Rm = np.diag([sx, sy, sz]) @ Vm
            R = Vs.T @ Rm  # maps mimic-centroid frame → snupi-centroid frame
            Mc_al = (Mc - Mm) @ R.T + Sm
            # Greedy count-constrained assignment mimic-helix → snupi-chain.
            assign: Dict[str, str] = {}
            used = set()
            total = 0.0
            for hi, h in enumerate(m_helices):
                best_c, best_d = None, np.inf
                for ci, c in enumerate(s_chains):
                    if c in used or s_counts[ci] != m_counts[hi]:
                        continue
                    d = float(np.linalg.norm(Mc_al[hi] - Sc[ci]))
                    if d < best_d:
                        best_d, best_c = d, c
                if best_c is not None:
                    assign[h] = best_c
                    used.add(best_c)
                    total += best_d
            if assign and (best is None or total < best[0]):
                best = (total, assign)
    if best is None:
        result.reason = "no count-consistent centroid assignment"
        return result

    _, assign = best
    pairs: List[Tuple[int, int]] = []
    for h, c in assign.items():
        result.chain_to_helix[c] = h
        s_idx = s_by_chain[c]  # ordered by resseq
        m_idx = m_by_helix[h]  # ordered by global_bp
        # Resolve direction by comparing endpoint separation both ways (after a
        # provisional whole-cloud alignment is unavailable here, use raw distance
        # between the two orderings' endpoints — colinear helix makes this safe).
        asc = list(zip(s_idx, m_idx))
        desc = list(zip(s_idx, list(reversed(m_idx))))

        def _end_gap(pl: List[Tuple[int, int]]) -> float:
            si0, mi0 = pl[0]
            si1, mi1 = pl[-1]
            v_s = snupi_pos[si1] - snupi_pos[si0]
            v_m = mimic_pos[mi1] - mimic_pos[mi0]
            v_s = v_s / (np.linalg.norm(v_s) + 1e-9)
            v_m = v_m / (np.linalg.norm(v_m) + 1e-9)
            return -float(v_s @ v_m)  # smaller (more negative→) better aligned

        pairs.extend(asc if _end_gap(asc) <= _end_gap(desc) else desc)

    if len(pairs) < 4:
        result.reason = "spatial matching produced too few pairs"
        return result
    A = mimic_pos[[mi for _, mi in pairs]]
    B = snupi_pos[[si for si, _ in pairs]]
    _, _, res = _kabsch(A, B)
    mis = [mi for _, mi in pairs]
    result.pairs = pairs
    result.n_matched = len(pairs)
    result.residual_nm = round(res, 4)
    if len(set(mis)) != len(mis):
        result.reason = "spatial pairing not bijective"
    elif res > residual_tol_nm:
        result.reason = (
            f"spatial residual {res:.2f} nm exceeds tol {residual_tol_nm} nm"
        )
    else:
        result.ok = True
        result.reason = "spatial match validated (chain identity NOT label-verified)"
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 5. Observable agreement (given a validated match)
# ══════════════════════════════════════════════════════════════════════════════


def shape_rmsd_nm(
    snupi_pos: np.ndarray, mimic_pos: np.ndarray, pairs: Sequence[Tuple[int, int]]
) -> Optional[float]:
    """Kabsch RMSD (nm) between matched SNUPI and mimic node positions."""
    if len(pairs) < 4:
        return None
    B = np.asarray(snupi_pos)[[si for si, _ in pairs]]
    A = np.asarray(mimic_pos)[[mi for _, mi in pairs]]
    _, _, rmsd = _kabsch(A, B)
    return round(rmsd, 4)


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / denom) if denom > 0 else float("nan")


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return _pearson(ra, rb)


def rmsf_agreement(
    snupi_rmsf: Sequence[Optional[float]],
    mimic_rmsf: Sequence[float],
    pairs: Sequence[Tuple[int, int]],
) -> dict:
    """Pearson/Spearman of the per-node RMSF pattern over matched nodes."""
    xs, ys = [], []
    for si, mi in pairs:
        s = snupi_rmsf[si]
        if s is None:
            continue
        xs.append(float(s))
        ys.append(float(mimic_rmsf[mi]))
    if len(xs) < 4:
        return {"pearson": None, "spearman": None, "n": len(xs)}
    a, b = np.array(xs), np.array(ys)
    return {
        "pearson": round(_pearson(a, b), 4),
        "spearman": round(_spearman(a, b), 4),
        "n": len(xs),
        "snupi_mean_nm": round(float(a.mean()), 4),
        "mimic_mean_nm": round(float(b.mean()), 4),
    }


def rigid_body_fraction(field: np.ndarray, positions: np.ndarray) -> float:
    """Fraction of a displacement field's energy in the 6D rigid-body subspace.

    ``field`` and ``positions`` are (N, 3) over the SAME nodes.  Builds the 3
    translation + 3 rotation basis vectors, orthonormalises, and returns the
    projected energy fraction in [0, 1].  ~1.0 ⇒ a rigid-body motion.

    SNUPI's free-free NMA does NOT hard-project the 6 zero-frequency rigid modes,
    so its lowest saved modes are rigid-body residuals (eigval ~1e7, PR≈1) with no
    elastic counterpart in the mimic (which drops all 6 rigid modes) — filtering
    them out is what makes the MAC an elastic-to-elastic comparison.
    """
    P = np.asarray(positions, dtype=float)
    Pc = P - P.mean(0)
    basis = [np.tile(e, (len(P), 1)) for e in np.eye(3)]
    basis += [np.cross(ax, Pc) for ax in np.eye(3)]
    Q, _ = np.linalg.qr(np.array([b.ravel() for b in basis]).T)
    v = np.asarray(field, dtype=float).ravel()
    nv = np.linalg.norm(v)
    if nv == 0:
        return 0.0
    v = v / nv
    proj = Q.T @ v
    return float(proj @ proj)


def mac_matrix(
    snupi_modes: Sequence[np.ndarray],
    mimic_phi: np.ndarray,
    pairs: Sequence[Tuple[int, int]],
) -> dict:
    """Modal Assurance Criterion between SNUPI and mimic mode shapes.

    ``snupi_modes[i]`` is an (N_snupi, 3) translational displacement field (from
    ``parse_snupi_mode_vector``).  ``mimic_phi`` is the mimic's (6·N_mimic, K)
    eigenvector matrix (``_nma_modes`` return): node ``mi``'s translational DOFs
    are rows ``6*mi, 6*mi+1, 6*mi+2``.  For each SNUPI mode s and mimic mode j::

        MAC = (φ_s·φ_m)² / (|φ_s|² |φ_m|²)

    computed on the matched translational DOFs only, so it is invariant to mode
    sign and overall scale.  Returns the full matrix plus the greedy best mimic
    mode (and its MAC) for each SNUPI mode — the headline "does the mimic capture
    SNUPI's lowest bending/torsion modes" number.
    """
    if not pairs or not len(snupi_modes):
        return {"matrix": [], "assignment": []}
    s_idx = np.array([si for si, _ in pairs])
    m_idx = np.array([mi for _, mi in pairs])
    trans_rows = np.stack([6 * m_idx, 6 * m_idx + 1, 6 * m_idx + 2], axis=1).ravel()
    K = mimic_phi.shape[1]
    # Mimic mode vectors on matched translational DOFs: (K, 3m)
    mimic_vecs = mimic_phi[trans_rows, :].T  # (K, 3m)
    mimic_norm = np.linalg.norm(mimic_vecs, axis=1)

    matrix: List[List[float]] = []
    assignment: List[dict] = []
    for s, mode in enumerate(snupi_modes):
        phi_s = np.asarray(mode)[s_idx].ravel()  # (3m,)
        ns = np.linalg.norm(phi_s)
        row: List[float] = []
        for j in range(K):
            phi_m = mimic_vecs[j]
            denom = ns * mimic_norm[j]
            mac = float((phi_s @ phi_m) ** 2 / (denom**2)) if denom > 0 else 0.0
            row.append(round(mac, 4))
        matrix.append(row)
        best_j = int(np.argmax(row)) if row else -1
        assignment.append(
            {
                "snupi_mode": s + 1,
                "best_mimic_mode": best_j + 1,
                "mac": row[best_j] if row else None,
            }
        )
    return {"matrix": matrix, "assignment": assignment}


def _symmetrize(C: np.ndarray) -> np.ndarray:
    """Return a full symmetric matrix from ``C``.

    SNUPI stores its NMA correlation matrices **lower-triangular only** (upper
    triangle and diagonal are zero); the mimic's are already full+symmetric.
    ``C + C.T`` reconstructs the full matrix from a triangular one and merely
    scales an already-symmetric one by 2 (Pearson is scale-invariant, and the
    diagonal is excluded downstream), so this is correct for both.
    """
    C = np.asarray(C, dtype=float)
    return C + C.T


def correlation_agreement(
    snupi_corr: np.ndarray,
    mimic_corr: np.ndarray,
    pairs: Sequence[Tuple[int, int]],
) -> dict:
    """Off-diagonal Pearson agreement of two bp-bp correlation matrices over the
    matched node submatrix.  Both are reordered to the common matched-node order
    and symmetrized (SNUPI stores only the lower triangle).
    """
    snupi_corr = _symmetrize(snupi_corr)
    mimic_corr = _symmetrize(mimic_corr)
    s_idx = np.array([si for si, _ in pairs])
    m_idx = np.array([mi for _, mi in pairs])
    if snupi_corr.shape[0] <= s_idx.max(initial=-1) or mimic_corr.shape[0] <= m_idx.max(
        initial=-1
    ):
        return {
            "pearson": None,
            "n": 0,
            "reason": "index out of range for a corr matrix",
        }
    S = snupi_corr[np.ix_(s_idx, s_idx)]
    M = mimic_corr[np.ix_(m_idx, m_idx)]
    iu = np.triu_indices(len(s_idx), k=1)
    a, b = S[iu], M[iu]
    if len(a) < 4:
        return {"pearson": None, "n": len(a)}
    return {"pearson": round(_pearson(a, b), 4), "n": int(len(a))}


# ══════════════════════════════════════════════════════════════════════════════
# 6. Self-consistency (parse-fidelity <0.1%) + unit-free persistence length
# ══════════════════════════════════════════════════════════════════════════════
#
# SNUPI outputs both the raw NMA data (eigenvalues + eigenvectors) AND the derived
# quantities (RMSF, correlation matrices).  Reconstructing the derived quantities
# from the raw with SNUPI's own formula must match SNUPI's stored values to machine
# precision — a per-run guard that our parsing/units/DOF-layout are faithful before
# any mimic-vs-SNUPI number is trusted.


def _median_pct(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, float).ravel()
    b = np.asarray(b, float).ravel()
    m = np.abs(b) > 1e-9
    return (
        float(np.median(np.abs(a[m] - b[m]) / np.abs(b[m])) * 100)
        if m.any()
        else float("nan")
    )


def _trans_dof(n_nodes: int) -> np.ndarray:
    tr = np.empty(3 * n_nodes, dtype=int)
    tr[0::3] = 6 * np.arange(n_nodes)
    tr[1::3] = 6 * np.arange(n_nodes) + 1
    tr[2::3] = 6 * np.arange(n_nodes) + 2
    return tr


def reconstruct_rmsf(
    eigenvalues,
    eigenvectors,
    n_nodes: int,
    *,
    n_rigid: int = SNUPI_N_RIGID,
    kbt: float = KBT_300K,
) -> np.ndarray:
    """SNUPI's per-node RMSF (nm) from its own modes: sqrt(kBT·Σ φ²/λ) over the
    elastic modes (the first ``n_rigid`` dropped).  ``eigenvectors`` is (n_modes,
    6·n_nodes) — the ``parse_snupi_nma_mat`` layout, per-node [tx,ty,tz,rx,ry,rz]."""
    lam = np.asarray(eigenvalues, float).ravel()[n_rigid:]
    phi = np.asarray(eigenvectors, float)[n_rigid:, :]  # (m, 6N)
    var = np.zeros(n_nodes)
    for dim in range(3):
        cols = phi[:, 6 * np.arange(n_nodes) + dim]  # (m, N)
        var += kbt * np.sum(cols**2 / lam[:, None], axis=0)
    return np.sqrt(np.clip(var, 0.0, None))


def reconstruct_pearson_correlation(
    eigenvalues, eigenvectors, n_nodes: int, *, n_rigid: int = SNUPI_N_RIGID
) -> np.ndarray:
    """SNUPI's bp-bp Pearson DCCM from its own modes (kBT cancels)."""
    lam = np.asarray(eigenvalues, float).ravel()[n_rigid:]
    phi = np.asarray(eigenvectors, float)[n_rigid:, :]  # (m, 6N)
    tr = _trans_dof(n_nodes)
    psi = (phi[:, tr].T / np.sqrt(lam)[None, :]).reshape(n_nodes, 3, -1)
    cov = np.einsum("idm,jdm->ij", psi, psi)
    d = np.sqrt(np.clip(np.diag(cov), 1e-30, None))
    return np.clip(cov / np.outer(d, d), -1.0, 1.0)


def self_consistency(mat: dict, *, n_rigid: int = SNUPI_N_RIGID) -> dict:
    """Reconstruct SNUPI's RMSF + Pearson DCCM from its stored eigenvalues +
    eigenvectors and compare to its stored NMA_RMSF / NMA_CORR_PEARSON.  Proves
    our parse (units, 300 K kBT, DOF layout, node order, rigid-mode count) is
    faithful — expected agreement is machine precision.  Returns ``ok`` True when
    RMSF matches < 0.1 % and Pearson off-diagonal matches < 1e-6.
    """
    ev, vec = mat.get("eigenvalues"), mat.get("eigenvectors")
    out: dict = {"ok": False}
    if ev is None or vec is None or vec.ndim != 2:
        out["reason"] = "no eigen data in .mat"
        return out
    n = vec.shape[1] // 6
    stored_rmsf = mat.get("rmsf")
    if stored_rmsf is not None and len(stored_rmsf) == n:
        out["rmsf_median_pct"] = round(
            _median_pct(reconstruct_rmsf(ev, vec, n, n_rigid=n_rigid), stored_rmsf), 6
        )
    stored_cp = mat.get("pearson_correlation")
    if stored_cp is not None and stored_cp.shape[0] == n:
        rec = reconstruct_pearson_correlation(ev, vec, n, n_rigid=n_rigid)
        S = np.asarray(stored_cp) + np.asarray(stored_cp).T  # SNUPI stores lower-tri
        iu = np.triu_indices(n, 1)
        out["pearson_median_abs"] = float(np.median(np.abs(rec[iu] - S[iu])))
    out["ok"] = (
        out.get("rmsf_median_pct", 1e9) < 0.1
        and out.get("pearson_median_abs", 1e9) < 1e-6
    )
    return out


def bending_amplitude_variance(
    eigenvalues,
    eigenvectors,
    positions,
    *,
    n_rigid: int = SNUPI_N_RIGID,
    kbt: float = KBT_300K,
):
    """⟨a₁²⟩ (nm²): thermal variance of the fundamental free-free bending amplitude.

    Projects the physical NMA displacement covariance onto the analytic free-free
    Euler–Bernoulli fundamental bending shape ψ₁(ξ) along the PCA long axis (both
    transverse planes, averaged).  Returns ``(a1_var_nm2, bundle_length_nm)``.

    This is the unit-free basis for an apples-to-apples persistence length:
    ``L_p ∝ L³ / ⟨a₁²⟩``, so ``L_p_snupi = L_p_mimic · (⟨a₁²⟩_mimic / ⟨a₁²⟩_snupi)``
    (bundle lengths ≈ equal) sidesteps the two engines' differing internal units —
    only physical fluctuation amplitudes (nm) enter.  ``eigenvectors`` (n_modes,
    6·N); ``positions`` (N, 3) in the same node order.
    """
    lam = np.asarray(eigenvalues, float).ravel()[n_rigid:]
    phi = np.asarray(eigenvectors, float)[n_rigid:, :]  # (m, 6N)
    P = np.asarray(positions, float)
    n = len(P)
    ctr = P - P.mean(0)
    Vt = np.linalg.svd(ctr, full_matrices=False)[2]
    axis, e1, e2 = Vt[0], Vt[1], Vt[2]
    x = ctr @ axis
    L = float(x.max() - x.min())
    xi = (x - x.min()) / max(L, 1e-12)
    bl = _EB_BETA1_L
    sig = (np.cosh(bl) - np.cos(bl)) / (np.sinh(bl) - np.sin(bl))
    bb = bl * xi
    shp = np.cosh(bb) + np.cos(bb) - sig * (np.sinh(bb) + np.sin(bb))
    shp = shp / np.sqrt(np.mean(shp**2))  # RMS-normalised

    def _av(vec_field: np.ndarray) -> float:
        p = np.zeros(6 * n)
        idx = 6 * np.arange(n)
        p[idx] = vec_field[:, 0]
        p[idx + 1] = vec_field[:, 1]
        p[idx + 2] = vec_field[:, 2]
        proj = phi @ p  # (m,)
        return float(kbt * np.sum(proj**2 / lam))

    a1 = 0.5 * (_av(shp[:, None] * e1) + _av(shp[:, None] * e2))
    return a1, L
