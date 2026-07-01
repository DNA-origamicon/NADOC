#!/usr/bin/env python3
"""Latest oxDNA frame of a job → PDB for a VMD structure-integrity check (PBC-unwrapped).

Unlike the raw `oxdna_conf_to_pdb.py`, this uses NADOC's `read_configuration_unwrapped`, which
rebuilds whole molecules across the periodic box and Kabsch-aligns to the job's initial conf — so
a structure that merely straddles the box edge shows as the intact bundle it is, not a scattered
mess.  One bead per nucleotide at its backbone position; chained by helix.

Usage (run with the NADOC venv so backend imports resolve):
    export PATH="$HOME/.local/bin:$PATH"
    uv run python scripts/oxdna_job_to_pdb.py <job_dir> <out.pdb>
    vmd <out.pdb>      # Representation: VDW or Points
"""
import glob
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.core.oxdna_runner import _load_snapshot_design  # noqa: E402
from backend.physics.oxdna_interface import read_configuration_unwrapped  # noqa: E402

_CHAINS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def main(job_dir: str, out_pdb: str) -> None:
    jd = pathlib.Path(job_dir)
    design = _load_snapshot_design(jd)
    ref = jd / "conf.dat"
    confs = sorted(glob.glob(str(jd / "*" / "last_conf.dat")),
                   key=lambda p: pathlib.Path(p).stat().st_mtime)
    if not confs:
        sys.exit(f"no last_conf.dat under {jd}")
    conf = confs[-1]
    print(f"job: {jd.name}\nlatest frame: {pathlib.Path(conf).parent.name}/last_conf.dat", flush=True)
    pos = read_configuration_unwrapped(conf, design, ref)

    helix_ids = sorted({k[0] for k in pos})
    chain_of = {h: _CHAINS[i % len(_CHAINS)] for i, h in enumerate(helix_ids)}
    xs = []
    with open(out_pdb, "w") as out:
        for i, (key, rec) in enumerate(pos.items()):
            x, y, z = (float(v) * 10.0 for v in rec["backbone_position"])  # nm → Å
            xs.append((x, y, z))
            out.write(
                f"ATOM  {(i+1)%100000:>5} {' CA ':<4} {'DNA':>3} {chain_of[key[0]]}"
                f"{(int(key[1])%10000):>4}    {x:>8.3f}{y:>8.3f}{z:>8.3f}"
                f"{1.0:>6.2f}{0.0:>6.2f}          {'C':>2}\n")
        out.write("END\n")

    def rng(a):
        return max(a) - min(a)
    ex = [rng([p[k] for p in xs]) for k in range(3)]
    print(f"wrote {out_pdb}: {len(xs)} nucleotides", flush=True)
    print(f"extent (Å): {ex[0]:.0f} x {ex[1]:.0f} x {ex[2]:.0f}  "
          f"(intact straight 3x6x400 ≈ 1360 x ~150 x ~150; exploded = many thousands)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(1)
    main(sys.argv[1], sys.argv[2])
