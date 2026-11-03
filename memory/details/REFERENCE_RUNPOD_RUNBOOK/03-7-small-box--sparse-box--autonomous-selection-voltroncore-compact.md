# 7. Small-box / sparse-box / autonomous selection (VoltronCore compact, 2026-07-24) — supporting detail

[Topic head](../../REFERENCE_RUNPOD_RUNBOOK.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## 7. Small-box / sparse-box / autonomous selection (VoltronCore compact, 2026-07-24)

A 1.31M-atom **compact** run (23%-fill water-shell box, oxDNA-relaxed VoltronCore) re-learned a
stack of things §0–6 did not cover. §0–6 came from *full-box, H100, 3.0.2-release* runs; none of
its numbers or card choices transfer to a *sparse, small, cheap-card* run. The general rule
under all of this: **the fullbox bench predicted almost nothing about a different box on a
different card — re-measure resident-capability, timestep stability, AND rate empirically every
time, on the actual card class.** Reusable launcher: `launch_voltron_compact.py`.

**Build × box-fill decides GPU-resident — not the GPU.**
- The **3.0.2 release** dies at **step 0** on a sparse (water-shell/carved, <~90% fill) cell:
  `FATAL ERROR: Low global CUDA exclusion count! (N vs M)`. Fires on 4 fs AND 2 fs → it is NOT a
  timestep problem, it is resident-tiling on a vacuum-containing cell.
- The **Dec-2025 git build** does sparse-cell GPU-resident fine (that is literally what runs
  locally). **For any carved/shell box you must ship the git build**, or fall back to CUDA-offload
  (a different code path that tolerates sparse cells, ~2.6× slower). Switching GPU does NOT help —
  same 3.0.2 → same failure on any card.
- Package the git build once: `tar czf namd_git.tar.gz -C <build>/Linux-x86_64-g++ namd3`
  (302 MB→167 MB). It statically links CUDA; the pod needs only `apt-get install -y libtcl8.6
  libfftw3-single3`. Verify `ldd namd3 | grep 'not found'` is empty before trusting it.

**The git build is multi-arch sm_50…sm_90 — NO sm_120.** So the **RTX 5090 (Blackwell) cannot run
it.** "5090 or higher" is self-contradictory with the git build; usable cards top out at
sm_90 (H100/H200). Rebuilding NAMD +sm_120 = a multi-hour on-pod recompile — not worth it.
**Always arch-gate the offered card against the build's ACTUAL arch set** (git: {5.0,6.0,7.0,7.5,
8.0,8.6,8.9,9.0}; the multi-arch 3.0.2 tar: {8.0,8.9,9.0,12.0}).

**Best $/ns for a SMALL box is a cheap Ada/Ampere card, NOT an H100.** Measured on the 1.31M box,
4 fs GPU-resident: **RTX 4090 (sm_89, $0.69/hr) ≈ 24 ns/day ≈ $0.69/ns.** An H100 SXM is ~1.6×
faster wall-clock but ~5× the $/ns — its horsepower is wasted below a few M atoms. The
`gpu_value_is_two_axes` rule flips with box size: **H100/H200 win value only on the huge (10 M+)
boxes of §1; small boxes want the cheapest arch-compatible card that still fills.**

**Same GPU model, different pod = different rate — bench the ACTUAL pod.** The bench 4090 did
14.3 ms/step (24 ns/day); a *second* 4090 for the production run did 21.5 ms/step (**16 ns/day**) —
same conf, same box, ~1.5× slower, from RunPod's per-pod vCPU/host/thermal variance. **Size the run
from a rate measured on THE pod you are on, never a prior pod's.**

**Prove timestep stability ONCE, then FORCE it — do not re-probe every run.** 4 fs stability is a
*system* property (ssDNA + HMR + rigidBonds integrator), card-independent. The launcher's 20k-step
4 fs "probe" used a fixed **240 s wall-clock window**; on a slower card 20k steps don't finish in
240 s → "no verdict" → silent **conservative fallback to 2 fs = HALF speed**. Two fixes, both
applied: probe verdict must be **step-count based** (N clean steps), and once 4 fs is proven for a
system, pass **`--force-4fs`** to skip the probe entirely. (VoltronCore's free ssDNA: 4 fs is
PROVEN stable — force it.)

**Never let a fallback silently degrade value.** When the target 4090 was a dud, the launcher fell
back to an **A6000** (2× worse $/ns) AND its slow rate tripped the probe→2 fs fallback (another 2×)
= **4× worse than intended, silently**, at 2 ns/day. **Bound the fallback list to same-value-tier
cards; prefer retrying for the target card over renting a poor-value one.**

**Two launcher bugs that hung/failed the paid path (both fixed, keep the fix):**
- Backgrounded SSH launch (`setsid nohup … & echo $!`) occasionally returns **no channel-EOF** on
  a quirky/slow pod → `conn.run` times out even though the process started. **Tolerate the timeout
  and verify liveness separately** (deadman via its own log line; NAMD via log-file growth — never
  `pgrep namd3`, it renames to "NAMD masterPe", §3).
- **No-SSH dud pods** (rent RUNNING, never expose SSH within 900 s) are common. **Acquisition
  retry**: terminate the dud, rent a fresh pod, up to N attempts; set a `committed` flag at NAMD
  launch so a failure AFTER the run starts does NOT restart an expensive run.

**Teardown + deadman are proven (watched firing).** Across 4 induced failures + 3 clean runs,
`confirmed_pod`'s finally left **0 pods** every time; the **pod-side deadman self-terminated 78 s**
after the controller went dark (zero-secret, via the pod-injected key in `/proc/1/environ`); the
SANITY monitor caught an injected `Atoms moving too fast` and tore down. **Cheap preflight (~$1
over 8 pods) is worth it — it found both bugs and the wrong-config trap before the paid run.**

---

## 8. The unified pipeline (autonomous, no intervention)

The end-to-end order every RunPod NAMD job should follow — each stage encodes a §5/§7 lesson so
they are not re-learned. Driver: `experiments/exp43_runpod_bench/launch_voltron_compact.py`
(generalize per-job).

1. **ASSESS** — atom count + **box fill fraction** (`md_vram.carve_fill_fraction`). Fill <~90% →
   sparse → **git build (resident) or offload**; ≥90% → either build. Atom count → VRAM floor →
   min card memory. Look up (or probe once) timestep stability for the system.
2. **SELECT CARD** — poll RunPod for **available** GPU types + live prices; filter to
   `arch ∈ build.arches` AND `vram ≥ floor` AND in-stock; **rank by $/ns** (measured-rate registry
   per arch, else estimate). Small box → cheapest compatible; huge box → H100/H200. Fallback list =
   same-value-tier only. **Never a card outside the build's arch set** (silent step-0 death).
3. **PACKAGE** — stage the right NAMD build tar (git for sparse) + solvated system + confs + HMR
   PSF (for 4 fs). Compress the binary; verify `ldd … | grep 'not found'` empty on the pod.
4. **PREFLIGHT (cheap, on the chosen pod)** — arm deadman; a short run to **measure the REAL
   ms/step on THIS pod**, confirm resident works on this box, confirm the timestep holds (step-based
   probe). **Size the full run from the measured rate + budget.** Killswitch tests
   (`deadman_test.py`, `--inject-fail`) are generic — run once per toolchain change, not per job.
5. **RUN** — full production; monitors = budget + stall (flat step count) + blowup (BLOWUP_RE) kill,
   deadman heartbeat refresh each poll, **selective auto-fetch before teardown** (container disk
   dies with the pod), `confirmed_pod` prove-destroyed. `pod_watchdog.py` as the independent
   budget/age backstop. All autonomous; dud-retry throughout.

**Implemented** (`launch_voltron_compact.py`, spec-driven — pass a `JobSpec`, defaults to
VoltronCore compact; tests `test_runpod_select.py` + `test_runpod_launch_pipeline.py`):
- **ASSESS**: `natom_from_package` reads `!NATOM` from the package PSF (past the multi-thousand-line
  NTITLE block — a naive small read-cap misses it), so atom count is never hard-coded.
- **SELECT**: `backend/core/runpod_select.pick_cards` — live stock/price × `BUILD_ARCHS` × VRAM ×
  $/ns with a speed floor; returns a fast same-tier fallback list.
- **LEARN**: a per-arch rate registry (`gpu_rates.json`, running mean of accepted-run ms/step-per-
  Matom) refines the $/ns estimate + reroll floor over time — `record_rate` folds in each accepted
  run, `estimate_rate(registry=…)` uses it above 2 samples, else the conservative static prior.
  (Only ACCEPTED/post-reroll rates are recorded, so slow-pod outliers never pollute the mean.)
- **AUTO-REROLL** (the per-pod-variance fix): after warmup (~8k steps) it measures the REAL rate and,
  if `< reroll_floor × estimate_rate(card)` (default 0.7×), kills + rents a fresh pod — bounded by
  `--max-reroll` (default 2), then accepts the next pod as-is. This is what would have caught the
  16-ns/day dud 4090 automatically. A rerolled pod is terminated by `confirmed_pod` (no fetch).
