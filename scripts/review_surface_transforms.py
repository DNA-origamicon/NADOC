"""Render a read-only rigid-frame audit of a PEG .nadoc design; no engine launch."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from backend.api.crud import _geometry_for_design
from backend.core.models import Design
from backend.core.constants import NM_TO_OXDNA
from backend.core.surface_transforms import RigidTransform, surface_frame, transform_surface
from backend.physics.oxdna_interface import write_configuration
from backend.physics.oxdna_surface_geometry import resolved_wall
from backend.physics.oxdna_surface_strands import CaptureSpec, build_capture_strands


def review(path, output):
    design = Design.from_json(path.read_text())
    coating = design.metadata.peg_surface
    with tempfile.TemporaryDirectory(prefix='nadoc_surface_review_') as scratch:
        conf = Path(scratch) / 'conf.dat'
        write_configuration(design, _geometry_for_design(design), conf, oxdna_native_seed=True)
        dna = np.loadtxt(conf, skiprows=3)[:, :3] / NM_TO_OXDNA
    surface = resolved_wall(coating['surface'], dna * NM_TO_OXDNA)
    spec = CaptureSpec.from_payload(coating['surface_strands'])
    build = build_capture_strands(spec, origami_cm_oxdna=(dna*NM_TO_OXDNA).tolist(),
                                  n_particles_origami=len(dna),
                                  n_strands_origami=len(design.strands), surface=surface)
    peg = np.array([[float(v) for v in line.split()[:3]] for line in build.conf_lines]) / NM_TO_OXDNA
    surface.update(peg_positions_nm=peg.tolist(), graft_sites_nm=
                   [(np.asarray(p)/NM_TO_OXDNA).tolist() for _, p in build.trap_anchors])
    angle = .6
    transform = RigidTransform([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
                                [-np.sin(angle), 0, np.cos(angle)]], [5, 3, -2])
    # Second rotation tilts the plane as well as the patch tangents.
    transform = transform.then(RigidTransform([[1, 0, 0], [0, np.cos(angle), -np.sin(angle)],
                                               [0, np.sin(angle), np.cos(angle)]]))
    moved = transform_surface(surface, transform)
    frame = surface_frame(surface)
    center = frame.project(dna.mean(0))
    corners = np.array([center + x*np.asarray(frame.tangent_u) + y*frame.tangent_v
                        for x, y in [(-7,-7), (7,-7), (7,7), (-7,7), (-7,-7)]])
    fig = plt.figure(figsize=(14, 5))
    for i, title in enumerate(['Source', 'Shared rotation + translation', 'Inverse overlay']):
        ax = fig.add_subplot(1, 3, i+1, projection='3d')
        d = dna if i != 1 else transform.points(dna)
        p = peg if i != 1 else np.asarray(moved['peg_positions_nm'])
        c = corners if i != 1 else transform.points(corners)
        ax.scatter(*d.T, color='#187bcd', s=8, label='DNA CM')
        for chain in p.reshape(-1, spec.peg['segments']+1, 3):
            ax.plot(*chain.T, color='#ab47bc', marker='.', linewidth=1)
        ax.plot(*c.T, color='#444444', label='Barrier patch')
        if i == 2:
            restored = transform.inverse().points(moved['peg_positions_nm'])
            ax.scatter(*restored.T, color='#19a974', marker='x', s=12, label='Restored PEG')
        ax.set(title=title, xlabel='x (nm)', ylabel='y (nm)', zlabel='z (nm)')
        ax.set_box_aspect([1, 1, 1])
        ax.legend(fontsize=7)
    fig.suptitle('PEG surface rigid-frame audit — geometry only, no dynamics')
    fig.tight_layout()
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output / 'surface-review.png', dpi=150)
    metrics = {'design': str(path), 'dna_particles': len(dna), 'peg_particles': len(peg),
               'max_inverse_error_nm': float(np.abs(transform.inverse().points(transform.points(peg))-peg).max()),
               'max_plane_distance_delta_nm': float(np.abs(
                   surface_frame(moved).signed_distance(transform.points(dna)) - frame.signed_distance(dna)).max())}
    (output / 'surface-review.json').write_text(json.dumps(metrics, indent=2) + '\n')
    print(json.dumps(metrics))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    review(args.design, args.output)
