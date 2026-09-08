#!/usr/bin/env python3
"""Partition interstrand TT photoproduct opportunity into extra and native bases."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
EXP59 = ROOT / "experiments" / "exp59_kimmdy_extra_base_matrix"
INVENTORY = EXP59 / "inventory.json"
JOBS = HERE / "results" / "jobs"
PAIR_CSV = HERE / "pair_summary.csv"
LINEAGE_CSV = HERE / "lineage_class_summary.csv"
GROUP_CSV = HERE / "group_summary.csv"
REPORT = HERE / "REPORT.md"

# Only matched structural families enter the causal decomposition. Parent/child production
# jobs share a lineage; sibling replicas do not.
CASE_SPECS = (
    # job id, family, insert arrangement, lineage, optional audited workspace design
    ("6fc87681f9de", "24hb", "0-0", "24hb_0xT", "workspace/24hb_0xT.nadoc"),
    ("3e9e2df26012", "24hb", "0-0", "24hb_0xT", "workspace/24hb_0xT.nadoc"),
    ("6950d3b79138", "24hb", "1-1", "24hb_1xT", None),
    ("fc12195d0636", "24hb", "2-2", "24hb_2xT", None),
    ("6d7c2e38e455", "6hbx100", "0-0", "6hbx100_0xT", None),
    ("892ad3d12d4f", "6hbx100", "0-0", "6hbx100_0xT", None),
    ("7838a495c0a6", "6hbx100", "0-0", "6hbx100_0xT", None),
    ("37418e309e59", "6hbx100", "1-1", "6hbx100_1xT_rep1", None),
    ("992ab65c0d1a", "6hbx100", "1-1", "6hbx100_1xT_rep2", None),
    ("eb4953783dd3", "6hbx100", "1-1", "6hbx100_1xT_rep3", None),
)

CLASSES = (
    "designed_extra_extra",
    "other_extra_extra",
    "extra_native",
    "native_native_near_insert",
    "native_native_far",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _resolve_cases() -> list[dict[str, Any]]:
    inv = _read_json(INVENTORY)
    indexed = {row["job_id"]: row for row in inv["relevant_managed_jobs"]}
    cases = []
    for job_id, family, arrangement, lineage, override in CASE_SPECS:
        source = indexed[job_id]
        package = Path(source["package"])
        stem = source["name_stem"]
        topology = next((path for path in (
            package / f"{stem}_hmr.psf", package / f"{stem}.psf"
        ) if path.is_file()), None)
        if topology is None:
            raise FileNotFoundError(f"no PSF for {job_id}")
        if override:
            design = ROOT / override
            design_source = "audited_workspace_family_design"
        else:
            design = Path(source["design_path"])
            design_source = source.get("design_source", "job_snapshot")
        dcds = [Path(path) for path in source["production_dcds"]]
        if not design.is_file() or not dcds:
            raise FileNotFoundError(f"incomplete inputs for {job_id}")
        cases.append({
            "job_id": job_id, "family": family, "arrangement": arrangement,
            "lineage_id": lineage, "design": design, "design_source": design_source,
            "topology": topology, "dcds": dcds,
        })
    return cases


def _trajectory_duration_ps(paths: list[Path]) -> float:
    from MDAnalysis.coordinates.DCD import DCDReader

    duration = 0.0
    for path in paths:
        reader = DCDReader(str(path))
        duration += max(0, len(reader) - 1) * float(reader.dt)
        reader.close()
    return duration


def analyse(max_frames: int = 500, force: bool = False) -> None:
    from backend.core.kimmdy_analysis import analyze_kimmdy_trajectory, write_kimmdy_outputs
    from backend.core.models import Design

    JOBS.mkdir(parents=True, exist_ok=True)
    cases = _resolve_cases()
    for number, case in enumerate(cases, start=1):
        out = JOBS / case["job_id"]
        if (out / "summary.json").is_file() and not force:
            print(f"[{number}/{len(cases)}] {case['job_id']} cached", flush=True)
            continue
        print(f"[{number}/{len(cases)}] {case['job_id']} {case['family']} {case['arrangement']}", flush=True)
        design = Design.model_validate_json(case["design"].read_text())

        def progress(stage: str, done: int, total: int) -> None:
            if done == 1 or done == total or done % 100 == 0:
                print(f"  {stage} {done}/{total}", flush=True)

        report, series = analyze_kimmdy_trajectory(
            case["topology"], case["dcds"], design,
            pair_mode="all-tt", pair_scope="interstrand", screen_cutoff_ang=6.0,
            max_candidates=100_000, max_frames=max_frames, rate_model="periodic",
            progress=progress,
        )
        report["exp60"] = {
            "job_id": case["job_id"], "family": case["family"],
            "arrangement": case["arrangement"], "lineage_id": case["lineage_id"],
            "design_source": case["design_source"],
            "duration_ps": _trajectory_duration_ps(case["dcds"]),
        }
        write_kimmdy_outputs(report, series, out)


def _near_insert_keys() -> dict[str, set[tuple[str, int, str]]]:
    from backend.core.models import Design

    design_paths = {
        "24hb": ROOT / "workspace" / "24hb_2xT.nadoc",
        "6hbx100": ROOT / "workspace" / "6hbx100_1xT.nadoc",
    }
    output: dict[str, set[tuple[str, int, str]]] = {}
    for family, path in design_paths.items():
        design = Design.model_validate_json(path.read_text())
        keys: set[tuple[str, int, str]] = set()
        for crossover in design.crossovers:
            if not crossover.extra_bases:
                continue
            for half in (crossover.half_a, crossover.half_b):
                direction = getattr(half.strand, "value", str(half.strand))
                for delta in range(-2, 3):
                    keys.add((half.helix_id, int(half.index) + delta, direction))
        output[family] = keys
    return output


def _native_key(site: dict[str, Any]) -> tuple[str, int, str] | None:
    identity = site.get("design_identity") or {}
    if identity.get("kind") != "base":
        return None
    return (str(identity["helix_id"]), int(identity["bp_index"]), str(identity["direction"]))


def _pair_class(pair: dict[str, Any], near: set[tuple[str, int, str]]) -> str:
    identities = [pair[side].get("design_identity") or {} for side in ("site_a", "site_b")]
    extra = [identity.get("kind") == "crossover_insert" for identity in identities]
    if all(extra):
        return "designed_extra_extra" if pair.get("intended_weld") else "other_extra_extra"
    if any(extra):
        return "extra_native"
    keys = [_native_key(pair[side]) for side in ("site_a", "site_b")]
    return "native_native_near_insert" if any(key in near for key in keys) else "native_native_far"


def _bootstrap(values: list[float], seed: int) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = np.mean(rng.choice(array, size=(20_000, len(array)), replace=True), axis=1)
    return tuple(float(x) for x in np.percentile(samples, (2.5, 97.5)))


def summarize() -> None:
    from backend.core.cpd_metrics import REACTIVE_D_NM, REACTIVE_ETA_DEG, angular_separation_deg

    near_by_family = _near_insert_keys()
    pair_rows: list[dict[str, Any]] = []
    job_class_rows: list[dict[str, Any]] = []
    cases = {case["job_id"]: case for case in _resolve_cases()}
    for job_id, case in cases.items():
        out = JOBS / job_id
        report = _read_json(out / "summary.json")
        series = np.load(out / "timeseries.npz")
        pair_index = {str(pair_id): i for i, pair_id in enumerate(series["pair_ids"])}
        class_indices: dict[str, list[int]] = defaultdict(list)
        for pair in report["pairs"]:
            index = pair_index[pair["id"]]
            pair_class = _pair_class(pair, near_by_family[case["family"]])
            screen_hit = pair.get("screen_min_midpoint_ang") is not None
            # Intended pairs are forced into the raw KIMMDY output even if they never
            # enter the 6 Å discovery radius. Exclude those forced-only pairs from the
            # class sums so extra and native opportunity use the same spatial criterion.
            if screen_hit:
                class_indices[pair_class].append(index)
            k = np.asarray(series["periodic_propensity"])[index]
            d = np.asarray(series["d_mid_nm"])[index]
            eta = np.asarray(series["eta_deg"])[index]
            reactive = (d < REACTIVE_D_NM) & (angular_separation_deg(eta) < REACTIVE_ETA_DEG)
            pair_rows.append({
                "job_id": job_id, "lineage_id": case["lineage_id"],
                "family": case["family"], "arrangement": case["arrangement"],
                "pair_id": pair["id"], "pair_class": pair_class,
                "site_a": pair["site_a"]["site_id"], "site_b": pair["site_b"]["site_id"],
                "native_key_a": repr(_native_key(pair["site_a"])),
                "native_key_b": repr(_native_key(pair["site_b"])),
                "intended_weld": bool(pair.get("intended_weld")),
                "screen_hit": screen_hit,
                "screen_min_midpoint_ang": pair.get("screen_min_midpoint_ang"),
                "mean_k": float(np.mean(k)), "reactive_pct": float(100 * np.mean(reactive)),
            })

        n_frames = int(report["n_sampled_frames"])
        all_k = np.asarray(series["periodic_propensity"])
        all_d = np.asarray(series["d_mid_nm"])
        all_eta = np.asarray(series["eta_deg"])
        for pair_class in CLASSES:
            indices = class_indices.get(pair_class, [])
            if indices:
                k = all_k[indices]
                reactive = ((all_d[indices] < REACTIVE_D_NM)
                            & (angular_separation_deg(all_eta[indices]) < REACTIVE_ETA_DEG))
                sum_mean_k = float(np.sum(np.mean(k, axis=1)))
                event_rate = float(100 * np.sum(reactive) / n_frames)
                any_reactive = float(100 * np.mean(np.any(reactive, axis=0)))
            else:
                sum_mean_k = event_rate = any_reactive = 0.0
            job_class_rows.append({
                "job_id": job_id, "lineage_id": case["lineage_id"],
                "family": case["family"], "arrangement": case["arrangement"],
                "duration_ps": float(report["exp60"]["duration_ps"]),
                "sampled_frames": n_frames, "pair_class": pair_class,
                "candidate_pairs": len(indices), "sum_mean_k": sum_mean_k,
                "reactive_pair_events_per_100_frames": event_rate,
                "any_reactive_frame_pct": any_reactive,
            })
        if report.get("screen", {}).get("truncated"):
            raise RuntimeError(f"candidate screen truncated for {job_id}")

    _write_csv(PAIR_CSV, pair_rows)

    lineage_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in job_class_rows:
        lineage_groups[(row["lineage_id"], row["family"], row["arrangement"], row["pair_class"])].append(row)
    lineage_rows = []
    for (lineage, family, arrangement, pair_class), rows in sorted(lineage_groups.items()):
        weights = np.asarray([max(row["duration_ps"], 1.0) for row in rows])
        lineage_rows.append({
            "lineage_id": lineage, "family": family, "arrangement": arrangement,
            "pair_class": pair_class, "jobs": len(rows),
            "candidate_pairs_mean": float(np.average([row["candidate_pairs"] for row in rows], weights=weights)),
            "sum_mean_k": float(np.average([row["sum_mean_k"] for row in rows], weights=weights)),
            "reactive_pair_events_per_100_frames": float(np.average(
                [row["reactive_pair_events_per_100_frames"] for row in rows], weights=weights)),
            "any_reactive_frame_pct": float(np.average(
                [row["any_reactive_frame_pct"] for row in rows], weights=weights)),
        })
    _write_csv(LINEAGE_CSV, lineage_rows)

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lineage_rows:
        groups[(row["family"], row["arrangement"], row["pair_class"])].append(row)
    group_rows = []
    for (family, arrangement, pair_class), rows in sorted(groups.items()):
        vals = [row["sum_mean_k"] for row in rows]
        lo, hi = _bootstrap(vals, seed=60)
        group_rows.append({
            "family": family, "arrangement": arrangement, "pair_class": pair_class,
            "n_lineages": len(rows), "mean_candidate_pairs": float(np.mean(
                [row["candidate_pairs_mean"] for row in rows])),
            "mean_sum_k": float(np.mean(vals)), "sum_k_ci_lo": lo, "sum_k_ci_hi": hi,
            "mean_reactive_pair_events_per_100_frames": float(np.mean(
                [row["reactive_pair_events_per_100_frames"] for row in rows])),
            "mean_any_reactive_frame_pct": float(np.mean(
                [row["any_reactive_frame_pct"] for row in rows])),
        })
    _write_csv(GROUP_CSV, group_rows)
    _write_report(group_rows, pair_rows)


def _write_report(group_rows: list[dict[str, Any]], pair_rows: list[dict[str, Any]]) -> None:
    indexed = {(row["family"], row["arrangement"], row["pair_class"]): row for row in group_rows}

    def value(family: str, arrangement: str, classes: tuple[str, ...]) -> float:
        return sum(indexed[(family, arrangement, name)]["mean_sum_k"] for name in classes)

    def events(family: str, arrangement: str, classes: tuple[str, ...]) -> float:
        return sum(indexed[(family, arrangement, name)]["mean_reactive_pair_events_per_100_frames"]
                   for name in classes)

    extra_classes = ("designed_extra_extra", "other_extra_extra", "extra_native")
    native_classes = ("native_native_near_insert", "native_native_far")
    arrangements = (("24hb", "0-0"), ("24hb", "1-1"), ("24hb", "2-2"),
                    ("6hbx100", "0-0"), ("6hbx100", "1-1"))
    lines = [
        "# exp60 report — extra versus native interstrand TT opportunity",
        "",
        "## Question and scope",
        "",
        "This analysis asks whether added crossover thymines supply the interstrand photoproduct opportunity themselves, alter nearby native-thymidine opportunity, or are unnecessary because native–native pairs elsewhere already account for the signal. It uses all finite sampled frames with no structural gates.",
        "",
        "The observable is KIMMDY TT ground-state geometric propensity, not formed-product count or mechanical stability. Therefore the result decomposes *potential interstrand TT photoproduct opportunity*; it cannot assign a measured stability increase without experimental CPD yields and post-irradiation mechanics for the same constructs. Cytosine-containing CPDs are outside the currently implemented TT model.",
        "",
        "The 24hb 0×T, 1×T, and 2×T designs have identical native topology after insert annotations are removed. The 6hbx100 0×T and 1×T designs are likewise matched; no matched 6hbx100 2×T production trajectory exists. Native sites within ±2 bp of an insert-bearing crossover endpoint are classified as nearby in every member of a family, including its 0×T control.",
        "",
        "## Aggregate propensity partition",
        "",
        "`Σk` sums each screened interstrand pair's ensemble-mean corrected periodic propensity. Intended pairs that never enter the common 6 Å discovery radius remain in the raw audit but are excluded from these sums, ensuring that extra and native pairs use the same inclusion rule. Shares are descriptive opportunity mass, not reaction probabilities.",
        "",
        "| family | arrangement | native–native Σk | extra-involving Σk | extra share | native reactive events/100 frames | extra reactive events/100 frames |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, arrangement in arrangements:
        native = value(family, arrangement, native_classes)
        extra = value(family, arrangement, extra_classes)
        share = 100 * extra / (native + extra) if native + extra else 0.0
        lines.append(
            f"| {family} | {arrangement} | {native:.4f} | {extra:.4f} | {share:.1f}% | "
            f"{events(family, arrangement, native_classes):.3f} | "
            f"{events(family, arrangement, extra_classes):.3f} |"
        )

    lines += ["", "## Increment relative to the no-insert control", "",
              "The identity `total change = direct extra contribution + change in native–native contribution` is used below.", "",
              "| family | arrangement | total Σk change | direct extra Σk | native–native Σk change |",
              "|---|---:|---:|---:|---:|"]
    for family, arrangement in arrangements:
        if arrangement == "0-0":
            continue
        baseline = value(family, "0-0", native_classes)
        native = value(family, arrangement, native_classes)
        extra = value(family, arrangement, extra_classes)
        lines.append(f"| {family} | {arrangement} | {native + extra - baseline:+.4f} | {extra:.4f} | {native - baseline:+.4f} |")

    native_24_0 = value("24hb", "0-0", native_classes)
    native_24_1 = value("24hb", "1-1", native_classes)
    native_24_2 = value("24hb", "2-2", native_classes)
    extra_24_1 = value("24hb", "1-1", extra_classes)
    extra_24_2 = value("24hb", "2-2", extra_classes)
    increment_24_1 = native_24_1 + extra_24_1 - native_24_0
    increment_24_2 = native_24_2 + extra_24_2 - native_24_0
    designed_24_1 = value("24hb", "1-1", ("designed_extra_extra",))
    designed_24_2 = value("24hb", "2-2", ("designed_extra_extra",))
    extra_native_24_1 = value("24hb", "1-1", ("extra_native",))
    extra_native_24_2 = value("24hb", "2-2", ("extra_native",))
    native_6_0 = value("6hbx100", "0-0", native_classes)
    native_6_1 = value("6hbx100", "1-1", native_classes)
    extra_6_1 = value("6hbx100", "1-1", extra_classes)
    reactive_24_0 = events("24hb", "0-0", native_classes)
    reactive_native_24_1 = events("24hb", "1-1", native_classes)
    reactive_extra_24_1 = events("24hb", "1-1", extra_classes)
    reactive_native_24_2 = events("24hb", "2-2", native_classes)
    reactive_extra_24_2 = events("24hb", "2-2", extra_classes)
    lines += [
        "",
        "## Main findings",
        "",
        f"For 24hb 1+1, total screened opportunity rises by {increment_24_1:.4f} Σk above the 0×T control. Pairs containing an extra T contribute {extra_24_1:.4f} Σk, or {100 * extra_24_1 / increment_24_1:.1f}% of that increase; native–native pairs contribute only the remaining {100 * (native_24_1 - native_24_0) / increment_24_1:.1f}%. For 2+2, extra-involving pairs account for {100 * extra_24_2 / increment_24_2:.1f}% of the increase and the native–native change accounts for {100 * (native_24_2 - native_24_0) / increment_24_2:.1f}%.",
        "",
        f"The extra-T contribution is not limited to the intended reciprocal insert weld. In 24hb 1+1, designed extra–extra pairs contribute {designed_24_1:.4f} Σk ({100 * designed_24_1 / extra_24_1:.1f}% of extra-involving opportunity), while extra–native pairs contribute {extra_native_24_1:.4f} ({100 * extra_native_24_1 / extra_24_1:.1f}%). In 2+2 the split is {100 * designed_24_2 / extra_24_2:.1f}% designed extra–extra and {100 * extra_native_24_2 / extra_24_2:.1f}% extra–native (with the remainder from other extra–extra contacts). Thus inserted bases add many alternative interstrand contacts with native thymidines nearby.",
        "",
        f"The matched 6hbx100 1+1 ensemble does not show an aggregate gain: total Σk is {native_6_1 + extra_6_1:.4f}, compared with {native_6_0:.4f} in 0×T. The direct extra contribution ({extra_6_1:.4f}) is offset by a {native_6_1 - native_6_0:+.4f} change in native–native opportunity, and no extra-involving pair reaches the reactive corner in the three short 0.5 ns replicas. This family cannot establish a long-time effect because matched 1+1 production is short and matched 2+2 production is absent.",
        "",
        "## Strict reactive-corner result",
        "",
        f"The stricter binary criterion gives a different but complementary picture. The 24hb 0×T control has {reactive_24_0 / 100:.2f} native reactive pair-events per frame. The 1+1 trajectory has {(reactive_native_24_1 + reactive_extra_24_1) / 100:.2f} total events per frame, of which {100 * reactive_extra_24_1 / (reactive_native_24_1 + reactive_extra_24_1):.1f}% involve an extra T; 2+2 has {(reactive_native_24_2 + reactive_extra_24_2) / 100:.2f} events per frame, of which {100 * reactive_extra_24_2 / (reactive_native_24_2 + reactive_extra_24_2):.1f}% involve an extra T. Every 24hb condition already has at least one native reactive candidate in essentially every sampled frame.",
        "",
        "Thus the inserts do not raise the total strict reactive-event count above the no-insert trajectory. They create additional crossover-associated choices and shift some opportunity toward extra-involving sites. Any stability advantage would therefore have to depend on *where and which strands* are covalently linked, not simply on whether the structure contains any potentially reactive TT geometry.",
    ]

    lines += ["", "## Nearby-native test", "",
              "| family | arrangement | near-insert native Σk | far native Σk |",
              "|---|---:|---:|---:|"]
    for family, arrangement in arrangements:
        near = value(family, arrangement, ("native_native_near_insert",))
        far = value(family, arrangement, ("native_native_far",))
        lines.append(f"| {family} | {arrangement} | {near:.4f} | {far:.4f} |")

    n_pairs = len(pair_rows)
    near_24_0 = value("24hb", "0-0", ("native_native_near_insert",))
    near_24_1 = value("24hb", "1-1", ("native_native_near_insert",))
    near_24_2 = value("24hb", "2-2", ("native_native_near_insert",))
    near_6_0 = value("6hbx100", "0-0", ("native_native_near_insert",))
    near_6_1 = value("6hbx100", "1-1", ("native_native_near_insert",))
    lines += [
        "",
        "## Interpretation",
        "",
        f"There is no detectable enhancement of native–native propensity immediately around the 24hb insert sites: the nearby term changes by {100 * (near_24_1 / near_24_0 - 1):+.1f}% in 1+1 and {100 * (near_24_2 / near_24_0 - 1):+.1f}% in 2+2. In 6hbx100 it changes by {100 * (near_6_1 / near_6_0 - 1):+.1f}%. The data therefore favor a direct-extra mechanism over the hypothesis that inserts stabilize the structure primarily by making neighboring native–native TT pairs more photoreactive.",
        "",
        f"Native–native pairs still supply a large absolute background: {100 * native_24_1 / (native_24_1 + extra_24_1):.1f}% of total 24hb 1+1 propensity and {100 * native_24_2 / (native_24_2 + extra_24_2):.1f}% of 2+2 propensity. But that background is already present in 0×T and explains only {100 * (native_24_1 - native_24_0) / increment_24_1:.1f}% and {100 * (native_24_2 - native_24_0) / increment_24_2:.1f}%, respectively, of the *increase* in aggregate propensity. Moreover, a native CPD elsewhere need not topologically bridge a crossover or reproduce the mechanical effect of a deliberately located weld.",
        "",
        "Accordingly, the continuous Σk metric says extra bases account for nearly all of its 24hb increment, while the strict-corner metric shows that native bases already provide abundant background opportunities. These are not contradictory: the inserts add many moderate-propensity and strategically located candidates without increasing the global count of strict reactive events. A substantial portion of the insert-associated signal comes from extra–native alternatives rather than only the nominal extra–extra pair.",
        "",
        "The simulations therefore do not support the claim that improved mechanical stability can be explained merely by an increased number of native-site photoproduct opportunities. They also cannot exclude native products as contributors. Quantifying stability causally requires irradiated 0×T/1×T/2×T product yields, product-site mapping, and a topology-aware mechanical analysis or simulations with the candidate CPD bonds actually installed. Each 24hb condition currently has only one long lineage.",
        "",
        "Pair discovery retained every interstrand TT pair whose C5–C6 midpoint separation reached 6 Å in at least one sampled frame; no candidate list was truncated. KIMMDY also exported forced intended-weld records outside that radius, but they are marked `screen_hit=false` and excluded from the aggregate comparison. Pair identities and classifications are exported for audit.",
        "",
        "## Outputs",
        "",
        f"- `pair_summary.csv`: {n_pairs:,} job-specific pair records",
        "- `lineage_class_summary.csv`: independent-lineage class aggregates",
        "- `group_summary.csv`: family/arrangement comparisons",
        "- `results/jobs/<job_id>/`: all-T KIMMDY reports and time series",
        "",
    ]
    REPORT.write_text("\n".join(lines))
    print(REPORT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("analyse", "summarize", "all"))
    parser.add_argument("--max-frames", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command in {"analyse", "all"}:
        analyse(args.max_frames, args.force)
    if args.command in {"summarize", "all"}:
        summarize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
