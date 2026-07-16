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

**All rows MEASURED** (no estimates — the scaled 4090/PRO 4500 guesses were both ~10–25%
optimistic, so every card was run for real). Live SECURE prices as drawn 2026-07-15; the driver
bills `pod.cost_per_hr` (the GraphQL `lowestPrice` is a community floor). `NAMD 3.0.2
multicore-CUDA` (sm_80/89/90/120) ran on every in-arch card; arch was never the failure — conf was.
Sorted by $/ns. `50 ns wall = ms_step × 3.472 h`, `50 ns cost = $/ns × 50` (steady-state; excludes
the one-time ladder, provisioning, upload, download).

| card | arch | VRAM | $/hr | ms/step | ns/day | $/ns | 50 ns wall | 50 ns cost |
|---|---|---|---|---|---|---|---|---|
| **RTX 6000 Ada** | sm_89 | 48 GB | 0.77 | 15.2 | 22.8 | **0.81** | 53 h | **$41** |
| RTX 4090 | sm_89 | 24 GB | 0.69 | 20.0 | 17.3 | 0.96 | 69 h | $48 |
| **RTX 5090** | sm_120 | 32 GB | 0.99 | 14.5 | 23.8 | 1.00 | 50 h | $50 |
| RTX PRO 4500 | sm_120 | 32 GB | 0.74 | 19.9 | 17.4 | 1.02 | 69 h | $51 |
| L40S | sm_89 | 48 GB | 0.99 | 19.6 | 17.6 | 1.35 | 68 h | $67 |
| **H100 SXM** | sm_90 | 80 GB | 2.99 | 8.8 | 39.3 | 1.83 | 31 h | $92 |
| H100 PCIe | sm_90 | 80 GB | 2.89 | 11.7 | 29.5 | 2.35 | 41 h | $118 |
| H200 SXM | sm_90 | 141 GB | 4.39 | **8.3** | **41.5** | 2.53 | **29 h** | $127 |
| H100 NVL | sm_90 | 94 GB | 3.19 | 13.1 | 26.4 | 2.90 | 45 h | $145 |
| RTX 3090 · RTX A6000 | sm_86 | 24 / 48 GB | 0.22 / 0.49 | — | — | — | — | needs an sm_86 NAMD rebuild |

**Findings for a 1.32M-atom system (fits in 24 GB GPU-resident, ~4.5 GB):**
- **RTX 6000 Ada is the overall value champion — $0.81/ns, $41 for 50 ns.** Full AD102 die, so it's
  faster than the 4090/PRO 4500 *and* cheapest per ns of everything measured. 48 GB means it also holds
  the seeded 1xT/2xT builds (2.3–2.6 M atoms) that the 24 GB 4090/5090 can't.
- **RTX 5090 is the fastest sub-$1/hr card** (14.5 ms/step, 23.8 ns/day) at $1.00/ns — pick it in the
  value tier when you want speed. It obsoletes the L40S (faster AND cheaper per ns).
- **The value tier is tighter than the estimates suggested.** 4090/PRO 4500/L40S all cluster at ~20
  ms/step; real $/ns is $0.81–1.35, not the ~$0.71–0.92 the scaling predicted. The old 11.2
  ms/step·Matom⁻¹ 4090 fit doesn't transfer to this system (real ≈ 15.2) — **re-bench, don't scale.**
- **Speed tier (H100/H200):** H100 SXM is the pick — nearly as fast as H200 (8.8 vs 8.3 ms/step) at
  2/3 the price; HBM3 bandwidth is what matters for this memory-bound MD (SXM > PCIe on both axes).
  H200's 141 GB buys nothing under 80 GB (+6% speed for +47% $). H100 NVL underperformed (one draw).

**Two tiers, both fully measured.** Value ($0.81–1.35/ns, ~50–69 h/50 ns) vs Speed ($1.83–2.90/ns,
~29–45 h). Value is ~2× cheaper per ns but ~1.7–2.4× slower wall-clock (`feedback_gpu_value_is_two_axes`).

**Picks:** throughput / cost-sensitive → **RTX 6000 Ada** ($41/50 ns); need it overnight → **H100 SXM**
($92, 31 h); fast-but-cheap → **RTX 5090** ($50, 50 h). The 3-variant 0/1/2xT campaign (150 ns) scales
~linearly: ~$123 on RTX 6000 Ada (~6.5 d) or ~$275 on H100 SXM (~4 d) — but the 2.3–2.6 M-atom seeded
builds run slower per ns than this 1.32 M control, so treat those as a floor.

**Arch gate (safeguard added this session):** a card whose `compute_cap` ∉ {8.0, 8.9, 9.0, 12.0} is
rejected in ~2 s *before* the 360 MB upload (RTX 3090 sm_86, RTX A6000 sm_86 both caught for
~$0.005). Benchmarking sm_86 (3090/A6000) or sm_75 would need those archs added to the NAMD build.

⚠️ **Upload dominates cost on this path.** NAMD (263 MB) + package (95 MB) re-upload per pod; uplink
varied 0.8–10 MB/s by region (27 s to 281 s for the NAMD tar). Everything downstream was seconds. If
benchmarking many cards in one region, staging a network volume ONCE would remove the repeat upload —
the tradeoff is region-lock. For a few cards across regions, container-disk (this path) is simpler and
was ~$0.2/card in upload overhead.
