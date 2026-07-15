# Autonomous RunPod NAMD — confirmation-coded toolchain

Goal: launch a NAMD job on *any* compatible RunPod GPU with a **verified confirmation code at
every money-moving step** (pod SETUP, job LAUNCH, pod TERMINATION), such that a step which
finishes *without* a code automatically triggers a review instead of silently spending. Built
2026-07-15 to benchmark higher-end cards (H100/H200) on the `24hb_0xT` structure.

## The confirmation contract (the core idea)

A confirmation code is **not** "the API returned 200". The runbook's failure catalogue is full
of calls that returned success while the thing they claimed never happened (a `terminate` that
left a pod billing; a launch that died at step 0 on the wrong GPU arch). So a code here is a
**verified-state receipt** — minted only after the code independently *re-queries* RunPod / the
pod and proves the post-condition:

| step | proof required before a code is minted |
|---|---|
| **setup** | `get_pod` shows `RUNNING` **and** a public IP + SSH port (not just "create returned an id") |
| **launch** | NAMD process alive **and** its log is growing / has a progress marker, **and** no "no kernel image" / FATAL |
| **terminate** | pod is **gone from `list_pods`** (or `desired_status` destroyed) — not "delete returned 200" |

No proof → no code → `guarded_step` writes the step to `review_queue.jsonl` and raises
`NoConfirmation`. The campaign **refuses to keep spending while the review queue is non-empty**
(`ConfirmationLog.require_clean()`), so a missing confirmation halts the run and demands a
safeguard — exactly the requested behaviour.

`runpod_confirm.py` holds this framework; `test_runpod_confirm.py` proves its invariants
(19 tests, run with `python experiments/exp43_runpod_bench/test_runpod_confirm.py`).

## Files

| file | role |
|---|---|
| `runpod_confirm.py` | the confirmation framework: `Receipt`, `ConfirmationLog`, `guarded_step`, the three `confirm_*` verifiers |
| `test_runpod_confirm.py` | 19 self-contained tests (no network, no pytest — dodges no test guard) |
| `campaign_common.py` | one confirm-gated pod lifecycle (`confirmed_pod`) reused by every script; container-disk, not region-pinned |
| `pod_watchdog.py` | **autonomous backstop** — polls RunPod, enforces `$budget` + max pod age, kills only campaign-named pods, verifies each kill |
| `build_bench_package.py` | assemble the 346 MB trimmed `24hb_0xT` bench package (production-cadence conf, relaxed seed) |
| `fetch_namd.py` | pull the NAMD build off the EU-RO-1 volume to local (one cheap pod) so it can travel to any region |
| `bench_anypod.py` | the reusable `$/ns` benchmark: rent → upload → run → measure → destroy, all confirm-gated |

## Run order (each step is idempotent)

```bash
export PATH="$HOME/.local/bin:$PATH"
export RUNPOD_API_KEY=$(cat ~/.runpod_key)

# 0. balance gate (never rent below the reserve)
python experiments/exp43_runpod_bench/balance.py --require 10

# 1. build the bench package (free, local, ~1 min)
python experiments/exp43_runpod_bench/build_bench_package.py

# 2. ALWAYS start the watchdog FIRST, in the background — the hard $ backstop
python experiments/exp43_runpod_bench/pod_watchdog.py --budget 5 --max-pod-min 25 &

# 3. fetch NAMD to local (one cheap pod; proves the full confirm lifecycle)
python experiments/exp43_runpod_bench/fetch_namd.py

# 4. benchmark the cards (container-disk, any region; stops at --budget)
python experiments/exp43_runpod_bench/bench_anypod.py --budget 5 --only "H100 PCIe,H200 SXM"

# 5. teardown proof — MUST read 0 pods
python experiments/exp43_runpod_bench/reap.py
```

## Safety invariants (why this can run unattended)

- **The watchdog only ever destroys campaign-named pods** (`nadoc-bench`/`nadoc-fetch`/
  `nadoc-stage`). An unknown pod is WARNed, never killed — so it cannot repeat the "destroyed
  EVERY pod on the account" incident (git `ad72…`). `reap.py --kill` remains the human all-pods
  button.
- **Isolated spend accounting.** The campaign ledger lives at
  `/media/jojo/Archive/nadoc_bench_campaign/spend.json`, one level *above* `nadoc_jobs/`, so
  `SpendLedger.spent()` sums only this campaign — a $5 budget does not inherit the old ~$80.
- **Billing is booked at pod creation, not at SSH-ready** (`on_created`), so a pod that boots
  but never exposes SSH still reaches the ledger and the budget guard.
- **Container-disk only** — no network volume, so nothing pins the region and there is no
  shared volume a bench pod could corrupt for a live run.

## Two conf bugs the confirmation layer caught (both on a $0.99 canary, not an H100)

Both were **silent-at-the-API** — the pod rented fine, NAMD launched, then died at setup. Neither
produced a benchmark number; the launch confirmation refused to mint a code and captured the exact
FATAL into the review queue, so each was diagnosed without the pod and fixed for pennies.

1. **Periodic cell defined twice.** `namd_fast.conf` hardcodes `cellBasisVector*/cellOrigin`; the
   bench seeds the cell from the checkpoint `.xsc` via `extendedSystem`. NAMD FATALs on a
   double-defined cell. Fix: strip the hardcoded cell block when seeding from a checkpoint.
2. **Seed keywords placed AFTER `run`.** NAMD executes `run` at parse time, so `binCoordinates/
   binVelocities/extendedSystem` appended *after* it are never read → "Must have either an initial
   temperature or a velocity file." Fix: inject the seed block immediately *before* `run`.

Lesson reinforced: **run a cheap canary (L40S) before the expensive cards.** The container-disk
path re-uploads NAMD+package per pod, so a conf bug on an H100 costs the same upload minutes as on
an L40S but at 3x the rate. The canary caught both bugs for ~$0.5 total.

## Measured results — 24hb_0xT (1.32M atoms), production conf (fullElect 1), 2000 steps @ 4 fs

Live secure prices (the GraphQL `lowestPrice` is a community floor — the driver bills the real
`pod.cost_per_hr`). Ordered by $/ns.

Ordered by $/ns within tier. Campaign total **$1.32** (fetch $0.05 + 2 canary/debug pods ~$0.5 +
4 high-end cards $0.77), well under the $5 cap. `NAMD 3.0.2 multicore-CUDA` sm_90 confirmed running
on every H100/H200 (arch never an issue — the risk was all conf).

| card | arch | $/hr | ms/step | ns/day | $/ns | note |
|---|---|---|---|---|---|---|
| **H100 SXM** | sm_90 | 2.99 | **8.8** | 39.3 | **1.83** | **best high-end value; near-fastest** |
| H100 PCIe | sm_90 | 2.89 | 11.7 | 29.5 | 2.35 | slower than SXM (less bandwidth) |
| H200 SXM | sm_90 | 4.39 | **8.3** | **41.5** | 2.54 | fastest, but +47% $ for +6% speed |
| H100 NVL | sm_90 | 3.19 | 13.1 | 26.4 | 2.90 | worst value (throttled host draw?) |
| L40S | sm_89 | 0.99 | 19.6 | 17.6 | **1.35** | overall value champ if wall-clock allows |

**Findings for a 1.32M-atom system (fits in 80 GB):**
- **H100 SXM is the pick among high-end** — nearly as fast as H200 (8.8 vs 8.3 ms/step) at 2/3 the
  price. HBM3 bandwidth is what matters for this memory-bound MD, so SXM > PCIe on both axes.
- **H200's 141 GB buys nothing here** — it only helps a system too big for 80 GB. +6% speed for +47%
  money. Reach for it only when the box doesn't fit an H100.
- **L40S is the value champion** (`$1.35/ns`) but 2.2x slower wall-clock — good for throughput/queued
  runs, bad for a single run you're waiting on. Per `feedback_gpu_value_is_two_axes`: judge $/ns AND
  ns/day. A 50 ns production run is ~68 h on L40S vs ~30 h on H100 SXM.
- **H100 NVL underperformed** its price — one draw; re-bench before trusting it (a single sample can
  be a slow host).

### Projected 50 ns production run (steady-state)

Extrapolated from the measured `ns/day` at the production integrator: `wall_h = 50 / ns_day * 24`,
`cost = wall_h * $/hr`. **Steady-state only** — excludes the one-time relaxation ladder (already done
for 0xT), pod provisioning, package upload, and result download. On-demand SECURE prices as drawn
2026-07-15 (volatile; re-check before a real run). Ranked by wall-clock.

| card | $/hr | ns/day | **50 ns wall** | **50 ns cost** | verdict |
|---|---|---|---|---|---|
| H200 SXM | 4.39 | 41.5 | **28.9 h** (1.20 d) | **$127** | fastest; you pay for it |
| **H100 SXM** | 2.99 | 39.3 | **30.5 h** (1.27 d) | **$91** | **best overall — ~2 h slower than H200, $36 cheaper** |
| H100 PCIe | 2.89 | 29.5 | 40.7 h (1.70 d) | $118 | no reason over SXM |
| H100 NVL | 3.19 | 26.4 | 45.5 h (1.89 d) | $145 | worst on both axes (one draw) |
| L40S | 0.99 | 17.6 | 68.2 h (2.84 d) | **$67** | cheapest 50 ns, but ~2.4 d wall |

**Reading it:** if a 50 ns run must land overnight, **H100 SXM ($91, 30 h)** is the sweet spot — H200
saves ~2 h for +$36. If wall-clock is not the constraint (queued/background), **L40S is cheapest at
$67** but takes ~2.4 days. The three-variant 0/1/2xT campaign (150 ns total) scales linearly:
~$275 / ~4 days on H100 SXM, or ~$200 / ~8.5 days on L40S.

⚠️ **Upload dominates cost on this path.** NAMD (263 MB) + package (95 MB) re-upload per pod; uplink
varied 0.8–10 MB/s by region (27 s to 281 s for the NAMD tar). Everything downstream was seconds. If
benchmarking many cards in one region, staging a network volume ONCE would remove the repeat upload —
the tradeoff is region-lock. For a few cards across regions, container-disk (this path) is simpler and
was ~$0.2/card in upload overhead.
