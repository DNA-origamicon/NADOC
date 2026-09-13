# PEG relaxation failure diagnosis — 2026-09-12

Job `48c1995afbd5` is marked failed with `PEG safety failed; polymer plateau=False`.
The native engine successfully completed `peg_relax_p10` at step 120,000 (480 ps)
at 13:06 MDT. Together with the 25 ps warm-up, 505 ps of dynamics completed.
The remaining p50/p100 chunks have not run. No NAMD process was running at diagnosis.

## Root cause

`parse_namd_log_frames` ignores ENERGY lines until it sees ETITLE in the same file.
Resumed NAMD output can contain ENERGY lines before the next periodic ETITLE.
`peg_relax_p10.resume1.log` has no ETITLE; resume2 first prints ETITLE at step 40,000.
The validator therefore misses energy records for seven of the thirty saved frame
steps: 12,000, 16,000, 20,000, 24,000, 28,000, 32,000 and 36,000.
Its required energy/coordinate coverage fails, but the generic error obscures this
and prominently reports the unrelated, nonfatal polymer plateau result.

The final resume2 log contains the expected final coordinate/velocity writes,
GPU-resident banner and `End of program`. Logs contain no FATAL, CUDA error,
constraint failure or atoms-moving-too-fast message. The full final coordinate,
velocity and fixed 48 Å cell checkpoint at step 120,000 is present.

## Independent diagnostic check

Copied the package to a temporary directory. Verified that all emitted ETITLE
schemas agree and every ENERGY row has the matching column count. Prepended that
verified header to resumed logs in the copy, preserving file modification times
because current continuation precedence uses them. Re-ran the existing validator.

- All 30 saved frames pass the safety test.
- Maximum sampled wall penetration: **0.3384065 Å** (limit 1 Å).
- Maximum sampled graft displacement: **0.8350351 Å** (limit 1.5 Å).
- Maximum wall/graft energy error: **0.0000573584 kcal/mol** (limit 0.1).
- Energy plateau: false. Polymer plateau: false. Skip: false.

These results diagnose missing parsed evidence, not unstable wall/graft forces.
Failure to plateau should cause the remaining chunks to run; it is not a safety
failure. The evidence supports continuing from the completed p10 checkpoint after
correcting the parser/validator. It does not establish equilibrium or guarantee
future stages will remain stable.

Original native logs, trajectories, configurations and job status were left intact.
No new simulation was launched. Diagnostic output is saved beside the job as
`output/peg_relax_p10.diagnosis.json`.

## Required fix before resuming

1. Parse continuation ENERGY rows using a verified compatible column schema, even
   when ETITLE appears later or only in the earlier log. Preserve restart precedence
   so duplicate step numbers pair with coordinates from the same continuation.
2. Report individual failed safety checks, especially energy-frame coverage, rather
   than the generic `PEG safety failed; polymer plateau=False` message.
3. Regression-test headerless and delayed-header continuations, duplicate restart
   steps and missing/incompatible schemas. Revalidate the untouched saved package.
4. Resume the existing job at p50 from the completed p10 checkpoint. There is no
   evidence here requiring a smaller timestep, new minimization or MC reseeding.

## Fix implemented

The PEG continuation reader now validates and inherits the recorded ETITLE schema,
pairs frames with the correct restart attempt, and uses numeric continuation order.
Failures identify the exact safety check and missing steps; nonconvergence is
reported as a reason to continue. Untouched native p10 evidence now passes all
30 frames. See [implementation and skip proof](namd_peg_skip_validation.md).
