"""One bounded 50 ps NVE confirmation for isomers failing the short drift panel.

Keep both starts and both timesteps; retain the original failed comparisons.
No threshold changes, parameter fitting, geometry changes, or repeated retries.
"""
import argparse
import copy
import json
import re
from pathlib import Path

from scripts import validate_cpd_hmr as panel
from backend.core.cpd_forcefield import packaged_photoproduct_manifest
from backend.core.photoproduct_psf_audit import parse_psf_atoms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pilot', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pilot = args.pilot.resolve()
    source_verdict = json.loads((pilot/'verdict.json').read_text())
    failed = {p['job'] for p in source_verdict['pairs'] if not p['passed']}
    records = json.loads((pilot/'results.json').read_text())
    assert len(records) == 16
    # A longer slope estimate cannot excuse a constraint or chemistry failure.
    assert all(r['npt']['passed'] and r['nve']['normal_exit'] and r['nve']['finite']
               and r['nve']['geometry']['passed'] for r in records)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((pilot/'protocol.json').read_text())
    protocol.update(confirmation_worker=panel.pin(__file__), pilot_protocol=panel.pin(pilot/'protocol.json'),
                    pilot_verdict=source_verdict, nve_ps_by_job={jid:50 for jid in sorted(failed)},
                    confirmation_rule='One 50 ps NVE panel for both starts and both timesteps of each short-panel-failing isomer. Same limits. No further extension.')
    panel.save(root/'protocol.json', protocol)
    panel.POLICY = dict(panel.POLICY, nve_ps=50)
    results = []
    for original in records:
        r = copy.deepcopy(original)
        jid, start, dt = r['job'], r['start'], r['dt_fs']
        name = f'{jid}_{start}_{dt}fs'
        source = pilot/name
        arm = root/name
        if jid not in failed:
            arm.symlink_to(source, target_is_directory=True)
        else:
            arm.mkdir()
            for p in source.iterdir():
                if not p.name.startswith('nve'):
                    (arm/p.name).symlink_to(p.resolve(), target_is_directory=p.is_dir())
            inputs = json.loads((arm/'inputs.json').read_text())
            manifest_path = next(Path(i['path']) for i in inputs['inputs'] if i['path'].endswith('photoproduct_forcefield_manifest.json'))
            manifest = packaged_photoproduct_manifest(manifest_path.parent)
            psf = Path(inputs['psf']['path'])
            natoms = len(parse_psf_atoms(psf.read_text()))
            conf = re.sub(r'^run\s+.*$', f'run {round(50000/dt)}', (source/'nve.conf').read_text(), flags=re.M)
            panel.save(arm/'confirmation_inputs.json', dict(
                operation='Extend NVE diagnostic duration from 10 to 50 ps from the identical NPT endpoint; no fitting or mass/coordinate changes',
                source_npt=[panel.pin(source/f'npt.{ext}') for ext in ['coor','vel','xsc']],
                source_conf=panel.pin(source/'nve.conf'), source_result=panel.pin(source/'nve.json'),
                worker=panel.pin(__file__)))
            r['short_window_nve'] = r['nve']
            r['nve'] = panel.run_stage(arm, conf, 'nve', dt, natoms, psf, manifest, protocol['engine']['path'])
            r['passed'] = r['npt']['passed'] and r['nve']['passed']
            r['nve_duration_ps'] = 50
        results.append(r)
        panel.save(root/'results.json', results)
    pairs=[]
    for jid in panel.JOBS:
        for start in panel.POLICY['starts']:
            arms={r['dt_fs']:r for r in results if r['job']==jid and r['start']==start}
            excess=abs(arms[4]['nve']['drift_kcal_mol_ns_atom'])-abs(arms[2]['nve']['drift_kcal_mol_ns_atom'])
            pairs.append(dict(job=jid,start=start,drift_excess=excess,
                              nve_ps=protocol['nve_ps_by_job'].get(jid,10),
                              passed=all(r['passed'] for r in arms.values()) and excess<=panel.POLICY['maximum_paired_abs_drift_excess']))
    panel.save(root/'verdict.json',dict(passed=all(p['passed'] for p in pairs),pairs=pairs))


if __name__=='__main__':
    main()
