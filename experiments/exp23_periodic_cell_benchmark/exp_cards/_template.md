---
id: HXXX
title: One-line description of what is being tested
status: pending          # pending | running | complete | superseded
date_opened: YYYY-MM-DD
literature:
  - "Author et al. (Year) Journal Vol:Page — one-line relevance"
parameter_change:
  key: param_name
  from: old_value
  to: new_value
baseline_run: ramp_v2_03     # restart file stem the test branches from
test_duration_ns: 0.5        # how long to run the hypothesis test
---

## Hypothesis

State the specific, falsifiable claim. E.g.: "Changing rigidBonds from `water` to `all`
will raise the C1'–C1' pairing fraction from 47.8% to > 90% after 500 ps of unrestrained
NVT at 310 K."

## Mechanism

Explain the physical or numerical reason this parameter matters. Cite literature.

## Method

Exact NAMD parameters changed relative to baseline. Restart source. Number of steps.
How the result will be measured (metrics_extract.py fields, base_pairing.py output).

## Expected Outcome

What result confirms the hypothesis? What result rejects it? Include numeric thresholds.

---

## Result

*(Fill after run. Paste key lines from metrics JSON + pairing fraction.)*

## Conclusion

*(Adopt / Reject / Needs more data — and why. One paragraph.)*
