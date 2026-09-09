"""Build a separate continuation package, preserving the failed job's evidence."""
from pathlib import Path
import json
from backend.core.namd_graphene import graphene_pressure_conf
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=ROOT/'workspace/md_jobs/7aa73d7afe93/package/small_plate_namd_solvated'
TARGET=HERE/'recovery_package'
TARGET.mkdir(exist_ok=True)
(TARGET/'output').mkdir(exist_ok=True)
for item in SOURCE.iterdir():
    dst=TARGET/item.name
    if item.name=='output':continue
    if item.suffix=='.conf':
        if dst.exists():raise RuntimeError(f'Preserve existing candidate first: {dst}')
        dst.write_text(graphene_pressure_conf(item.read_text(),enabled=True))
    elif item.name in {'manifest.json','nadoc_md_run.json'}:
        manifest=json.loads(item.read_text())
        manifest['package_dir']=str(TARGET)
        manifest['diagnostic_recovery']={'source_job':'7aa73d7afe93','source_slurm_job':'32089399','changed_directives':{'langevinPistonPeriod':10000,'langevinPistonDecay':5000},'status':'isolated candidate; not submitted to Alpine'}
        manifest.setdefault('relax_protocol_settings',{}).update(ladder_piston_period_decay_fs=[10000.,5000.],production_piston_period_decay_fs=[10000.,5000.])
        if not dst.exists():dst.write_text(json.dumps(manifest,indent=2)+'\n')
    elif not dst.exists():dst.symlink_to(item,target_is_directory=item.is_dir())
previous='small_plate_02_300K_NPT_ENM_k0p1_p100'
for ext in ('coor','vel','xsc'):
    dst=TARGET/'output'/f'{previous}.{ext}'
    if not dst.exists():dst.symlink_to(SOURCE/'output'/dst.name)
print(TARGET)
