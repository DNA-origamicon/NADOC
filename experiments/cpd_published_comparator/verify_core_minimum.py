"""Independent numerical stationarity and step-halved curvature of the joint core."""

import argparse
import json
from pathlib import Path
import sys
import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import write, source


def main(root):
    assert not (root / "core_minimum.json").exists()
    s = mm.XmlSerializer.deserialize((root / "core/candidate.xml").read_text())
    x = np.loadtxt(root / "core/minimum_A.txt")
    n = x.size
    it = mm.VerletIntegrator(0.001)
    ctx = mm.Context(s, it, mm.Platform.getPlatformByName("Reference"))

    def gradient(pos):
        ctx.setPositions(pos * u.angstrom)
        return -np.asarray(
            ctx.getState(getForces=True)
            .getForces(asNumpy=True)
            .value_in_unit(u.kilocalorie_per_mole / u.angstrom)
        ).ravel()

    max_force = float(max(abs(gradient(x))))
    c = x - x.mean(axis=0)
    rigid = np.column_stack(
        [np.tile(v, (len(x), 1)).ravel() for v in np.eye(3)]
        + [np.cross(np.tile(v, (len(x), 1)), c).ravel() for v in np.eye(3)]
    )
    basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
    eigen = []
    for step in (1e-4, 5e-5):
        h = np.empty((n, n))
        for i in range(n):
            a, b = x.ravel().copy(), x.ravel().copy()
            a[i] += step
            b[i] -= step
            h[:, i] = (gradient(a.reshape(-1, 3)) - gradient(b.reshape(-1, 3))) / (
                2 * step
            )
        eigen.append(float(np.linalg.eigvalsh(basis.T @ ((h + h.T) / 2) @ basis).min()))
    report = dict(
        max_force=max_force,
        smallest_internal_curvatures=eigen,
        passed=max_force < 1e-4 and min(eigen) > 0,
        sources=[
            source(root / "core/candidate.xml"),
            source(root / "core/minimum_A.txt"),
            source(Path(__file__)),
        ],
    )
    write(root / "core_minimum.json", report)
    print(json.dumps(report, indent=2))
    assert report["passed"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    main(p.parse_args().root.resolve())
