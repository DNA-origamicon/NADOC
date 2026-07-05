"""CanDo-FEM autorefine — Phase-5 Item 4.

Greedy loop/skip placement refinement driven by the FAST in-process CanDo FEM shape
oracle (``fem_solver.predict_shape`` → ``cando_deviation.compute_deviation``), replacing
the hours-long oxDNA CUDA simulation that the square-lattice self-consistency loop
(:mod:`backend.api.skip_twist_tuning`) uses.  Because a linear FEM solve is ~seconds on a
6HB/210, the greedy single-edit inner loop that was impractical with oxDNA becomes routine.

**Objective** = shrink the Item-3 deviation RMSD: the per-nucleotide distance between the
FEM-predicted relaxed shape and the design's INTENDED (displayed) geometry — i.e. make the
loop/skip program actually realise the bend/twist the user drew.  This is a mirror of
:func:`backend.api.skip_twist_tuning.greedy_finetune_skips`, with the FEM oracle swapped in
for the pooled oxDNA measurement.

**Edit strategy (topology-safe).**  Deciding whether a hotspot wants an added deletion, an
added loop, or a removed mark is a *directional / topological* judgement — which this module
NEVER makes geometrically (see CLAUDE.md's DNA-topology rule + [[feedback_crossover_no_reasoning]]).
Instead every candidate edit is TRIED and the FEM oracle empirically keeps whichever lowers
the RMSD.  Two modes, per the user's split:

  * **square lattice** → candidate edits are ADD-skip / REMOVE-mark only (deletion-only space,
    matching the oxDNA finetuner);
  * **twist/bend designs** (honeycomb) → also ADD-loop, so a hotspot can be corrected by
    lengthening (loop, +1) as well as shortening (skip, −1).

**Placement is off-crossover / off-end.**  Auto-placed marks must never sit on a crossover bp
or a strand terminus/nick ([[feedback_loopskip_no_crossover_ends]] — CanDo crashes on such
files).  ``free_interior_candidates`` filters ``core_candidates`` down to crossover-free,
endpoint-free, end-margin-free interior bp before any ADD.

Three-Layer Law: this module reads topology and predicts a Physical-layer shape; it returns a
proposed loop/skip mark set but NEVER mutates the active design.  The REST ``apply`` route lands
the converged marks as a reversible feature-log entry.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Optional

from backend.core.models import Design, LatticeType

# bp kept clear of each helix's duplex ends (mirrors the exp36 battery generator's END_MARGIN).
END_MARGIN = 6


# ── Deviation field + hotspot ranking (mechanical: highest positional error) ────────────────

def aggregate_deviation_by_bp(positions: list[dict]) -> dict[tuple[str, int], float]:
    """Collapse a :func:`compute_deviation` per-nucleotide list to a per-(helix, bp) field by
    averaging the deviation across the two strand directions and any loop copies at each station."""
    acc: dict[tuple[str, int], list[float]] = defaultdict(list)
    for p in positions:
        acc[(p["helix_id"], int(p["bp_index"]))].append(float(p["deviation"]))
    return {k: sum(v) / len(v) for k, v in acc.items()}


def rank_hotspots(deviation_by_bp: dict[tuple[str, int], float], *,
                  sigma: float = 1.0, max_hotspots: int = 8,
                  min_spacing: int = 8) -> list[tuple[str, int]]:
    """The up-to-``max_hotspots`` worst deviation stations, most-severe first.

    A hotspot must exceed ``mean + sigma·std`` of the whole field, so a uniform / already-good
    field yields NO hotspots (the refiner does no harm when there is nothing local to fix — the
    same noise-floor gate as :func:`skip_finetune.identify_finetune_edits`).  Stations within
    ``min_spacing`` bp of an already-chosen one on the same helix are skipped so edits stay spread.
    """
    if not deviation_by_bp:
        return []
    vals = list(deviation_by_bp.values())
    mean = sum(vals) / len(vals)
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    threshold = mean + sigma * std
    ranked = sorted((kv for kv in deviation_by_bp.items() if kv[1] > threshold),
                    key=lambda kv: kv[1], reverse=True)
    chosen: list[tuple[str, int]] = []
    for (hid, bp), _dev in ranked:
        if len(chosen) >= max_hotspots:
            break
        if any(h2 == hid and abs(bp - b2) < min_spacing for h2, b2 in chosen):
            continue
        chosen.append((hid, bp))
    return chosen


# ── Off-crossover / off-end candidate placement ([[feedback_loopskip_no_crossover_ends]]) ───

def _forbidden_bps(design: Design) -> tuple[dict[str, set[int]], dict[str, tuple[int, int]]]:
    """Per helix: the bp an auto mark must NOT land on (crossover bp + strand domain endpoints
    + a duplex-end margin) and the ``(lo, hi)`` interior range.  Mirrors the exp36 generator's
    ``_forbidden_bps`` so the live refiner enforces the same rule the battery does."""
    from backend.core.crossover_positions import extract_crossovers_from_strands

    forb: dict[str, set[int]] = {h.id: set() for h in design.helices}
    interior: dict[str, tuple[int, int]] = {}
    # Crossovers from strand TOPOLOGY (design.crossovers is often empty on loaded designs).
    try:
        xos, _ = extract_crossovers_from_strands(
            design.strands, design.helices, design.lattice_type)
    except Exception:  # noqa: BLE001
        xos = list(getattr(design, "crossovers", []) or [])
    for xo in xos:
        for half in (xo.half_a, xo.half_b):
            if half.helix_id in forb:
                forb[half.helix_id].add(half.index)
    cov: dict[str, set[int]] = {h.id: set() for h in design.helices}
    for s in design.strands:
        if getattr(s, "is_reference", False):
            continue
        for dm in s.domains:
            if dm.helix_id not in forb:
                continue
            forb[dm.helix_id].add(dm.start_bp)
            forb[dm.helix_id].add(dm.end_bp)
            cov[dm.helix_id].update(range(min(dm.start_bp, dm.end_bp),
                                          max(dm.start_bp, dm.end_bp) + 1))
    for hid, bps in cov.items():
        if bps:
            lo, hi = min(bps), max(bps)
            interior[hid] = (lo + END_MARGIN, hi - END_MARGIN)
            for b in range(lo, lo + END_MARGIN):
                forb[hid].add(b)
            for b in range(hi - END_MARGIN + 1, hi + 1):
                forb[hid].add(b)
        else:
            interior[hid] = (0, -1)
    return forb, interior


def free_interior_candidates(design: Design, helix, forbidden: set[int]) -> list[int]:
    """dsDNA-core bp on ``helix`` where a NEW auto mark may legally be placed: ``core_candidates``
    (both tracks present, not already marked) minus the ``forbidden`` set (crossovers / endpoints /
    end margin).  ``forbidden`` is precomputed once per design via :func:`_forbidden_bps`."""
    from backend.core.regional_skip_placer import core_candidates
    return [bp for bp in core_candidates(design, helix) if bp not in forbidden]


# ── Mark bookkeeping + trial builds (pure / topological) ────────────────────────────────────

def current_marks_by_helix(design: Design) -> dict[str, dict[int, int]]:
    """``{helix_id: {bp_index: delta}}`` for the design's existing loop/skips (delta −1 skip, +1 loop)."""
    return {h.id: {ls.bp_index: ls.delta for ls in h.loop_skips}
            for h in design.helices if h.loop_skips}


def apply_marks(base_design: Design, marks_by_helix: dict[str, dict[int, int]]) -> Design:
    """Return a copy of ``base_design`` whose loop/skips are EXACTLY ``marks_by_helix``
    (clear-then-apply).  Pure/topological and — deliberately — does NOT re-sequence: the FEM
    oracle reads duplex-coverage geometry, not base letters, so skipping the (slow) full-sequence
    rebuild keeps the inner loop fast.  The REST apply route re-sequences before landing on the
    real design (staple complementarity would otherwise drift — see routes_cando_autorefine)."""
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_all_loop_skips
    from backend.core.models import LoopSkip

    d = clear_all_loop_skips(base_design)
    mods = {hid: [LoopSkip(bp_index=int(bp), delta=int(dl)) for bp, dl in sorted(bps.items())]
            for hid, bps in marks_by_helix.items() if bps}
    if mods:
        d = apply_loop_skips(d, mods)
    return d


# ── The FEM oracle: one linear/nonlinear solve → deviation RMSD + field ──────────────────────

def fem_measure(design: Design, *, nonlinear: bool = False) -> Optional[dict]:
    """Run the CanDo FEM shape oracle once on ``design`` and return
    ``{rmsd, dev_max, dev_mean, n, deviation_by_bp, shape}`` — the RMSD is the objective the greedy
    loop minimises, ``deviation_by_bp`` steers the next round's hotspots, and ``shape`` (the raw
    ``predict_shape`` output) is retained so twist/bend can be measured for the status readout
    WITHOUT a second solve.

    Returns ``None`` when the design has no double-helical core to solve (``predict_shape`` raises
    ``ValueError`` on <2 duplex bp) so the caller can bail cleanly instead of crashing.
    """
    from backend.core.cando_deviation import compute_deviation
    from backend.physics.fem_solver import predict_shape

    try:
        shape = predict_shape(design, nonlinear=nonlinear, with_rmsf=False)
    except ValueError:
        return None
    dev = compute_deviation(design, shape["positions"])
    return {
        "rmsd":            dev["rmsd_nm"],
        "dev_max":         dev["max_deviation"],
        "dev_mean":        dev["mean_deviation"],
        "n":               dev["n"],
        "deviation_by_bp": aggregate_deviation_by_bp(dev["positions"]),
        "shape":           shape,
    }


# ── Twist / bend readout for the live status (no extra solve; measured off the cached shape) ────

def _core_keys(shape: dict) -> set[tuple[str, int]]:
    """The duplex-core (helix, bp) stations of a ``predict_shape`` result (its axis nodes) —
    the rigid set to restrict twist/bend measurement to (ssDNA ends / loop copies have ill-defined
    cross-section centres, per ``measure_bundle_twist``'s 'pass the duplex CORE' guidance)."""
    return {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}


def _measure_twist_bend(positions: list[dict], core_keys: set[tuple[str, int]]) -> dict:
    """``{twist_deg, bend_deg}`` of a backbone-position list (restricted to ``core_keys``), reusing
    the shared bundle-shape estimators.  Either value is ``None`` if its estimator can't resolve
    (too few helices / degenerate axis) — the status then shows '—' rather than a bogus number."""
    from backend.core.oxdna_health import measure_bundle_arc_bend, measure_bundle_twist

    core = [p for p in positions if (p["helix_id"], int(p["bp_index"])) in core_keys]
    out: dict = {"twist_deg": None, "bend_deg": None}
    try:
        out["twist_deg"] = float(measure_bundle_twist(core))
    except Exception:      # noqa: BLE001 — degenerate geometry → leave None
        pass
    try:
        out["bend_deg"] = float(measure_bundle_arc_bend(core))   # chord-sagitta: true arc angle
    except Exception:      # noqa: BLE001
        pass
    return out


def _intended_positions(design: Design) -> list[dict]:
    """The design's INTENDED (displayed) backbone positions as a measurement list
    ``[{helix_id, bp_index, backbone_position}]`` — the same ``deformed_nucleotide_positions`` the
    deviation oracle targets.  Twist/bend of THIS is the target the FEM prediction is aiming at."""
    from backend.core.deformation import deformed_nucleotide_positions

    out: list[dict] = []
    for h in design.helices:
        for nuc in deformed_nucleotide_positions(h, design):
            pos = nuc.position
            out.append({"helix_id": nuc.helix_id, "bp_index": nuc.bp_index,
                        "backbone_position": [float(pos[0]), float(pos[1]), float(pos[2])]})
    return out


def target_metrics(base_design: Design, core_keys: set[tuple[str, int]]) -> dict:
    """The target the refiner aims at: ``{deviation:0.0, twist_deg, bend_deg}`` — deviation target
    is 0 (perfect match) and twist/bend are measured off the design's intended geometry with the
    SAME estimators used for the current prediction, so the two are directly comparable."""
    tb = _measure_twist_bend(_intended_positions(base_design), core_keys)
    return {"deviation": 0.0, "twist_deg": tb["twist_deg"], "bend_deg": tb["bend_deg"]}


def current_metrics(measure: dict, core_keys: set[tuple[str, int]]) -> dict:
    """The current prediction's ``{deviation, twist_deg, bend_deg}`` from a :func:`fem_measure`
    result (reuses its cached ``shape`` — no extra solve)."""
    tb = _measure_twist_bend(measure["shape"]["positions"], core_keys)
    return {"deviation": measure["rmsd"], "twist_deg": tb["twist_deg"], "bend_deg": tb["bend_deg"]}


# ── Candidate edit enumeration (try-both; direction chosen empirically by the oracle) ────────

def candidate_edits(hotspot: tuple[str, int], marks_by_helix: dict[str, dict[int, int]],
                    free_by_helix: dict[str, list[int]], *, allow_loops: bool) -> list[dict]:
    """The edits to TRY at one ``(helix, bp)`` hotspot.  Never decides direction — enumerates the
    whole applicable set and lets :func:`fem_refine` keep whichever the oracle says helps.

    Each edit is ``{helix_id, op, bp_index}`` where ``op`` ∈ {``add_skip``, ``add_loop``,
    ``remove``}.  ADD ops target the nearest FREE INTERIOR bp (off crossovers/ends); REMOVE targets
    the nearest EXISTING mark on the helix.  Square-lattice mode omits ``add_loop``.
    """
    hid, bp = hotspot
    edits: list[dict] = []
    free = free_by_helix.get(hid, [])
    if free:
        target = min(free, key=lambda c: abs(c - bp))
        edits.append({"helix_id": hid, "op": "add_skip", "bp_index": int(target)})
        if allow_loops:
            edits.append({"helix_id": hid, "op": "add_loop", "bp_index": int(target)})
    existing = list(marks_by_helix.get(hid, {}).keys())
    if existing:
        nearest = min(existing, key=lambda c: abs(c - bp))
        edits.append({"helix_id": hid, "op": "remove", "bp_index": int(nearest)})
    return edits


def _with_edit(marks_by_helix: dict[str, dict[int, int]], edit: dict) -> dict[str, dict[int, int]]:
    """Return a deep-ish copy of ``marks_by_helix`` with one ``candidate_edits`` edit applied."""
    out = {hid: dict(bps) for hid, bps in marks_by_helix.items()}
    hid, op, bp = edit["helix_id"], edit["op"], int(edit["bp_index"])
    cur = out.setdefault(hid, {})
    if op == "add_skip":
        cur[bp] = -1
    elif op == "add_loop":
        cur[bp] = +1
    elif op == "remove":
        cur.pop(bp, None)
    if not cur:
        out.pop(hid, None)
    return out


# ── The greedy refinement loop ───────────────────────────────────────────────────────────────

def fem_refine(base_design: Design, *, nonlinear: bool = False, sigma: float = 1.0,
               max_hotspots: int = 8, min_spacing: int = 8, rmsd_improve_nm: float = 0.05,
               allow_loops: Optional[bool] = None,
               on_progress: Optional[Callable[[dict], None]] = None,
               should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """Greedily add/remove loop/skip marks to minimise the FEM-vs-intended deviation RMSD.

    Mirrors :func:`skip_twist_tuning.greedy_finetune_skips` with the FEM oracle.  Ranks the
    baseline deviation hotspots once, then walks them: at each, TRIES every applicable edit
    (add-skip / add-loop / remove) via the oracle and KEEPS the best if it lowers the RMSD by
    ≥ ``rmsd_improve_nm``.  Accepted edits accumulate, so later hotspots see the improved pattern.

    ``allow_loops`` defaults to ``design.lattice_type != SQUARE`` (square → skips only, per the
    user's split); pass an explicit bool to override.  ``nonlinear=False`` (linear, ~seconds) is
    the sensible inner-loop oracle; run a final Fine job to confirm.

    Returns ``{status, mode, n_hotspots, n_evaluated, edits_kept, before, after, converged_marks}``
    where ``converged_marks`` is ``{helix_id: {bp_index: delta}}`` (the apply route lands it) and
    ``before``/``after`` are ``{rmsd, dev_max, dev_mean}``.  ``status`` ∈ {done, stopped, error}.
    """
    if allow_loops is None:
        allow_loops = base_design.lattice_type != LatticeType.SQUARE
    mode = "loops_and_skips" if allow_loops else "skips_only"

    def emit(ev: dict) -> None:
        if on_progress:
            on_progress(ev)

    emit({"phase": "baseline", "mode": mode})
    baseline = fem_measure(base_design, nonlinear=nonlinear)
    if baseline is None:
        return {"status": "error", "mode": mode,
                "error": "design has no double-helical core to predict a shape for",
                "edits_kept": [], "n_hotspots": 0, "n_evaluated": 0}

    # Twist/bend/deviation readout for the live status: the target (intended geometry, measured
    # once) and the current best (reuses each fem_measure's cached shape — no extra solves).
    core_keys = _core_keys(baseline["shape"])
    target = target_metrics(base_design, core_keys)
    emit({"phase": "iteration", "iteration": 0, "n_hotspots": None,
          "current": current_metrics(baseline, core_keys), "target": target})

    hotspots = rank_hotspots(baseline["deviation_by_bp"], sigma=sigma,
                             max_hotspots=max_hotspots, min_spacing=min_spacing)
    emit({"phase": "hotspots", "n": len(hotspots)})

    forbidden, _interior = _forbidden_bps(base_design)
    helix_by_id = {h.id: h for h in base_design.helices}
    free_by_helix = {h.id: free_interior_candidates(base_design, h, forbidden[h.id])
                     for h in base_design.helices}

    cur_marks = current_marks_by_helix(base_design)
    best = baseline
    kept: list[dict] = []
    evaluated = 0
    iteration = 0
    stopped = False
    for hs in hotspots:
        if should_stop and should_stop():
            stopped = True
            break
        if hs[0] not in helix_by_id:
            continue
        iteration += 1
        # Re-derive free candidates for THIS helix from the accumulated pattern so a bp used by an
        # earlier accepted edit is not offered again (core_candidates already drops marked bp).
        helix = helix_by_id[hs[0]]
        live_free = free_interior_candidates(apply_marks(base_design, cur_marks), helix,
                                             forbidden[hs[0]])
        free_now = {hs[0]: live_free}
        best_edit = None
        best_measure = best
        for edit in candidate_edits(hs, cur_marks, free_now, allow_loops=allow_loops):
            if should_stop and should_stop():
                stopped = True
                break
            trial_marks = _with_edit(cur_marks, edit)
            m = fem_measure(apply_marks(base_design, trial_marks), nonlinear=nonlinear)
            evaluated += 1
            if m is None:
                continue
            emit({"phase": "trial", "helix_id": hs[0], "bp": hs[1], "op": edit["op"],
                  "rmsd": m["rmsd"]})
            if m["rmsd"] < best_measure["rmsd"]:
                best_edit, best_measure = edit, m
        if stopped:
            break
        accepted = best_edit is not None and best_measure["rmsd"] <= best["rmsd"] - rmsd_improve_nm
        if accepted:
            cur_marks = _with_edit(cur_marks, best_edit)
            best = best_measure
            kept.append({**best_edit, "rmsd": best["rmsd"], "dev_max": best["dev_max"]})
        # Per-iteration status: iteration index, the accepted op (if any), and the CURRENT best
        # twist/bend/deviation vs the target — reuses best["shape"], no extra solve.
        emit({"phase": "iteration", "iteration": iteration, "n_hotspots": len(hotspots),
              "helix_id": hs[0], "bp": hs[1],
              "op": best_edit["op"] if accepted else None, "accepted": accepted,
              "current": current_metrics(best, core_keys), "target": target})

    out = {
        "status":          "stopped" if stopped else "done",
        "mode":            mode,
        "n_hotspots":      len(hotspots),
        "n_evaluated":     evaluated,
        "edits_kept":      kept,
        "before":          {k: baseline[k] for k in ("rmsd", "dev_max", "dev_mean")},
        "after":           {k: best[k] for k in ("rmsd", "dev_max", "dev_mean")},
        # Final twist/bend/deviation of the best prediction vs the target (for the result readout).
        "metrics":         {"before": current_metrics(baseline, core_keys),
                            "after": current_metrics(best, core_keys), "target": target},
        "converged_marks": {hid: {int(bp): int(dl) for bp, dl in bps.items()}
                            for hid, bps in cur_marks.items() if bps},
    }
    emit({"phase": "done", "status": out["status"], "kept": len(kept),
          "before_rmsd": out["before"]["rmsd"], "after_rmsd": out["after"]["rmsd"],
          "current": out["metrics"]["after"], "target": target})
    return out
