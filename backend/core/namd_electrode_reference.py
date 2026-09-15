"""Separate bulk NPT electrolyte reference; never barostat an electrode cell."""
import json
import re
import shutil
import subprocess
from pathlib import Path
import numpy as np
from backend.core import namd_solvate as s
from backend.core.models import Design
from backend.core.namd_package import complete_psf


def prepare_reference(folder, *, salt_mM, mg_mM, temperature_K, seed):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    dims=(5.,5.,5.)
    result=subprocess.run([s._find_gmx(),'solvate','-cs','spc216.gro','-box',*map(str,dims),'-o','water.gro'],cwd=folder,capture_output=True,text=True,timeout=120)
    (folder/'solvate.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise ValueError('Bulk reference solvation failed; see bulk_reference/solvate.log')
    water,box=s._parse_gro((folder/'water.gro').read_text())
    ions=s.ion_counts(len(water),0,nacl_mM=salt_mM,mgcl2_mM=mg_mM,box_nm=box,mg_hexahydrate=True)
    water,na,mg,cl,mgh=s._place_ions_mixed(water,*ions.as_tuple(),seed=seed,mg_hexahydrate=True)
    psf=s._extend_psf(complete_psf(Design()),water,na,cl,mg_pos=mg,mgh_clusters=mgh)
    pdb=s._build_solvated_pdb('END\n',water,na,cl,box,0,mg_pos=mg,mgh_clusters=mgh)
    (folder/'bulk.psf').write_text(psf);(folder/'bulk.pdb').write_text(pdb)
    extra=s._mgh_extrabonds(0,len(water),len(na),len(mg),len(mgh))
    if extra:(folder/'mgh_extrabonds.txt').write_text(extra)
    (folder/'forcefield').mkdir();(folder/'output').mkdir()
    for name in s._FF_FILES:shutil.copy2(s._FF_DIR/name,folder/'forcefield'/name)
    meta=dict(temperature_K=temperature_K,salt_mM=salt_mM,mg_mM=mg_mM,water_oxygens=len(water)+6*len(mgh),seed=seed)
    (folder/'reference.json').write_text(json.dumps(meta,indent=2))
    write_reference_configs(folder)



def assess_reference(folder):
    folder=Path(folder)
    rows=[]
    for line in (folder/'output'/'bulk.xst').read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            v=list(map(float,line.split()))
            if v[0]>=137500:rows.append(abs(np.linalg.det(np.array(v[1:10]).reshape(3,3)))/1000)
    a=np.asarray(rows)
    if len(a)<100 or not np.isfinite(a).all() or np.any(a<=0):raise ValueError('Bulk reference lacks sufficient finite NPT volume samples')
    drift=abs(a[:len(a)//2].mean()-a[len(a)//2:].mean())/a.mean()
    if drift>.01 or a.std()/a.mean()>.02:raise ValueError('Bulk NPT density has not stabilized; extend reference equilibration')
    meta=json.loads((folder/'reference.json').read_text())
    return {**meta,'volume_nm3':float(a.mean()),'water_number_density_nm3':float(meta['water_oxygens']/a.mean()),'relative_volume_drift':float(drift),'samples':len(a),'passed':True}


async def ensure_reference(package, manifest, execute):
    import asyncio
    existing=manifest.get('electrode_validation',{}).get('bulk_reference_result',{})
    spec=manifest['two_electrodes']
    if existing.get('passed') and all(existing.get(k)==spec.get(k) for k in ['salt_mM','mg_mM','temperature_K']):return existing
    folder=Path(package)/'bulk_reference'
    report=folder/'result.json'
    if report.exists():
        cached=json.loads(report.read_text())
        if cached.get('passed') and all(cached.get(k)==spec.get(k) for k in ['salt_mM','mg_mM','temperature_K']):return cached
        raise ValueError('Stored bulk reference does not match the job salt/temperature or lacks a passing result; prepare a new job.')
    spec=manifest['two_electrodes']
    if not folder.exists():
        try:
            await asyncio.to_thread(prepare_reference,folder,salt_mM=spec['salt_mM'],mg_mM=spec['mg_mM'],temperature_K=spec['temperature_K'],seed=spec['seed'])
        except subprocess.SubprocessError as exc:
            raise ValueError(f'Bulk reference preparation failed: {exc}') from exc
    if not (folder/'bulk.conf').is_file():raise ValueError('Bulk reference preparation is incomplete; inspect bulk_reference before retrying')
    write_reference_configs(folder)
    for stem in ('bulk_min', 'bulk_heat', 'bulk'):
        if reference_stage_complete(folder,stem):continue
        code=await execute(folder,stem)
        if code or not reference_stage_complete(folder,stem):
            log=folder/f'{stem}.log'
            lines=log.read_text(errors='replace').splitlines() if log.exists() else []
            details=list(dict.fromkeys(line.strip() for line in lines if line.startswith(('ERROR:', 'FATAL ERROR:'))))
            cause='; '.join(details[:6]) or 'No NAMD error detail was recorded'
            raise ValueError(f'Bulk reference {stem} failed (exit {code}): {cause}; see bulk_reference/{stem}.log')
    result=assess_reference(folder)
    report.write_text(json.dumps(result,indent=2)+'\n')
    return result


def reference_conf(temperature_K, seed, box=(5.,5.,5.), n_atoms=0, mg_hexahydrate=False, *, stage='bulk', salt_mM=150., mg_mM=0.):
    """Each phase gets its own process: constraints/barostat are startup options."""
    if stage not in ('bulk_min','bulk_heat','bulk'):
        raise ValueError(f'Unknown reference stage: {stage}')
    text=s._render_solvated_namd_conf('bulk',box,n_atoms,nacl_mM=salt_mM,mgcl2_mM=mg_mM,mg_hexahydrate=mg_hexahydrate)
    text=re.split(r'(?m)^minimize\s',text)[0]
    keys='outputName|outputEnergies|xstFreq|xstFile|dcdFile|rigidBonds|timestep|temperature|langevinTemp|langevinPiston|langevinPistonTemp'
    text=re.sub(rf'(?mi)^\s*(?:{keys})\s+[^\n]*\n','',text)
    text+=f'\nseed {seed}\noutputName output/{stage}\noutputEnergies 500\nxstFreq 500\nxstFile output/{stage}.xst\ndcdFile output/{stage}.dcd\n'
    if stage=='bulk_min':
        return text+'temperature 0\nlangevinTemp 0\nlangevinPiston off\nrigidBonds none\ntimestep 1\nminimize 4800\n'
    previous='bulk_min' if stage=='bulk_heat' else 'bulk_heat'
    text+=f'binCoordinates output/{previous}.coor\nextendedSystem output/{previous}.xsc\nrigidBonds all\ntimestep 2\nlangevinTemp {temperature_K}\nlangevinPistonTemp {temperature_K}\n'
    if stage=='bulk_heat':
        return text+f'temperature {temperature_K}\nlangevinPiston off\nfirsttimestep 4800\nrun 12500\n'
    return text+'binVelocities output/bulk_heat.vel\nlangevinPiston on\nfirsttimestep 17300\nrun 250000\n'


def write_reference_configs(folder):
    """Upgrade old prepared references without altering atoms, salt or coordinates."""
    folder=Path(folder)
    meta=json.loads((folder/'reference.json').read_text())
    psf=(folder/'bulk.psf').read_text()
    for stage in ('bulk_min','bulk_heat','bulk'):
        path=folder/f'{stage}.conf'
        text=reference_conf(meta['temperature_K'],meta['seed'],n_atoms=s._find_last_atom_serial(psf),mg_hexahydrate=bool(meta['mg_mM']),stage=stage,salt_mM=meta['salt_mM'],mg_mM=meta['mg_mM'])
        if path.exists() and path.read_text()!=text:
            backup=path.with_suffix('.conf.before-split-stages')
            if not backup.exists():shutil.copy2(path,backup)
        path.write_text(text)


def reference_stage_complete(folder, stem):
    """Completed output plus a normal NAMD exit; partial checkpoints are insufficient."""
    folder=Path(folder)
    expected={'bulk_min':4800,'bulk_heat':17300,'bulk':267300}[stem]
    try:
        for suffix in ('coor','vel','xsc'):
            if (folder/'output'/f'{stem}.{suffix}').stat().st_size==0:return False
        with (folder/f'{stem}.log').open('rb') as stream:
            stream.seek(max(0,stream.seek(0,2)-65536))
            tail=stream.read().decode(errors='replace')
        rows=[r for r in (folder/'output'/f'{stem}.xsc').read_text().splitlines() if r.strip() and not r.startswith('#')]
        return bool(rows and int(rows[-1].split()[0])>=expected and 'WallClock:' in tail and 'FATAL ERROR' not in tail)
    except (OSError,ValueError,IndexError):return False


def reference_process(folder, stem, proc_root=Path('/proc')):
    """Match both the command and working directory, since every job uses bulk.conf."""
    folder=Path(folder).resolve()
    for entry in Path(proc_root).iterdir():
        if not entry.name.isdigit():continue
        try:
            args=(entry/'cmdline').read_bytes().split(b'\0')
            if args and b'namd' in Path(args[0].decode()).name.lower().encode() and f'{stem}.conf'.encode() in args and (entry/'cwd').resolve()==folder:
                return int(entry.name)
        except (OSError,UnicodeError):continue
    return None
