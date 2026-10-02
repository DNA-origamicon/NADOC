"""Review existing simulation results in an isolated desktop/native VR session.

The default fixture is 2hb_1xT; NADOC_VR_AUDIT_DESIGN selects a full-size source.
"""
import os
import json
from pathlib import Path
import shutil
from tools.vr_workflows.tour_catalog import ROOT


def psf_inventory(path):
    """Count topology atoms and distinct nucleic-acid residues, excluding solvent."""
    bases={'ADE','CYT','GUA','THY','URA','DA','DC','DG','DT','DU','A','C','G','T','U'}
    residues=set()
    with path.open() as stream:
        for line in stream:
            if '!NATOM' in line:
                count=int(line.split()[0]);break
        else:raise ValueError('PSF has no atom section')
        for _ in range(count):
            fields=next(stream).split()
            if len(fields)<5:raise ValueError('Incomplete PSF atom record')
            if fields[3].upper() in bases:residues.add((fields[1],fields[2]))
    return {'topology':str(path),'atoms_including_solvent':count,'nucleic_acid_residues':len(residues)}


def prepare_workspace(destination):
    source = ROOT / 'workspace'
    design_path=Path(os.environ.get('NADOC_VR_AUDIT_DESIGN',source/'2hb_1xT.nadoc'))
    design = json.loads(design_path.read_text())
    if os.environ.get('NADOC_VR_AUDIT_DESIGN'):
        for loadout in design.get('loadouts',[]):
            loadout['head_revision_id']=None;loadout['base_revision_id']=None
        os.environ['NADOC_VR_SIM_ENGINES']='namd'
    selected_engines=set()
    design['metadata']['name'] = '__e2e__VR Simulation '+design_path.stem
    (destination / design_path.name).write_text(json.dumps(design))
    inventory = []
    for kind in ('cando', 'snupi', 'mrdna', 'oxdna', 'md', 'lammps'):
        folder = source / (kind + '_jobs')
        paths = {p.parent.name: p.parent for p in folder.glob('*/job.json')}
        index = folder / '.archive_index.json'
        if index.exists():
            paths.update({key: Path(value) for key, value in json.loads(index.read_text()).items()})
        for identifier, path in paths.items():
            manifest = path / 'job.json'
            if not manifest.exists():
                continue
            data = json.loads(manifest.read_text())
            if data.get('design_source_path') != design_path.name or data.get('status') != 'completed':
                continue
            if os.environ.get('NADOC_VR_AUDIT_DESIGN') and kind in selected_engines:continue
            selected_engines.add(kind)
            target = destination / (kind + '_jobs') / identifier
            def copy_file(src, dst):
                # Trajectories are immutable inputs here; all writable metadata,
                # caches and analysis output are private copies in this workspace.
                if Path(src).suffix.lower() in ('.dcd', '.xtc', '.trr'):
                    Path(dst).symlink_to(Path(src).resolve())
                else:
                    shutil.copy2(src, dst)
            shutil.copytree(path, target, copy_function=copy_file)
            data['archived'] = False
            data['archive_path'] = None
            def relocate(value):
                if isinstance(value, str) and value.startswith(str(path) + '/'):
                    return str(target) + value[len(str(path)):]
                if isinstance(value, dict): return {k: relocate(v) for k, v in value.items()}
                if isinstance(value, list): return [relocate(v) for v in value]
                return value
            (target / 'job.json').write_text(json.dumps(relocate(data)))
            fixture=dict(engine=kind,job=identifier,source=str(path),design_source_path=data.get('design_source_path'),
                         design_fingerprint=data.get('design_fingerprint'),design_revision_id=data.get('design_revision_id'))
            topology=path/data.get('package_subdir','')/(data.get('name_stem','')+'.psf')
            if kind=='md' and topology.is_file():fixture['topology_inventory']=psf_inventory(topology)
            inventory.append(fixture)
    (destination / 'simulation-fixtures.json').write_text(json.dumps(inventory, indent=2))
    return inventory


def main():
    from tools.vr_workflows.ligation_tour import main as launch
    launch('simulations', prepare_workspace=prepare_workspace)


if __name__ == '__main__':
    main()
