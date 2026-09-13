"""PEG wall safety and conservative chunk convergence; no DNA surrogate metrics."""
import json
from pathlib import Path

import numpy as np

from backend.core.md_cutoff import CutoffParams
from backend.core.namd_peg_evidence import segment_evidence
from backend.core.md_health import HealthCheckResult
from backend.core.namd_peg_wall import RepulsiveSlit
from experiments.peg_namd.structure import read_pair


def series_report(values, drift_limit, fluct_limit):
    """Require two disjoint ten-frame windows to pass; expose measured margins."""
    v = np.asarray(values, float)
    valid = v.ndim == 1 and len(v) >= 20 and np.isfinite(v).all()
    windows = []
    if valid:
        for w in (v[-20:-10], v[-10:]):
            scale = abs(float(w.mean())) or 1.
            drift = abs(float(w[:5].mean()-w[5:].mean()))/scale
            fluct = float(w.std())/scale
            windows.append(dict(drift=drift, fluctuation=fluct,
                                passed=drift < drift_limit and fluct < fluct_limit))
        # A jump between individually flat windows is also still relaxation.
        scale = abs(float(v[-20:].mean())) or 1.
        between = abs(float(v[-20:-10].mean()-v[-10:].mean()))/scale
    else:
        between = None
    return dict(passed=bool(valid and all(w['passed'] for w in windows) and between < drift_limit),
                samples=int(v.size), required_samples=20, drift_limit=drift_limit,
                fluctuation_limit=fluct_limit, between_window_drift=between, windows=windows)


def polymer_plateau(energy, rg, height):
    params = CutoffParams()
    reports = {'potential': series_report([r.get('POTENTIAL', float('nan')) for r in energy],
                                          params.eps_pot_drift, params.eps_pot_fluct)}
    if any('VOLUME' in r for r in energy):
        reports['volume'] = series_report([r.get('VOLUME', float('nan')) for r in energy],
                                          params.eps_vol_drift, params.eps_vol_fluct)
    arrays = [np.asarray(rg, float), np.asarray(height, float)]
    shape_ok = (all(a.ndim == 2 and len(a) == len(energy) and a.shape[1] > 0
                    and np.isfinite(a).all() and (a > 0).all() for a in arrays)
                and arrays[0].shape == arrays[1].shape)
    structural = []
    if shape_ok:
        for label, a in zip(('rg', 'height'), arrays):
            for i in range(a.shape[1]):
                report = series_report(a[:, i], .05, .1)
                reports[f'{label}_chain_{i+1}'] = report
                structural.append(report['passed'])
    e = all(r['passed'] for name, r in reports.items() if name in ('potential', 'volume'))
    p = bool(shape_ok and structural and all(structural))
    return bool(e and p), dict(energy_plateaued=e, polymer_plateaued=p,
                               convergence=reports, structural_samples_valid=bool(shape_ok))


def assess_segment(package, segment):
    package = Path(package)
    manifest = json.loads((package/'manifest.json').read_text())
    spec = next(s for s in manifest['segments'] if s['name'] == segment)
    pair = read_pair(package/'system.psf', package/'grafts.pdb')
    slit = RepulsiveSlit(**manifest['slit']); box = np.array(slit.box_nm)*10
    anchors = manifest['audit']['anchor_indices_0']
    chains = [[i for i in manifest['audit']['peg_indices_0'] if pair['atoms'][i][1] == pair['atoms'][anchor][1]] for anchor in anchors]
    samples, native, logs = segment_evidence(package, segment, manifest['n_atoms'])
    if not samples:
        raise ValueError('trajectory_coverage: no PEG trajectory frames')
    rg, height, max_wall, max_anchor, max_energy_error = [], [], 0., 0., 0.
    compared = 0
    missing = []
    for step, (xyz, row) in sorted(samples.items()):
        if not np.isfinite(xyz).all():
            raise ValueError('nonfinite PEG trajectory')
        wrapped = np.mod(xyz/10, slit.box_nm)
        distances = np.minimum(*(f.signed_distance(wrapped)*10 for f in slit.frames))
        max_wall = max(max_wall, float(max(0, -distances.min())))
        delta = xyz[anchors]-pair['xyz'][anchors]; delta -= box*np.rint(delta/box)
        sq = np.sum(delta**2, axis=1)
        max_anchor = max(max_anchor, float(np.sqrt(sq.max())))
        if row is not None and {'BOUNDARY', 'MISC'} <= row.keys():
            compared += 1
            max_energy_error = max(max_energy_error, abs(row['MISC']-slit.energy_forces(xyz)[0]),
                                   abs(row['BOUNDARY']-manifest['graft_k_kcal_mol_A2']*sq.sum()))
        else:
            missing.append(step)
        # wrapAll is off for PEG: preserve contiguous chains, including long coils.
        rg.append([float(np.sqrt(np.mean(np.sum((xyz[c]-xyz[c].mean(axis=0))**2, axis=1)))) for c in chains])
        height.append([float(xyz[c, slit.axis].max()-slit.inset_nm*10) for c in chains])
    rows = [r if r is not None else {} for _, r in (samples[s] for s in sorted(samples))]
    plateau, diag = polymer_plateau(rows, rg, height)
    expected = list(range(spec['dcd_freq'], spec['steps']+1, spec['dcd_freq']))
    checks = dict(
        trajectory_coverage=sorted(samples) == expected,
        energy_frame_coverage=not missing,
        force_energy_agreement=max_energy_error < .1,
        wall_penetration=max_wall < 1.,
        graft_displacement=max_anchor < 1.5,
        native_completion=f"WRITING COORDINATES TO OUTPUT FILE AT STEP {spec['steps']}\n" in native and 'End of program' in native,
        gpu_resident='Running with GPU-resident mode' in native,
        no_engine_errors=not any(t.lower() in native.lower() for t in ('FATAL ERROR', 'CUDA error', 'Constraint failure', 'Atoms moving too fast')),
    )
    checks = {k: bool(v) for k, v in checks.items()}
    failed = [k for k, passed in checks.items() if not passed]
    safe = not failed
    result = dict(checks=checks, failed_checks=failed, expected_samples=len(expected),
                  energy_comparison_frames=compared, missing_energy_steps=missing,
                  evidence_logs=logs, missing_trajectory_steps=sorted(set(expected)-set(samples)),
                  safe=bool(safe), skip=bool(safe and plateau), **diag,
                  samples=len(samples), max_wall_penetration_A=max_wall,
                  max_anchor_displacement_A=max_anchor, max_force_energy_error_kcal_mol=float(max_energy_error),
                  chain_rg_A=rg, chain_height_A=height, dna_metrics='not_applicable',
                  limitation='Sampled operational cutoff; not a thermodynamic equilibrium certificate.')
    (package/'output'/f'{segment}.peg-health.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def health_result(package, segment):
    try:
        r = assess_segment(package, segment)
        return HealthCheckResult(passed=r['safe'], blocking=not r['safe'],
                                 reason=validation_message(r))
    except (ValueError, OSError, KeyError) as exc:
        report = dict(safe=False, skip=False, failed_checks=['evidence_error'], error=str(exc))
        output = Path(package)/'output'/f'{segment}.peg-health.json'
        try:
            output.write_text(json.dumps(report, indent=2))
        except OSError:
            pass
        return HealthCheckResult(passed=False, blocking=True, reason=f'PEG validation unavailable: {exc}')


def validation_message(result):
    if result['safe']:
        return 'PEG safety passed; ' + ('skip eligible (energy and all chains plateaued).' if result['skip'] else 'continue relaxation: convergence not established; this is not a safety failure.')
    details = ', '.join(result['failed_checks'])
    if result['missing_energy_steps']:
        details += f" (missing energy at steps {result['missing_energy_steps']}; matched {result['energy_comparison_frames']}/{result['samples']} frames)"
    return f"PEG validation failed: {details}. Wall max={result['max_wall_penetration_A']:.4g} Å (limit 1); graft max={result['max_anchor_displacement_A']:.4g} Å (limit 1.5); force-energy error={result['max_force_energy_error_kcal_mol']:.4g} kcal/mol (limit 0.1)."


def skip_decision(package, segment, enabled, has_remaining):
    """Durable distinction between eligible metrics and actually applying a skip."""
    package = Path(package)
    result = assess_segment(package, segment)
    missing = [ext for ext in ('coor', 'vel', 'xsc')
               if not (package/'output'/f'{segment}.{ext}').is_file()
               or (package/'output'/f'{segment}.{ext}').stat().st_size == 0]
    blockers = []
    if not result['safe']: blockers.append('safety_not_proven')
    if not result['energy_plateaued']: blockers.append('energy_not_plateaued')
    if not result['polymer_plateaued']: blockers.append('polymer_not_plateaued')
    if not enabled: blockers.append('skip_disabled')
    if not has_remaining: blockers.append('no_remaining_chunks')
    if missing: blockers.append('missing_checkpoint:' + ','.join(missing))
    result.update(skip=not blockers, skip_blockers=blockers, segment=segment,
                  skip_enabled=bool(enabled), has_remaining_chunks=bool(has_remaining))
    (package/'output'/f'{segment}.peg-skip.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
