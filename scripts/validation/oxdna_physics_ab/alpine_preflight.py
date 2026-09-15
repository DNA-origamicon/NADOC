from pathlib import Path
import os, subprocess, json, shutil

ROOT = Path(__file__).resolve().parent
binary = "/projects/jojo6687/nadoc_jobs/strep_bussi_fixed_20260913/build_cpu_portable/bin/oxDNA"
results = []
for test in ["weak_CPU", "mask_CPU_john_32_0"]:
    outputs = {}
    for variant in ["native", "baseline", "current_k", "rigid_mask"]:
        d = ROOT / "preflight_runs" / test / variant
        d.mkdir(parents=True, exist_ok=True)
        for p in (ROOT / "preflight_inputs" / test).iterdir():
            if p.name in ["conf.dat", "topology.top", "anm.par", "forces.txt", "input"]:
                shutil.copy2(p, d / p.name)
        env = dict(os.environ, OMP_NUM_THREADS="1")
        selected_binary = (
            binary
            if variant == "native"
            else str(ROOT / "engines" / variant / "bin/oxDNA")
        )
        with (d / "run.log").open("w") as log:
            subprocess.run(
                [selected_binary, "input"],
                cwd=d,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=60,
            )
        a = [
            [float(v) for v in line.split()]
            for line in (d / "last_conf.dat").read_text().splitlines()[3:]
            if line.strip()
        ]
        outputs[variant] = a
        k = sum(v * v for row in a for v in row[9:12]) / 2
        results.append(
            dict(
                test=test,
                variant=variant,
                K=k,
                point_L2=sum(v * v for row in a[:32] for v in row[12:])
                if test.startswith("mask")
                else None,
            )
        )
    assert outputs["baseline"] == outputs["native"], (
        "Recompiled baseline changes native output"
    )
    if test == "weak_CPU":
        k = lambda a: sum(v * v for row in a for v in row[9:12]) / 2
        assert 1.999 < k(outputs["current_k"]) / k(outputs["baseline"]) < 2.001
    else:
        assert all(
            a[:3] + a[9:12] == b[:3] + b[9:12]
            for a, b in zip(outputs["baseline"], outputs["rigid_mask"])
        )
        assert all(v == 0 for row in outputs["rigid_mask"][:32] for v in row[12:])
(ROOT / "preflight.json").write_text(json.dumps(results, indent=2))
print("PASS native baseline identity, current-K override, point-mask override")
