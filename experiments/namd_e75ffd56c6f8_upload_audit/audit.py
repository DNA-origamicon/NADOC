"""Read-only audit of the submitted small_plate copy and its SFTP receipts."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOB_ID = 'e75ffd56c6f8'
JOB_DIR = ROOT / 'workspace/md_jobs' / JOB_ID
PACKAGE = JOB_DIR / 'package/small_plate_namd_solvated'


def audit():
    job = json.loads((JOB_DIR / 'job.json').read_text())
    manifest = json.loads((PACKAGE / 'manifest.json').read_text())
    if job['status'] == 'preparing':
        raise RuntimeError('Preparation still in progress; package not yet final')
    rows = []
    for conf in sorted(PACKAGE.glob('*.conf')):
        data = conf.read_bytes()
        text = data.decode()
        def value(key):
            matches = re.findall(r'^\s*' + re.escape(key) + r'\s+([^\s#]+)', text, re.M | re.I)
            return matches[-1] if matches else None
        npt = value('langevinPiston') in ('on', 'yes', 'true', '1')
        row = dict(file=conf.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                   npt=npt, piston_period_fs=value('langevinPistonPeriod'),
                   piston_decay_fs=value('langevinPistonDecay'), timestep_fs=value('timestep'),
                   gpu_resident=value('GPUresident'), restraints=value('conskfile'),
                   coordinates=value('binCoordinates'), cell=value('extendedSystem'))
        if npt:
            assert float(row['piston_period_fs']) >= 10000, row
            assert float(row['piston_decay_fs']) >= 5000, row
        rows.append(row)
    assert len(manifest['segments']) == 21
    for segment in manifest['segments']:
        assert any(row['file'] == segment['name'] + '.conf' for row in rows), segment
    critical = next(r for r in rows if r['file'] == 'small_plate_03_300K_NPT_ENM_k0p01_p10.conf')
    assert critical['coordinates'] == 'output/small_plate_02_300K_NPT_ENM_k0p1_p100.coor'
    assert float(critical['timestep_fs']) == 4
    assert manifest['graphene_nanopore']['nonbonded_model'] == 'restrained_wall_no_self_lj_v1'
    assert manifest['relax_protocol_settings']['ladder_piston_period_decay_fs'] == [10000, 5000]
    receipts = {}
    errors = []
    logdir = ROOT / 'workspace/logs'
    for logfile in sorted(logdir.glob('alpine_operations.jsonl*'), key=lambda p: p.stat().st_mtime):
        for line in logfile.read_text().splitlines():
            if JOB_ID not in line:
                continue
            entry = json.loads(line)
            if entry['event'] == 'upload_finish':
                if entry.get('outcome') == 'success':
                    receipts[entry['remote_path']] = entry
                else:
                    errors.append(entry)
    uploaded_configs = []
    for row in rows:
        receipt = next((e for remote, e in receipts.items() if remote.endswith('/' + row['file'])), None)
        uploaded_configs.append(dict(file=row['file'], transferred=bool(receipt),
                                     byte_count_matches=bool(receipt and receipt['bytes'] == row['bytes']),
                                     receipt=receipt))
    inventory = json.loads((Path(__file__).parent / 'package_inventory.json').read_text())
    package_transfers = []
    for item in inventory:
        receipt = next((e for remote, e in receipts.items() if remote.endswith('/' + item['file'])), None)
        package_transfers.append(dict(file=item['file'],
                                      byte_count_matches=bool(receipt and receipt['bytes'] == item['bytes'])))
    result = dict(audited_at=datetime.now(timezone.utc).isoformat(), job_id=JOB_ID,
                  status=job['status'], slurm_job_id=job.get('slurm_job_id'),
                  remote_scratch_dir=job.get('remote_scratch_dir'),
                  config_count=len(rows), npt_configs=sum(r['npt'] for r in rows),
                  configs=rows, uploaded_configs=uploaded_configs,
                  package_transfers=package_transfers,
                  package_files_verified=sum(r['byte_count_matches'] for r in package_transfers),
                  successful_uploads=len(receipts), upload_errors=errors,
                  verification_limit='SFTP completion receipts and byte counts; no independent remote hash readback.')
    (Path(__file__).parent / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['configs','uploaded_configs','upload_errors','package_transfers']}, indent=2))
    print('Uploaded configs:', sum(r['byte_count_matches'] for r in uploaded_configs), '/', len(rows))
    return result


if __name__ == '__main__':
    audit()
