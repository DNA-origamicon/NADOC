"""Reusable KIMMDY-style CPD analysis for arbitrary NADOC NAMD designs.

This module generalises two older, design-specific workflows:

* AutoNAMD's broad cross-strand pyrimidine proximity scan followed by one KIMMDY
  invocation per hand-selected pair; and
* ``kimmdy-namd-cpd``'s reusable C5/C6 geometry and geometric-propensity model.

The implementation here is analysis-only.  It never changes a topology and does not
interpret the dimensionless KIMMDY geometric propensity as an absolute rate or yield.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from backend.core import cpd_metrics

SCHEMA = "nadoc.kimmdy-analysis.v1"
SERIES_SCHEMA = "nadoc.kimmdy-series.v1"
THYMINE_RESNAMES = frozenset({"DT", "DT3", "DT5", "THY", "THY3", "THY5", "T"})
PAIR_MODES = frozenset({"designed", "all-tt", "explicit"})
PAIR_SCOPES = frozenset({"all", "interstrand", "intrastrand"})
RATE_MODELS = frozenset({"periodic", "upstream"})


@dataclass(frozen=True)
class AnalysisSource:
    """Fully resolved input paths for one analysis invocation."""

    design_path: Path
    topology_path: Path
    trajectory_paths: tuple[Path, ...]
    output_dir: Path
    job_dir: Path | None = None
    package_dir: Path | None = None


def _continuation_key(path: Path) -> tuple[str, int]:
    match = re.search(r"\.cont(\d+)\.dcd$", path.name)
    base = re.sub(r"\.cont\d+\.dcd$", ".dcd", path.name)
    return base, 0 if match is None else int(match.group(1)) + 1


def _default_job_trajectories(package_dir: Path) -> list[Path]:
    output = package_dir / "output"
    paths = sorted(output.glob("*production*.dcd"), key=_continuation_key)
    if not paths:
        paths = sorted(output.glob("*.dcd"), key=_continuation_key)
    groups: dict[str, list[Path]] = {}
    for path in paths:
        groups.setdefault(_continuation_key(path)[0], []).append(path)
    if len(groups) > 1:
        examples = ", ".join(sorted(groups)[:5])
        raise ValueError(
            "job output contains multiple independent DCD series "
            f"({examples}); pass the intended base DCD and its continuations with --dcd"
        )
    return paths


def resolve_analysis_source(
    *,
    job_dir: Path | None = None,
    design_path: Path | None = None,
    topology_path: Path | None = None,
    trajectory_paths: Sequence[Path] = (),
    output_dir: Path | None = None,
) -> AnalysisSource:
    """Resolve either a managed NADOC job or explicit design/topology/trajectory paths.

    Managed jobs default to production DCD pieces in their manifest package.  Explicit
    DCD arguments always win, which also makes archived or branched trajectories usable.
    """

    if job_dir is not None:
        job_dir = Path(job_dir).resolve()
        job_path = job_dir / "job.json"
        if not job_path.is_file():
            raise FileNotFoundError(f"managed job has no job.json: {job_dir}")
        metadata = json.loads(job_path.read_text())
        package_subdir = metadata.get("package_subdir")
        stem = metadata.get("name_stem")
        if not package_subdir or not stem:
            raise ValueError("job.json has no prepared package_subdir/name_stem")
        package_dir = (job_dir / package_subdir).resolve()
        resolved_design = (
            Path(design_path).resolve() if design_path else job_dir / "design.json"
        )
        if topology_path:
            resolved_topology = Path(topology_path).resolve()
        else:
            choices = [package_dir / f"{stem}_hmr.psf", package_dir / f"{stem}.psf"]
            resolved_topology = next(
                (path for path in choices if path.is_file()), choices[-1]
            )
        resolved_trajectories = tuple(
            Path(path).resolve()
            for path in (trajectory_paths or _default_job_trajectories(package_dir))
        )
        resolved_output = (
            Path(output_dir).resolve()
            if output_dir
            else job_dir / "analysis" / "kimmdy"
        )
        source = AnalysisSource(
            design_path=resolved_design,
            topology_path=resolved_topology,
            trajectory_paths=resolved_trajectories,
            output_dir=resolved_output,
            job_dir=job_dir,
            package_dir=package_dir,
        )
    else:
        if design_path is None or topology_path is None or not trajectory_paths:
            raise ValueError(
                "explicit analysis requires design_path, topology_path, and trajectory_paths"
            )
        source = AnalysisSource(
            design_path=Path(design_path).resolve(),
            topology_path=Path(topology_path).resolve(),
            trajectory_paths=tuple(Path(path).resolve() for path in trajectory_paths),
            output_dir=(
                Path(output_dir).resolve()
                if output_dir
                else Path.cwd() / "kimmdy_analysis"
            ),
        )

    missing = [source.design_path, source.topology_path]
    missing.extend(source.trajectory_paths)
    absent = [str(path) for path in missing if not path.is_file()]
    if absent:
        raise FileNotFoundError("missing KIMMDY analysis inputs: " + ", ".join(absent))
    if not source.trajectory_paths:
        raise FileNotFoundError("no trajectory DCDs found; pass --dcd explicitly")
    return source


def sample_frame_indices(
    n_total: int,
    *,
    start: int = 0,
    stop: int | None = None,
    stride: int = 1,
    max_frames: int | None = None,
) -> list[int]:
    """Sample a bounded set spanning the complete requested interval.

    ``max_frames`` widens the step; it never truncates to the beginning of a run.
    """

    lo = max(0, int(start))
    hi = n_total if stop is None else min(n_total, max(lo, int(stop)))
    step = max(1, int(stride))
    frames = list(range(lo, hi, step))
    if frames and frames[-1] != hi - 1:
        frames.append(hi - 1)
    if max_frames is not None and max_frames > 0 and len(frames) > int(max_frames):
        cap = int(max_frames)
        if cap == 1:
            frames = [frames[0]]
        else:
            positions = np.linspace(0, len(frames) - 1, cap).round().astype(int)
            frames = [frames[int(position)] for position in positions]
    return sorted(set(frames))


def parse_pair_spec(value: str) -> tuple[tuple[str, int], tuple[str, int]]:
    """Parse ``SEGID:RESID~SEGID:RESID`` (``-`` is also accepted)."""

    match = re.fullmatch(r"\s*([^:\s~]+):(\d+)\s*(?:~|-)\s*([^:\s~]+):(\d+)\s*", value)
    if not match:
        raise ValueError(f"invalid pair {value!r}; expected SEGID:RESID~SEGID:RESID")
    return (match.group(1), int(match.group(2))), (match.group(3), int(match.group(4)))


def _design_residue_map(design: Any) -> dict[tuple[str, int], dict]:
    """Best-effort NADOC identity for ordinary and crossover-insert residues."""

    from backend.core import junction_topology as jt
    from backend.core.namd_topology import psfgen_dna_segids_for_design

    junctions = jt._junction_index(design)
    segids = psfgen_dna_segids_for_design(len(design.strands))
    out: dict[tuple[str, int], dict] = {}
    for strand_index, strand in enumerate(design.strands):
        segid = segids[strand_index]
        resid = 0
        for domain_index, domain in enumerate(strand.domains):
            step = 1 if domain.end_bp >= domain.start_bp else -1
            for bp in range(domain.start_bp, domain.end_bp + step, step):
                resid += 1
                out[(segid, resid)] = {
                    "strand_id": strand.id,
                    "helix_id": domain.helix_id,
                    "bp_index": int(bp),
                    "direction": jt._dir_value(domain.direction),
                    "kind": "base",
                }
            if domain_index + 1 >= len(strand.domains):
                continue
            nxt = strand.domains[domain_index + 1]
            key_a = (domain.helix_id, domain.end_bp, jt._dir_value(domain.direction))
            key_b = (nxt.helix_id, nxt.start_bp, jt._dir_value(nxt.direction))
            crossover_id, extra = junctions.get(frozenset((key_a, key_b)), (None, ""))
            for insert_k, base in enumerate(extra):
                resid += 1
                out[(segid, resid)] = {
                    "strand_id": strand.id,
                    "kind": "crossover_insert",
                    "crossover_id": crossover_id,
                    "extra_base_k": insert_k,
                    "design_base": base,
                    "from_helix": domain.helix_id,
                    "from_bp": int(domain.end_bp),
                    "to_helix": nxt.helix_id,
                    "to_bp": int(nxt.start_bp),
                }
    return out


def topology_thymine_sites(universe: Any, design: Any | None = None) -> list[dict]:
    """Return uniquely paired C5/C6 atoms for every topology thymine residue."""

    design_map = _design_residue_map(design) if design is not None else {}
    sites: list[dict] = []
    for residue in universe.residues:
        resname = str(residue.resname).upper()
        if resname not in THYMINE_RESNAMES:
            continue
        c5 = residue.atoms.select_atoms("name C5")
        c6 = residue.atoms.select_atoms("name C6")
        if len(c5) != 1 or len(c6) != 1:
            continue
        segid = str(residue.segid)
        resid = int(residue.resid)
        public = {
            "site_id": f"{segid}:{resid}",
            "label": f"{segid}:{resname}{resid}",
            "segid": segid,
            "resid": resid,
            "resname": resname,
            "resindex": int(residue.ix),
            "c5_serial": int(c5[0].index),
            "c6_serial": int(c6[0].index),
            "design_identity": design_map.get((segid, resid)),
        }
        sites.append(public)
    sites.sort(key=lambda site: (site["segid"], site["resid"], site["resindex"]))
    return sites


def _pair_key(index_a: int, index_b: int) -> tuple[int, int]:
    return (index_a, index_b) if index_a < index_b else (index_b, index_a)


def _candidate(site_a: dict, site_b: dict, *, intended: dict | None = None) -> dict:
    return {
        "id": f"{site_a['site_id']}~{site_b['site_id']}",
        "label": f"{site_a['label']}~{site_b['label']}",
        "site_a": site_a,
        "site_b": site_b,
        "same_strand": site_a["segid"] == site_b["segid"],
        "sequence_separation": (
            abs(site_a["resid"] - site_b["resid"])
            if site_a["segid"] == site_b["segid"]
            else None
        ),
        "intended_weld": intended is not None,
        "intended_weld_identity": intended,
    }


def _designed_candidate_map(
    design: Any, sites: Sequence[dict]
) -> tuple[dict[tuple[int, int], dict], list[dict]]:
    by_residue = {
        (site["segid"], site["resid"]): (index, site)
        for index, site in enumerate(sites)
    }
    mapped: dict[tuple[int, int], dict] = {}
    excluded: list[dict] = []
    for weld in cpd_metrics.designed_weld_pairs(design):
        a = by_residue.get((weld["segid_a"], weld["resid_a"]))
        b = by_residue.get((weld["segid_b"], weld["resid_b"]))
        if a is None or b is None:
            excluded.append(
                {**weld, "reason": "residue absent or not thymine in topology"}
            )
            continue
        mapped[_pair_key(a[0], b[0])] = weld
    return mapped, excluded


def _scope_allows(site_a: dict, site_b: dict, scope: str) -> bool:
    same = site_a["segid"] == site_b["segid"]
    return (
        scope == "all"
        or (scope == "intrastrand" and same)
        or (scope == "interstrand" and not same)
    )


def _valid_box(dimensions: Any) -> np.ndarray | None:
    if dimensions is None:
        return None
    box = np.asarray(dimensions, dtype=np.float32)
    if box.size < 6 or not np.all(np.isfinite(box[:6])) or np.any(box[:3] <= 0):
        return None
    return box[:6]


def _mic(vectors: np.ndarray, box: np.ndarray | None) -> np.ndarray:
    if box is None or not len(vectors):
        return np.asarray(vectors, dtype=float)
    from MDAnalysis.lib.distances import minimize_vectors

    return minimize_vectors(np.asarray(vectors, dtype=np.float32), box).astype(float)


def _site_midpoints_ang(
    positions: np.ndarray, sites: Sequence[dict], box: np.ndarray | None
) -> np.ndarray:
    c5 = positions[[site["c5_serial"] for site in sites]]
    c6 = positions[[site["c6_serial"] for site in sites]]
    return c5 + 0.5 * _mic(c6 - c5, box)


def _geometry_for_candidates(
    positions: np.ndarray, candidates: Sequence[dict], box: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray]:
    if not candidates:
        return np.empty(0), np.empty(0)
    c5a = positions[[row["site_a"]["c5_serial"] for row in candidates]]
    c6a_raw = positions[[row["site_a"]["c6_serial"] for row in candidates]]
    c5b = positions[[row["site_b"]["c5_serial"] for row in candidates]]
    c6b_raw = positions[[row["site_b"]["c6_serial"] for row in candidates]]

    c6a = c5a + _mic(c6a_raw - c5a, box)
    c6b_local = c5b + _mic(c6b_raw - c5b, box)
    mid_a = 0.5 * (c5a + c6a)
    mid_b = 0.5 * (c5b + c6b_local)
    distance_nm = 0.1 * np.linalg.norm(_mic(mid_b - mid_a, box), axis=1)

    # Put B into the image nearest A before evaluating C5a-C6a-C6b-C5b.
    c6b = c6a + _mic(c6b_raw - c6a, box)
    c5b_image = c6b + _mic(c5b - c6b_raw, box)
    eta = np.asarray(cpd_metrics.dihedral_deg(c5a, c6a, c6b, c5b_image), dtype=float)
    return distance_nm, eta


def upstream_kimmdy_propensity(d_nm: Any, eta_deg: Any) -> np.ndarray:
    """Exact upstream angular penalty (non-periodic ``abs(eta - N0)``)."""

    return np.exp(
        -(
            cpd_metrics.K1 * np.abs(np.asarray(d_nm, dtype=float) - cpd_metrics.D0)
            + cpd_metrics.K2 * np.abs(np.asarray(eta_deg, dtype=float) - cpd_metrics.N0)
        )
    )


def _scan_all_tt_candidates(
    universe: Any,
    sites: Sequence[dict],
    frame_indices: Sequence[int],
    *,
    cutoff_ang: float,
    pair_scope: str,
    always_include: dict[tuple[int, int], dict],
    max_candidates: int,
    progress: Callable[[str, int, int], None] | None,
) -> tuple[list[dict], dict]:
    from MDAnalysis.lib.distances import self_capped_distance

    minima: dict[tuple[int, int], float] = {}
    for done, frame_index in enumerate(frame_indices, start=1):
        ts = universe.trajectory[frame_index]
        box = _valid_box(ts.dimensions)
        midpoints = _site_midpoints_ang(universe.atoms.positions, sites, box)
        pairs, distances = self_capped_distance(
            midpoints,
            max_cutoff=float(cutoff_ang),
            box=box,
            return_distances=True,
        )
        for (index_a, index_b), distance in zip(pairs, distances):
            ia, ib = int(index_a), int(index_b)
            if not _scope_allows(sites[ia], sites[ib], pair_scope):
                continue
            key = _pair_key(ia, ib)
            minima[key] = min(minima.get(key, math.inf), float(distance))
        if progress:
            progress("screen", done, len(frame_indices))

    allowed_intended = {
        key: weld
        for key, weld in always_include.items()
        if _scope_allows(sites[key[0]], sites[key[1]], pair_scope)
    }
    keys = set(minima) | set(allowed_intended)
    intended_keys = sorted(allowed_intended)
    other_keys = sorted(
        keys - set(intended_keys), key=lambda key: (minima.get(key, math.inf), key)
    )
    limit = max(1, int(max_candidates))
    kept_keys = intended_keys + other_keys[: max(0, limit - len(intended_keys))]
    candidates = []
    for key in kept_keys:
        row = _candidate(
            sites[key[0]], sites[key[1]], intended=allowed_intended.get(key)
        )
        row["screen_min_midpoint_ang"] = minima.get(key)
        candidates.append(row)
    return candidates, {
        "screen_cutoff_ang": float(cutoff_ang),
        "n_screen_hits": len(minima),
        "n_intended_forced_in": len(set(allowed_intended) - set(minima)),
        "n_candidates_before_limit": len(keys),
        "max_candidates": limit,
        "truncated": len(keys) > len(kept_keys),
    }


def _explicit_candidates(specs: Sequence[str], sites: Sequence[dict]) -> list[dict]:
    by_id = {(site["segid"].upper(), site["resid"]): site for site in sites}
    rows = []
    seen = set()
    for spec in specs:
        (seg_a, resid_a), (seg_b, resid_b) = parse_pair_spec(spec)
        site_a = by_id.get((seg_a.upper(), resid_a))
        site_b = by_id.get((seg_b.upper(), resid_b))
        if site_a is None or site_b is None:
            raise KeyError(f"explicit pair is not two topology thymines: {spec}")
        key = tuple(sorted((site_a["site_id"], site_b["site_id"])))
        if key in seen:
            continue
        seen.add(key)
        rows.append(_candidate(site_a, site_b))
    return rows


def _circular_mean_deg(values: np.ndarray) -> tuple[float | None, float | None]:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return None, None
    radians = np.radians(finite)
    vector = np.mean(np.exp(1j * radians))
    return float(np.degrees(np.angle(vector))), float(abs(vector))


def _frame_provenance(
    universe: Any, frame_indices: Sequence[int], n_trajectories: int
) -> tuple[np.ndarray, np.ndarray]:
    """Map chained frame indices back to trajectory-file and local-frame indices."""

    trajectory = universe.trajectory
    readers = getattr(trajectory, "readers", None)
    if readers is None or n_trajectories == 1:
        return (
            np.zeros(len(frame_indices), dtype=np.int64),
            np.asarray(frame_indices, dtype=np.int64),
        )
    lengths = np.asarray([len(reader) for reader in readers], dtype=np.int64)
    if len(lengths) != n_trajectories or int(np.sum(lengths)) != len(trajectory):
        raise RuntimeError("cannot map chained frames to the supplied trajectory files")
    starts = np.concatenate((np.asarray([0], dtype=np.int64), np.cumsum(lengths)[:-1]))
    global_frames = np.asarray(frame_indices, dtype=np.int64)
    source_indices = np.searchsorted(starts, global_frames, side="right") - 1
    local_frames = global_frames - starts[source_indices]
    return source_indices, local_frames


def _display_key(site: dict) -> str | None:
    identity = site.get("design_identity") or {}
    if identity.get("kind") == "crossover_insert":
        crossover_id = identity.get("crossover_id")
        insert_k = identity.get("extra_base_k")
        if crossover_id is not None and insert_k is not None:
            return f"__xb__:{crossover_id}:{insert_k}"
    helix_id = identity.get("helix_id")
    bp_index = identity.get("bp_index")
    direction = identity.get("direction")
    if helix_id is None or bp_index is None or direction is None:
        return None
    return f"{helix_id}:{bp_index}:{direction}"


def aggregate_base_likelihoods(
    sites: Sequence[dict], pairs: Sequence[dict]
) -> list[dict]:
    """Aggregate pair propensities into relative per-thymine incident propensities.

    Each possible photoproduct contributes its ensemble-mean primary propensity to both
    participating bases.  The sum is then normalized by the largest base sum in the
    analysed design.  It is a relative visualization score, not a reaction probability.
    """

    totals = {site["site_id"]: {"sum": 0.0, "max": 0.0, "pairs": 0} for site in sites}
    for pair in pairs:
        score = pair.get("primary_propensity_mean")
        if not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
            continue
        for side in ("site_a", "site_b"):
            site_id = pair.get(side, {}).get("site_id")
            if site_id not in totals:
                continue
            totals[site_id]["sum"] += float(score)
            totals[site_id]["max"] = max(totals[site_id]["max"], float(score))
            totals[site_id]["pairs"] += 1

    scale = max((row["sum"] for row in totals.values()), default=0.0)
    rows = []
    for site in sites:
        aggregate = totals[site["site_id"]]
        rows.append(
            {
                "site_id": site["site_id"],
                "label": site["label"],
                "segid": site["segid"],
                "resid": site["resid"],
                "resname": site["resname"],
                "design_identity": site.get("design_identity"),
                "display_key": _display_key(site),
                "aggregate_propensity": aggregate["sum"],
                "max_pair_propensity": aggregate["max"],
                "candidate_pairs": aggregate["pairs"],
                "relative_likelihood": aggregate["sum"] / scale if scale > 0 else 0.0,
            }
        )
    rows.sort(
        key=lambda row: (-row["aggregate_propensity"], row["segid"], row["resid"])
    )
    return rows


def _summaries(
    candidates: Sequence[dict],
    distance_nm: np.ndarray,
    eta_deg: np.ndarray,
    periodic: np.ndarray,
    upstream: np.ndarray,
    frame_indices: Sequence[int],
    times_ps: Sequence[float],
    trajectory_paths: Sequence[Path],
    trajectory_indices: np.ndarray,
    trajectory_local_frames: np.ndarray,
    rate_model: str,
    screen_cutoff_ang: float,
) -> tuple[list[dict], np.ndarray]:
    primary = periodic if rate_model == "periodic" else upstream
    summaries: list[tuple[int, dict]] = []
    for pair_index, candidate in enumerate(candidates):
        d = distance_nm[pair_index]
        eta = eta_deg[pair_index]
        kp = periodic[pair_index]
        ku = upstream[pair_index]
        k = primary[pair_index]
        finite = np.isfinite(d) & np.isfinite(eta) & np.isfinite(k)
        if not np.any(finite):
            continue
        eta_mean, eta_resultant = _circular_mean_deg(eta[finite])
        valid_indices = np.flatnonzero(finite)
        best_series_index = int(valid_indices[np.argmax(k[finite])])
        reactive = (d[finite] < cpd_metrics.REACTIVE_D_NM) & (
            cpd_metrics.angular_separation_deg(eta[finite])
            < cpd_metrics.REACTIVE_ETA_DEG
        )
        public_candidate = {
            key: value
            for key, value in candidate.items()
            if key not in {"_site_index_a", "_site_index_b"}
        }
        summaries.append(
            (
                pair_index,
                {
                    **public_candidate,
                    "n_frames": int(np.sum(finite)),
                    "d_mid_mean_nm": float(np.mean(d[finite])),
                    "d_mid_min_nm": float(np.min(d[finite])),
                    "d_mid_p05_nm": float(np.percentile(d[finite], 5)),
                    "eta_circular_mean_deg": eta_mean,
                    "eta_resultant": eta_resultant,
                    "periodic_propensity_mean": float(np.mean(kp[finite])),
                    "periodic_propensity_max": float(np.max(kp[finite])),
                    "upstream_propensity_mean": float(np.mean(ku[finite])),
                    "upstream_propensity_max": float(np.max(ku[finite])),
                    "primary_propensity_mean": float(np.mean(k[finite])),
                    "primary_propensity_max": float(np.max(k[finite])),
                    "pct_primary_ge_0_1": float(100 * np.mean(k[finite] >= 0.1)),
                    "pct_primary_ge_0_5": float(100 * np.mean(k[finite] >= 0.5)),
                    "pct_d_mid_lt_0_4_nm": float(100 * np.mean(d[finite] < 0.4)),
                    "pct_d_mid_below_screen_cutoff": float(
                        100 * np.mean(d[finite] * 10 < screen_cutoff_ang)
                    ),
                    "reactive_frames": int(np.sum(reactive)),
                    "pct_reactive_corner": float(100 * np.mean(reactive)),
                    "representative_max_propensity": {
                        "series_index": best_series_index,
                        "frame": int(frame_indices[best_series_index]),
                        "time_ps": float(times_ps[best_series_index]),
                        "trajectory_index": int(trajectory_indices[best_series_index]),
                        "trajectory": str(
                            Path(
                                trajectory_paths[
                                    int(trajectory_indices[best_series_index])
                                ]
                            ).resolve()
                        ),
                        "trajectory_frame": int(
                            trajectory_local_frames[best_series_index]
                        ),
                        "d_mid_nm": float(d[best_series_index]),
                        "eta_deg": float(eta[best_series_index]),
                        "periodic_propensity": float(kp[best_series_index]),
                        "upstream_propensity": float(ku[best_series_index]),
                    },
                },
            )
        )
    sorted_summaries = sorted(
        summaries,
        key=lambda item: item[1]["primary_propensity_mean"],
        reverse=True,
    )
    order = np.asarray([pair_index for pair_index, _row in sorted_summaries], dtype=int)
    ranked = []
    for rank, (_pair_index, row) in enumerate(sorted_summaries, start=1):
        ranked.append({"rank": rank, **row})
    return ranked, order


def analyze_kimmdy_trajectory(
    topology_path: Path,
    trajectory_paths: Sequence[Path],
    design: Any,
    *,
    pair_mode: str = "designed",
    explicit_pairs: Sequence[str] = (),
    pair_scope: str = "all",
    screen_cutoff_ang: float = 6.0,
    max_candidates: int = 500,
    start: int = 0,
    stop: int | None = None,
    stride: int = 1,
    max_frames: int | None = 2000,
    rate_model: str = "upstream",
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Run candidate discovery and KIMMDY geometry over one trajectory ensemble."""

    if pair_mode not in PAIR_MODES:
        raise ValueError(
            f"unknown pair_mode {pair_mode!r}; choose from {sorted(PAIR_MODES)}"
        )
    if pair_scope not in PAIR_SCOPES:
        raise ValueError(f"unknown pair_scope {pair_scope!r}")
    if rate_model not in RATE_MODELS:
        raise ValueError(f"unknown rate_model {rate_model!r}")
    if pair_mode == "explicit" and not explicit_pairs:
        raise ValueError("explicit pair mode needs at least one pair specification")

    import MDAnalysis as mda

    paths = [str(path) for path in trajectory_paths]
    universe = mda.Universe(str(topology_path), paths if len(paths) > 1 else paths[0])
    frame_indices = sample_frame_indices(
        len(universe.trajectory),
        start=start,
        stop=stop,
        stride=stride,
        max_frames=max_frames,
    )
    if not frame_indices:
        raise ValueError("requested frame interval is empty")
    sites = topology_thymine_sites(universe, design)
    designed_map, designed_excluded = _designed_candidate_map(design, sites)

    screen = None
    if pair_mode == "designed":
        candidates = [
            _candidate(sites[key[0]], sites[key[1]], intended=weld)
            for key, weld in sorted(designed_map.items())
            if _scope_allows(sites[key[0]], sites[key[1]], pair_scope)
        ]
    elif pair_mode == "explicit":
        candidates = _explicit_candidates(explicit_pairs, sites)
        candidates = [
            row
            for row in candidates
            if _scope_allows(row["site_a"], row["site_b"], pair_scope)
        ]
        for row in candidates:
            index_by_site = {site["site_id"]: i for i, site in enumerate(sites)}
            weld = designed_map.get(
                _pair_key(
                    index_by_site[row["site_a"]["site_id"]],
                    index_by_site[row["site_b"]["site_id"]],
                )
            )
            if weld:
                row["intended_weld"] = True
                row["intended_weld_identity"] = weld
    else:
        candidates, screen = _scan_all_tt_candidates(
            universe,
            sites,
            frame_indices,
            cutoff_ang=screen_cutoff_ang,
            pair_scope=pair_scope,
            always_include=designed_map,
            max_candidates=max_candidates,
            progress=progress,
        )

    n_pairs = len(candidates)
    n_frames = len(frame_indices)
    distances = np.full((n_pairs, n_frames), np.nan, dtype=np.float64)
    etas = np.full((n_pairs, n_frames), np.nan, dtype=np.float64)
    times_ps = np.empty(n_frames, dtype=np.float64)
    trajectory_indices, trajectory_local_frames = _frame_provenance(
        universe, frame_indices, len(trajectory_paths)
    )
    for series_index, frame_index in enumerate(frame_indices):
        ts = universe.trajectory[frame_index]
        box = _valid_box(ts.dimensions)
        d, eta = _geometry_for_candidates(universe.atoms.positions, candidates, box)
        distances[:, series_index] = d
        etas[:, series_index] = eta
        times_ps[series_index] = float(ts.time)
        if progress:
            progress("measure", series_index + 1, n_frames)

    periodic = np.asarray(cpd_metrics.kimmdy_rate(distances, etas), dtype=np.float64)
    upstream = upstream_kimmdy_propensity(distances, etas)
    ranked, order = _summaries(
        candidates,
        distances,
        etas,
        periodic,
        upstream,
        frame_indices,
        times_ps,
        trajectory_paths,
        trajectory_indices,
        trajectory_local_frames,
        rate_model,
        screen_cutoff_ang,
    )
    if len(order):
        distances = distances[order]
        etas = etas[order]
        periodic = periodic[order]
        upstream = upstream[order]

    report = {
        "schema": SCHEMA,
        "ready": True,
        "topology": str(Path(topology_path).resolve()),
        "trajectories": [str(Path(path).resolve()) for path in trajectory_paths],
        "pair_mode": pair_mode,
        "pair_scope": pair_scope,
        "rate_model": rate_model,
        "rate_note": (
            "Dimensionless geometric propensity, not an absolute kinetic rate or quantum yield. "
            "Both upstream non-periodic and NADOC periodic-angle values are exported."
        ),
        "parameters": {
            "k1_per_nm": cpd_metrics.K1,
            "k2_per_deg": cpd_metrics.K2,
            "d0_nm": cpd_metrics.D0,
            "eta0_deg": cpd_metrics.N0,
            "reactive_d_nm": cpd_metrics.REACTIVE_D_NM,
            "reactive_eta_window_deg": cpd_metrics.REACTIVE_ETA_DEG,
            "screen_cutoff_ang": float(screen_cutoff_ang),
        },
        "n_total_frames": len(universe.trajectory),
        "n_sampled_frames": n_frames,
        "frame_start": int(frame_indices[0]),
        "frame_stop": int(frame_indices[-1]),
        "effective_stride_min": int(np.min(np.diff(frame_indices)))
        if n_frames > 1
        else None,
        "frame_indices": [int(value) for value in frame_indices],
        "times_ps": [float(value) for value in times_ps],
        "trajectory_indices": [int(value) for value in trajectory_indices],
        "trajectory_local_frames": [int(value) for value in trajectory_local_frames],
        "n_topology_thymines": len(sites),
        "n_candidates": len(ranked),
        "designed_welds_resolved": len(designed_map),
        "designed_welds_excluded": designed_excluded,
        "screen": screen,
        "pairs": ranked,
        "base_likelihoods": aggregate_base_likelihoods(sites, ranked),
        "base_likelihood_note": (
            "For each topology thymine, sum the ensemble-mean primary propensities of "
            "analysed T-T pairs incident on that base, then normalize by the largest "
            "base sum. Relative visualization score only; not an absolute probability."
        ),
    }
    series = {
        "schema": np.asarray(SERIES_SCHEMA),
        "pair_ids": np.asarray([row["id"] for row in ranked], dtype=str),
        "frame_indices": np.asarray(frame_indices, dtype=np.int64),
        "times_ps": times_ps,
        "trajectory_indices": trajectory_indices,
        "trajectory_local_frames": trajectory_local_frames,
        "d_mid_nm": distances,
        "eta_deg": etas,
        "periodic_propensity": periodic,
        "upstream_propensity": upstream,
    }
    return report, series


def write_kimmdy_outputs(
    report: dict, series: dict[str, np.ndarray], output_dir: Path
) -> dict[str, str]:
    """Write JSON/TSV summary and a compressed, rank-aligned per-frame series."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    tsv_path = output_dir / "pairs.tsv"
    npz_path = output_dir / "timeseries.npz"
    json_path.write_text(json.dumps(report, indent=2) + "\n")

    fields = [
        "rank",
        "id",
        "label",
        "intended_weld",
        "same_strand",
        "sequence_separation",
        "n_frames",
        "d_mid_mean_nm",
        "d_mid_min_nm",
        "d_mid_p05_nm",
        "eta_circular_mean_deg",
        "eta_resultant",
        "periodic_propensity_mean",
        "periodic_propensity_max",
        "upstream_propensity_mean",
        "upstream_propensity_max",
        "primary_propensity_mean",
        "primary_propensity_max",
        "pct_primary_ge_0_1",
        "pct_primary_ge_0_5",
        "pct_d_mid_lt_0_4_nm",
        "pct_d_mid_below_screen_cutoff",
        "reactive_frames",
        "pct_reactive_corner",
        "segid_a",
        "resid_a",
        "resname_a",
        "segid_b",
        "resid_b",
        "resname_b",
        "representative_frame",
        "representative_time_ps",
        "representative_trajectory_index",
        "representative_trajectory",
        "representative_trajectory_frame",
    ]
    with tsv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in report.get("pairs", []):
            representative = row.get("representative_max_propensity", {})
            writer.writerow(
                {
                    **{key: row.get(key) for key in fields},
                    "segid_a": row["site_a"]["segid"],
                    "resid_a": row["site_a"]["resid"],
                    "resname_a": row["site_a"]["resname"],
                    "segid_b": row["site_b"]["segid"],
                    "resid_b": row["site_b"]["resid"],
                    "resname_b": row["site_b"]["resname"],
                    "representative_frame": representative.get("frame"),
                    "representative_time_ps": representative.get("time_ps"),
                    "representative_trajectory_index": representative.get(
                        "trajectory_index"
                    ),
                    "representative_trajectory": representative.get("trajectory"),
                    "representative_trajectory_frame": representative.get(
                        "trajectory_frame"
                    ),
                }
            )
    np.savez_compressed(npz_path, **series)
    return {
        "summary_json": str(json_path),
        "pairs_tsv": str(tsv_path),
        "timeseries_npz": str(npz_path),
    }
