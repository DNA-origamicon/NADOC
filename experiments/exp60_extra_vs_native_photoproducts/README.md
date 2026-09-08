# exp60 — extra versus native interstrand photoproduct opportunity

This experiment runs all-thymidine, interstrand KIMMDY discovery on matched 24hb and
6hbx100 production ensembles. It partitions screened TT pairs into intended extra–extra,
other extra–extra, extra–native, nearby native–native, and far native–native classes.

The primary analysis uses every finite sampled frame without structural gates. The output
decomposes geometric photoproduct opportunity; it does not equate the dimensionless score
with formed CPDs or mechanical stability.

```bash
uv run python experiments/exp60_extra_vs_native_photoproducts/run.py analyse
uv run python experiments/exp60_extra_vs_native_photoproducts/run.py summarize
```
