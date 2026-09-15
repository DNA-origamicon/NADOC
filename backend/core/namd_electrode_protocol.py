"""Fixed-cell electrode adapter for the shared DNA relaxation ladder."""
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

from backend.core.md_protocols import ELECTRODE_PROTOCOL, prepare_mgh_slow_release
from backend.core.namd_two_electrode_package import build_qualification_package, qualification_config


def electrode_force_block():
    return '\n# Fixed electrode compartment: never barostat the vacuum-padded cell.\nlangevinPiston off\nwrapAll off\nwrapWater off\ntclForces on\ntclForcesScript electrode_forces.tcl\n'


def wall_restraints(pdb):
    sites=[]
    index=0
    for row in pdb.splitlines():
        if not row.startswith(('ATOM  ', 'HETATM')):continue
        index+=1
        if row[17:21].strip()=='GRP' or (row[17:21].strip()=='PEGM' and row[22:26].strip()=='1' and row[12:16].strip()=='C1'):
            sites.append((index,[*[float(row[i:i+8]) for i in (30,38,46)],10. if row[17:21].strip()=='GRP' else 5.]))
    records=' '.join(f'{i} {{{" ".join(map(str,p))}}}' for i,p in sites)
    return f'''
# Preserve harmonic electrode restraints independently of DNA restraint release.
set electrode_sites {{{records}}}
foreach {{id reference}} $electrode_sites {{ addatom $id }}
rename calcforces electrode_slab_forces
proc calcforces {{}} {{
    electrode_slab_forces
    global electrode_sites
    loadcoords xyz
    foreach {{id reference}} $electrode_sites {{
        set k [lindex $reference 3]
        set force {{}}
        set energy 0.0
        for {{set axis 0}} {{$axis < 3}} {{incr axis}} {{
            set dx [expr {{[lindex $xyz($id) $axis]-[lindex $reference $axis]}}]
            lappend force [expr {{-$k*$dx}}]
            set energy [expr {{$energy+0.5*$k*$dx*$dx}}]
        }}
        addforce $id $force
        addenergy $energy
    }}
}}
'''


def prepare_electrode_namd(design, job_dir, *, two_electrodes, namd_peg_coating=None, **kwargs):
    """Build the physical compartment, then reuse ENM, HMR, checkpoints and chunks."""
    if not isinstance(two_electrodes, dict):
        raise ValueError("Electrode relaxation requires two-electrode settings; configure them before preparing the job.")
    # Electrode callbacks have a different crossover from ordinary DNA jobs.
    # The measured 24,677-atom control benefits from resident mode even below
    # the generic size threshold. Retain explicit off for diagnostic comparisons.
    if kwargs.get('gpu_resident_mode', 'auto') in (None, 'auto'):
        kwargs['gpu_resident_mode'] = 'on'
    electrode_manifest={}
    namd_peg_coating=namd_peg_coating or two_electrodes.get('peg_coating')
    temperature=kwargs.pop('electrode_temperature_K',300.)
    water_clearance=kwargs.pop('electrode_water_clearance_nm',.32)
    def build(d, **options):
        if options.get('solute_coords') is not None:
            raise ValueError('Electrode protocol does not yet accept a vacuum/BLADE coordinate seed.')
        with tempfile.TemporaryDirectory(prefix='nadoc_electrode_protocol_') as temp:
            folder=Path(temp)/'system_namd_solvated'
            manifest=build_qualification_package(folder,two_electrodes,
                design=d,atomistic_model=options.get('atomistic_model'),
                salt_mM=options['ion_conc_mM'],mg_mM=options['mg_conc_mM'],
                temperature_K=temperature,seed=options['seed'],peg=namd_peg_coating,
                water_oxygen_clearance_nm=water_clearance)
            electrode_manifest.update(manifest)
            (folder/'namd.conf').write_text(qualification_config(manifest))
            (folder/'electrode_forces.tcl').write_text((folder/'slab.tcl').read_text()+wall_restraints((folder/'system.pdb').read_text()))
            from backend.core.namd_electrode_native import install_native
            electrode_manifest['native_callback']=install_native(folder)
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
                for path in folder.rglob('*'):
                    if path.is_file():archive.write(path,str(path.relative_to(Path(temp))))
            return out.getvalue()
    kwargs.pop('require_full_topology',None)
    kwargs.pop('graphene_only',None)
    kwargs.pop('graphene_nanopore',None)
    result=prepare_mgh_slow_release(design,job_dir,protocol=ELECTRODE_PROTOCOL,
        require_full_topology=True,graphene_only=not bool(design.strands),
        fixed_cell=True,target_temperature_K=temperature,package_builder=build,**kwargs)
    folder=Path(job_dir)/result[0]
    for path in folder.glob('*.conf'):
        path.write_text(apply_electrode_forces(path.read_text(),peg=bool(electrode_manifest.get('peg')),combined_slab=True))
    path=folder/'manifest.json'
    manifest=json.loads(path.read_text())
    manifest['two_electrodes']=electrode_manifest
    manifest['solvation']['npt_allowed']=False
    manifest['electrode_validation']={'status':'unqualified','bulk_reference':'bulk_reference',
        'required':['liquid density','ion-profile stationarity','DNA health when present','PEG health when present']}
    path.write_text(json.dumps(manifest,indent=2)+'\n')
    (folder/'nadoc_md_run.json').write_text(path.read_text())
    return result


def apply_electrode_forces(text, *, peg=False, combined_slab=False):
    scripts=re.findall(r'(?mi)^\s*tclForcesScript\s+([^\n]+)',text)
    allowed={'electrode_forces.tcl'} | ({'slab.tcl'} if combined_slab else set())
    if any(script.strip() not in allowed for script in scripts):
        raise ValueError('Electrode forces cannot replace another Tcl force script; combine and validate the callbacks first.')
    text=re.sub(r'(?mi)^\s*(?:langevinPiston|wrapAll|wrapWater|tclForces|tclForcesScript)\s+[^\n]*\n','',text)
    # Startup directives must precede even an adaptive Tcl minimization loop.
    text=electrode_force_block()+text
    if peg:text='parameters forcefield/par_all35_ethers.prm\n'+text
    return text
