"""
Exp08 — Real-time autostaple performance benchmark.

Measures wall-clock time for each stage of the full autostaple pipeline
across design sizes. Target: <100 ms total for 18HB at typical lengths.
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.core.lattice import compute_autostaple_plan, make_autostaple, make_bundle_design
from backend.core.models import Direction

sys.path.insert(0, str(Path(__file__).parent.parent / "exp07_nick_placement"))
from run import make_nicks_for_autostaple

# ── Cell layouts ──────────────────────────────────────────────────────────────

CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

# 2-helix strip (minimal case)
CELLS_2HX = [(0, 0), (0, 1)]

# 4×3 = 12 helices
CELLS_12HB = [(r, c) for r in range(4) for c in range(3)
              if (r + c % 2) % 3 != 2][:12]

# Larger: approximate 72 helices by repeating 18HB cells across rows
def _make_72hb():
    base = CELLS_18HB
    extra = [(r + 6, c) for r, c in base]
    extra2 = [(r + 12, c) for r, c in base]
    extra3 = [(r + 18, c) for r, c in base]
    return base + extra + extra2 + extra3

CELLS_72HB = _make_72hb()

# ── Benchmark ─────────────────────────────────────────────────────────────────

N_WARMUP = 1
N_RUNS   = 3


def bench(cells, length_bp: int, label: str) -> dict:
    # Warmup
    for _ in range(N_WARMUP):
        d = make_bundle_design(cells, length_bp=length_bp)
        make_autostaple(d)

    times_plan = []
    times_apply = []
    times_nick = []

    for _ in range(N_RUNS):
        d = make_bundle_design(cells, length_bp=length_bp)
        n_helices = len(d.helices)

        t0 = time.perf_counter()
        plan = compute_autostaple_plan(d)
        t1 = time.perf_counter()

        result = make_autostaple(d)
        t2 = time.perf_counter()

        result_nicked = make_nicks_for_autostaple(result)
        t3 = time.perf_counter()

        times_plan.append((t1 - t0) * 1000)
        times_apply.append((t2 - t0) * 1000)   # plan + apply
        times_nick.append((t3 - t2) * 1000)

    return {
        "label": label,
        "n_helices": n_helices,
        "length_bp": length_bp,
        "n_plan": len(plan),
        "plan_ms":   sum(times_plan) / N_RUNS,
        "apply_ms":  sum(times_apply) / N_RUNS,
        "nick_ms":   sum(times_nick) / N_RUNS,
        "total_ms":  sum(t_a + t_n for t_a, t_n in zip(times_apply, times_nick)) / N_RUNS,
    }


if __name__ == "__main__":
    RT_THRESHOLD = 100  # ms — target for real-time feel

    configs = [
        (CELLS_2HX,  42,  "2HX  42bp"),
        (CELLS_2HX,  126, "2HX 126bp"),
        (CELLS_18HB, 42,  "18HB  42bp"),
        (CELLS_18HB, 126, "18HB 126bp"),
        (CELLS_18HB, 252, "18HB 252bp"),
        (CELLS_72HB, 42,  "72HB  42bp"),
        (CELLS_72HB, 126, "72HB 126bp"),
    ]

    results = []
    print(f"{'Design':<14} {'H':>4} {'bp':>5} {'plan':>7} {'apply':>7} {'nick':>7} {'total':>7}  RT?")
    print("─" * 65)

    for cells, lbp, label in configs:
        r = bench(cells, lbp, label)
        results.append(r)
        rt = "✓" if r["total_ms"] < RT_THRESHOLD else "✗"
        print(f"{label:<14} {r['n_helices']:>4} {lbp:>5} "
              f"{r['plan_ms']:>6.1f}ms {r['apply_ms']:>6.1f}ms "
              f"{r['nick_ms']:>6.1f}ms {r['total_ms']:>6.1f}ms  {rt}")

    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    with open(out / "metrics.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to {out}/metrics.json")

    # Bottleneck analysis
    worst_18hb = max((r for r in results if "18HB" in r["label"]), key=lambda r: r["total_ms"])
    print(f"\nBottleneck for 18HB: plan={worst_18hb['plan_ms']:.1f}ms  "
          f"apply={worst_18hb['apply_ms']:.1f}ms  nick={worst_18hb['nick_ms']:.1f}ms")
    dominant = max(["plan", "apply", "nick"], key=lambda k: worst_18hb[f"{k}_ms"])
    print(f"Dominant stage: {dominant}")

    # Verdict
    all_18hb_ok = all(r["total_ms"] < RT_THRESHOLD for r in results if "18HB" in r["label"])
    print(f"\n18HB real-time (<{RT_THRESHOLD}ms): {'✓ PASS' if all_18hb_ok else '✗ FAIL'}")
