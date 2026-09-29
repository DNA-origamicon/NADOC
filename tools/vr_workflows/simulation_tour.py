"""Review existing 2hb_1xT results in an isolated desktop/native VR session."""
import json
from pathlib import Path
import shutil
from tools.vr_workflows.tour_catalog import ROOT


def prepare_workspace(destination):
    source = ROOT / 'workspace'
    design = json.loads((source / '2hb_1xT.nadoc').read_text())
    design['metadata']['name'] = '__e2e__VR Simulation 2hb_1xT'
    (destination / '2hb_1xT.nadoc').write_text(json.dumps(design))
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
            if data.get('design_source_path') != '2hb_1xT.nadoc' or data.get('status') != 'completed':
                continue
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
            inventory.append(dict(engine=kind, job=identifier, source=str(path)))
    (destination / 'simulation-fixtures.json').write_text(json.dumps(inventory, indent=2))
    return inventory


def main():
    from tools.vr_workflows.ligation_tour import main as launch
    launch('simulations', prepare_workspace=prepare_workspace)


if __name__ == '__main__':
    main()
