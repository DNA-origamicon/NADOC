# Experiment 43 — 7-bp crossover transition tokens

This experiment uses a three-helix honeycomb neighborhood because consecutive 7-bp
crossover opportunities face different neighbors. It is staged so preparation
cannot accidentally start NAMD.

```bash
# Cheap: build and validate the three NADOC designs only
python experiments/exp43_7bp_crossover_transition/run.py build

# Expensive CPU/disk preparation: solvate and emit full NAMD ladders; still no NAMD
python experiments/exp43_7bp_crossover_transition/run.py prepare

# Later, start exactly one condition (explicit arm is mandatory)
python experiments/exp43_7bp_crossover_transition/run.py launch \
  --condition no_crossover --confirm-start

# Suitable for cron/systemd; exit 2 means a fatal experiment-level trigger fired
python experiments/exp43_7bp_crossover_transition/run.py monitor

# After completion: validate and export restrained/unrestrained datasets separately
python experiments/exp43_7bp_crossover_transition/run.py process

# Run/watch all conditions sequentially; safe to restart after interruption
python experiments/exp43_7bp_crossover_transition/run_all.py
```

`prepare` creates managed jobs in the normal workspace and records their IDs in
`runs/registry.json`. It never invokes the runner. The standard runner supplies
checkpointing, bounded recovery for known transient failures, NAMD error
classification, performance logs, and per-segment health checks. `monitor` adds a
stale-job trigger and output-integrity checks.

The full standard relaxation ladder is intentional. Frames produced while restraints
are being released describe useful nonequilibrium relaxation paths, while the
unrestrained segments are only *equilibrium candidates*. Burn-in must be selected from
observable stationarity and autocorrelation diagnostics after the run; the protocol
boundary alone does not prove equilibration.
