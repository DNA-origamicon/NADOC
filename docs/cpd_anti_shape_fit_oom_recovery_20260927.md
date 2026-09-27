# Interrupted second fit: evidence and prepared recovery

**Current status:** the authorized recovery ended at the original04:29:42UTC
deadline. See the [audited closeout](cpd_anti_shape_fit_closeout_20260927.md).
Selected model61 has three shape failures; no scientific qualification. The
service wake was delivered and ACKed04:30:00UTC. No fit is running. The following
preserves the OOM evidence, preparation and initial recovery handoff.

The second fit stopped at **2026-09-27 02:41:50 UTC**, about 12 minutes after
launch. The kernel identifies a memory-cgroup OOM in this exact service, whose
limit was 6 GiB. It killed Python PID2179155 with approximately6.19 million KiB
of anonymous resident memory. This is an execution/resource failure, not an
optimizer convergence result. The raw `status.json` still says `running` because
the supervisor was also stopped; it is preserved as stale evidence.

Wake `2c49745f-d67f-4036-9db5-0acec5e1b04e`, event `supervisor_stopped`, was
acknowledged at02:43:38UTC. The service directory contains archived systemd,
service-journal and kernel records plus `completion_delivery_verified.json`.

## What survived and was verified

- 33 complete parameter-vector evaluations, each with26 fragment optimizations.
- Model34 has16 complete fragments and an interrupted seventeenth fragment.
- Independent audit verifies **874 complete fragments / 29,870 saved MM evaluations**:
  native trajectories, atom order, saved energies/forces, exported final E/F,
  stationarity/constraints, chemistry, shape, and all33 objective/residual vectors.
- The interrupted fragment has eight saved evaluations and projected maximum
  gradient5.50409 kcal/mol/Å; it is nonstationary and receives no completion credit.
- Every completed model fails at least one development gate. There is no final
  fitted/qualified candidate and no minimum certification.

The lowest-objective completed trial is **model32**, a derivative probe retained
under the original selection rule. Its 23 exposed-point energy RMS/max is
**0.426142 / 1.127347 kcal/mol**; all three representative geometry tests pass.
Shape failures fall from eight to six: original endpoint2 −15°, −7.5°, and lower
+15° improve, but endpoint1 +30° becomes a new failure. Endpoint1 −15°, −7.5°,
−30°, prospective −22.5°, and the lower endpoint2 reference still fail. This is
partial progress, not a passed fit or proof that the chosen model is incapable
of meeting the gates.

## Prepared repair and checks

The implementation is
[`shape_fit_isolated_recovery_v1.py`](../experiments/cpd_anti_additive/shape_fit_isolated_recovery_v1.py),
with a separate cached-Sella replay helper. Its frozen recovery plan and checks
are in `cpd-anti-shape-recovery-preparation-v1b`.

The coordinator reconstructs the same SciPy optimizer by replaying saved
residuals. Each uncached model then runs in a fresh child process, releasing that
process's caches/allocations on exit. The precise allocator responsible for the
original growth is not established; no claim that Sella's numerical algorithm
failed follows from the OOM. The change isolates resource lifetime without
changing energies, variables, geometry settings, objective or acceptance gates.

Verified without any new QM/MM energy calculation or fit evaluation:

1. Replaying all33 complete residuals reaches model34 with **bitwise identical
   parameters**. No optimizer-history reset or replacement start.
2. The isolated result assembler reproduces all33 saved residual vectors and
   verdicts **bitwise identically**.
3. Cached forces reproduce one complete37-evaluation Sella optimization and all
   eight evaluations of the interrupted case. The diagnostic stops before its
   next uncomputed force. Its process peaked at392,628KiB RSS. This checks replay,
   not a complete memory stress test of the repaired campaign.
4. Four guard tests pass; execution without explicit recovery authorization is
   rejected before creating the recovery output directory.

The initial replay-helper probe stopped on a missing `Path` import before any
Sella evaluation. Its source/error remains under preparation-v1; the corrected
v1b tests pass. Original scientific artifacts, locks, verdicts and ledgers were
not rewritten.

## Proposed recovery limits

This is recovery of the interrupted second round, **not a third fit**. It
reuses33 complete models and model34's16 complete fragments; its eight cached
Sella evaluations count toward the original600-evaluation/400-step case caps.
A changed replay path fails closed rather than silently starting afresh.

The recovery retains the original6GiB memory limit, CPUs4–7,360 total model-vector
cap including derivative probes, max_nfev12, and the original absolute fitting
deadline **2026-09-27 04:29:42 UTC (September26,22:29:42 MDT)**. Offline review and
repair time do not reset this window. It creates a new output directory, preserves
all earlier evidence, and has no automatic second recovery attempt. It cannot run
after that original deadline under this plan.

**Recovery authorized and launched at 2026-09-27 04:16:06 UTC.** The user instructed
“Resume with the interrupted round.” Preparation-v1b now contains an exclusive
`authorization.json` identifying recovery-plan SHA256
`262ea4d63d8505dedf714f9a99a349abda9175236c2e65689f55980988d1dc2a`.
The earlier `pending_confirmation.json` remains an unchanged historical receipt.
All pinned inputs and preparation checks were verified again before launch.

Service `cpd-anti-shape-fit-recovery-service-v1` runs the same interrupted round;
output is `cpd-anti-shape-fit-recovery-v1`. Supervisor PID2434317, external watcher
PID2434319, token `5b5de21a-1f24-4815-8a3f-36f4abb54225` (since delivered/ACKed).
Model34 has completed, retaining six shape failures. Independent
`recovered_model34_verified.json` checks all26 fragments /909 saved evaluations,
final exported energy/forces, three constraint projections, chemistry, shape,
and the exact residual vector. Its16 completed fragments were reused unchanged;
the interrupted fragment replayed eight cached evaluations and used26 new ones.
This verifies numerical completion, not minimum certification or qualification.

At the handoff check,41 models were complete (eight more than before recovery).
Best trial36 reports energy RMS0.424368/max1.094948 kcal/mol and still six shape
failures. `handoff_health.json` records live coordinator/child identities on
CPUs4–7, the armed watcher, and a memory peak of704,380,928 bytes (672MiB), below
the unchanged6GiB cap. This observation is not a guarantee for the remaining run.
About815 seconds remained at launch before the original absolute
04:29:42UTC fitting deadline. The service cap also remains inside the original
04:44:42UTC outer limit; authorization did not reset either clock.

The frozen [second-round contract](cpd_anti_shape_fit_v2_r2.md) says “No automatic
restart or continuation.” This explicit authorization covers this one prepared
recovery. No larger fitting budget, additional round, QM target acquisition,
context MD, normal application promotion or cloud spending is included.
