# Joint PEG oxDNA/NAMD development pilot — H200 budget

2026-09-10. USD; estimate only. No resources rented or jobs authorized/launched by
this budget. Machine-readable detail: [CSV](PILOT_BUDGET.csv), [JSON](PILOT_BUDGET.json).

## Scope and deliverables

Develop and compare neutral PEG brush models at N36/N45/N76, qualify the simulation
packages, measure sampling/performance, and obtain initial brush statistics and
exploratory coarse-grained compression curves. The atomistic campaign uses the
existing 27-case plan; the oxDNA brush/compression matrix is a proposed development
allocation, not an implemented or validated surface protocol.

The pilot should deliver parameter provenance, engine energy/force checks, chain
and brush observables with uncertainty, cross-model comparisons with matched
chemistry/conditions, a ranked interface-parameter backlog, and measured resource
requirements for production. It can finish with an unresolved scientific result.
Coarse-grained compression here uses an ideal mechanical probe, not a validated
DNA tile or electrical actuator.

Existing local bulk oxDNA allocations incur **$0 additional cloud rental in this
estimate**. This does not imply free electricity or a completed validation. Their
scope, caps and scheduler remain unchanged. New GPU bulk checks do not by themselves
resolve the known CPU EOS sampling issue; sampler diagnosis has a CPU allowance.

## Itemized baseline

| Item | H200 GPU-hours | Cost at $4.59/hour |
|---|---:|---:|
| oxDNA H200 qualification/timing | 12 | $55.08 |
| oxDNA targeted bulk recheck reserve | 24 | $110.16 |
| oxDNA brush pilot: 27 runs × 8 hours | 216 | $991.44 |
| oxDNA compression: 45 windows × 8 hours | 360 | $1,652.40 |
| NAMD asset smoke/timing | 12 | $55.08 |
| NAMD isolated-chain references: 9 runs × 10 hours | 90 | $413.10 |
| NAMD brush pilot: 27 × 22.2 ns at 50 ns/day/GPU | 287.712 | $1,320.60 |
| NAMD interface diagnostic pool: 6 jobs × 8 hours | 48 | $220.32 |
| **GPU subtotal** | **1,049.712** | **$4,818.18** |
| Additional GPU sampling/overhead reserve, 30% | 314.914 equivalent | $1,445.45 |
| CPU QM/fitting: 512 × 32-vCPU/128-GB node-hours at $0.773 | — | $395.78 |
| CPU preparation/sampler/analysis: 160 × 16-vCPU/32-GB node-hours at $0.194 | — | $31.04 |
| Storage/backup allowance | — | $150.00 |
| **Total** | — | **$6,840.45** |

H200 price: [RunPod Pods](https://www.runpod.io/pricing). CPU prices:
[E2E C3 instance table](https://www.e2enetworks.com/pricing). CPU jobs use CPU
instances, not idle H200 reservations. Prices exclude applicable taxes; availability
and exact regional configuration are unconfirmed. Storage is a planning allowance,
not a quoted package. Personnel, experimental consumables and facilities are excluded.

## What is estimated versus allocated

Only the NAMD brush row is derived from a prescribed trajectory duration. Its
assumed H200 speed is unmeasured. Every other compute row is a bounded development
allowance. For example, the QM pool could support 64 eight-hour node allocations;
this is not a prediction that 64 chemistry calculations will finish or suffice.
Au electronic structure, actual linker identity and held-out validation may require
additional work. Do not manufacture a force field merely to fit this budget.

The NAMD matrix comprises three lengths, three requested graft densities and three
replicas. Each case receives 2 ns equilibration, 0.2 ns timing and 20 ns pilot data.
Total = 599.4 ns; GPU-hours = 599.4 / rate_ns_per_day × 24. The oxDNA compression
allowance comprises three lengths, one selected density each, five heights and three
replicas. These short screening curves do not establish precision actuation or
sampling at all relevant densities.

If only NAMD brush speed changes, retaining all other development allowances:

| NAMD ns/day/GPU | Total including reserve/CPU/storage |
|---:|---:|
| 100 | $5,982 |
| 50 | $6,840 |
| 25 | $8,557 |

This sensitivity range is not a confidence interval for all project costs.
An initial **$10,000 cloud budget ceiling** provides headroom beyond the midpoint;
revise after hardware qualification, parameter selection and mixing measurements.

## Optional extension and rental strategy

If pilots justify extending all 27 NAMD brush cases by another 80 ns, the additional
2,160 ns costs about **$6,187**, including 30% GPU allowance, at 50 ns/day/GPU.
Pilot plus that extension: approximately **$13,027**; this still does not guarantee
convergence or include full atomistic force curves.

At 30-day on-demand-equivalent rates, one H200 costs $3,304.80 on RunPod. E2E lists
an H200 monthly price of $2,837.51. Four E2E H200s for a month therefore cost
$11,350.04 plus roughly $577 CPU/storage = **$11,927**, with 2,880 GPU-hours of
capacity. This is an alternative billing plan, not an amount to add to burst costs.
It provides more hours but less concurrency than the fastest burst strategy.
Hyperstack's reserved starting rate requires a term/capacity quote; it is not used
as an unconditional one-month price here.

For time-prioritized execution, burst to 27 GPUs for brush cases and up to 45 for
coarse compression windows after each preceding qualification gate. At the midpoint,
the atomistic 22.2 ns stage is about 10.7 hours per case before overhead. The eight-hour
coarse windows form an eight-hour allocation wave, not an eight-hour convergence
promise. Aggregate runtime is about 1,365 GPU-hours with reserve; four GPUs would
need roughly 14.2 fully occupied days, whereas bursts remove most queueing.
Model development, equilibration dependencies and result review determine calendar
completion; no fixed delivery date follows from the GPU-hour budget.

This pilot excludes a full DNA-tile PMF, voltage sweeps, constant-potential electrode
implementation, reactive Au-S/faradaic chemistry and physical experiments. Those
are subsequent scope decisions, not hidden inside the interface diagnostic pool.
