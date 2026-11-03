"""NAMD engine and compact host-stage memory envelopes from origami probes.

These are conservative engineering budgets, not 99% tolerance bounds. Separate
RAM/VRAM and execution modes; refuse to certify configurations outside the
measured domain. Application memory and the host reserve are additional.
"""
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
import math
import re
import shlex


@dataclass(frozen=True)
class MemoryEstimate:
    atoms: int
    gpu_resident: bool
    ram_mib: int
    gpu_mib: int
    supported: bool
    limitations: tuple[str, ...] = ()
    basis: str = 'origami-20261101-resolved-pme-envelope-v3'
    confidence: None = None
    patch_layout: dict | None = None
    components: dict | None = None
    expected: dict | None = None

    def as_dict(self):
        return asdict(self)


def health_memory_mib(atoms):
    """Additional peak RSS allowance for the compact health reader.

    Four origami families, including full-frame checks; retain the preceding
    allowance outside the measured atom domain. This is not a confidence bound.
    """
    if 0 < atoms <= 3_000_000:
        return math.ceil(256 + atoms / 1e6 * 400)
    return math.ceil(512 + max(0, atoms) / 1e6 * 1200)


def health_expected_mib(atoms):
    """Descriptive process peak, not time-average usage or admission."""
    return math.ceil(160 + atoms / 1e6 * 303) if 0 < atoms <= 3_000_000 else None


def preparation_memory_mib(atoms, *, extra_bonds=2_600_000):
    """Preparation budget including topology, solvent temporaries and ENM build.

    Compact preparation qualified on four origami families and the 31 nm cube,
    both profiles. Atom upper bounds can include 10% solvent-count headroom.
    Keep the prior allowance outside that domain; application/OS reserve is extra.
    """
    if 0 < atoms <= 3_300_000 and 0 <= extra_bonds <= 2_600_000:
        return math.ceil(512 + atoms/1e6*700 + extra_bonds*192/1024**2)
    return math.ceil(1024 + max(0,atoms)/1e6*1600 + max(0,extra_bonds)*192/1024**2)


def preparation_expected_mib(atoms, *, extra_bonds=2_600_000):
    """Expected compact preparation peak; unknown restraints use the allowance."""
    if 0 < atoms <= 3_300_000 and 0 <= extra_bonds <= 2_600_000:
        return math.ceil(128 + atoms/1e6*600 + extra_bonds/1e6*152)
    return None


def prepare_with_memory_budget(prepare, design, job_dir, **kwargs):
    """Reserve explicit-DNA preparation before allocating solvent/topology arrays."""
    import json
    from backend.core.md_vram import estimate_profile_from_design
    from backend.core.memory_budget import reserve,MemoryBudgetExceeded,reclaim_discretionary_memory
    screening=kwargs.get('salt_mode')=='screening'
    profile=estimate_profile_from_design(design,padding_nm=kwargs.get('padding_nm',6),
        box_mode=kwargs.get('box_mode','rotation'),box_size_nm=kwargs.get('box_size_nm'),
        atomistic_model=kwargs.get('atomistic_model'),nacl_mM=0 if screening else kwargs.get('ion_conc_mM',0),
        mgcl2_mM=12.5 if screening else kwargs.get('mg_conc_mM',12.5))
    if not profile or not 0<profile['atom_upper_bound']<=3_300_000:
        raise MemoryBudgetExceeded('Local preparation is outside the characterized atom-count envelope')
    required=preparation_memory_mib(profile['atom_upper_bound'])
    receipt=dict(atom_upper_bound=profile['atom_upper_bound'],ram_mib=required,
        expected_peak_ram_mib=preparation_expected_mib(profile['atom_upper_bound']),
        extra_bonds_allowance=2_600_000,basis='origami-20261102-compact-preparation-v2',confidence=None)
    Path(job_dir).mkdir(parents=True,exist_ok=True)
    (Path(job_dir)/'preparation_resources.json').write_text(json.dumps(receipt,indent=2)+'\n')
    reclaim_discretionary_memory()
    with reserve(required*1024**2,kind='simulation',label='NAMD DNA preparation'):
        return prepare(design,job_dir,**kwargs)


def execution_options(atoms, **settings):
    """Preview alternatives; explicit mode choices are never silently changed."""
    return {name: {**estimate_memory(atoms, gpu_resident=resident, **settings).as_dict(),
                   'health_ram_mib': health_memory_mib(atoms),
                   'expected_health_peak_ram_mib': health_expected_mib(atoms)}
            for name, resident in [('resident', True), ('offload', False)]}


def estimate_memory(atoms, *, gpu_resident=True, extra_bonds=0,
                    pairlist=13.5, pme_spacing=1.5, box_angstrom=None,
                    margin=3, threads=16, two_away=(None,None,None), shared_bytes=49152,check_patch=True):
    atoms = int(atoms)
    issues = []
    if (not all(math.isfinite(float(v)) for v in (pairlist,pme_spacing,margin,threads,extra_bonds))
            or pme_spacing <= 0):
        return MemoryEstimate(atoms,gpu_resident,0,0,False,('invalid numerical resource settings',))
    if box_angstrom is not None:
        if len(box_angstrom) != 3 or any(not math.isfinite(float(d)) or float(d)<=0 for d in box_angstrom):
            return MemoryEstimate(atoms,gpu_resident,0,0,False,('invalid periodic box dimensions',))
        if atoms / math.prod(float(d) for d in box_angstrom) > .12:
            issues.append('atom density exceeds the tested solvated-system envelope')
    if not 0 < atoms <= 3_000_000:
        issues.append('atom count outside the measured range (up to 3 million)')
    if not 0 < pairlist <= 24 or not 0 <= margin <= 30:
        issues.append('neighbor or patch settings outside the measured range')
    if not 0.75 <= pme_spacing <= 1.5:
        issues.append('PME spacing outside the measured range')
    if not 1 <= threads <= 32 or not 0 <= extra_bonds <= 2_600_000:
        issues.append('worker/restraint count outside the measured range')
    n = max(0, atoms) / 1e6
    host_parts = dict(fixed_mib=512., topology_and_engine_mib=(3600 if gpu_resident else 2200)*n)
    gpu_parts = dict(fixed_mib=512., atoms_and_default_buffers_mib=(3500 if gpu_resident else 2400)*n)
    # Tuple metadata/staging buffers; measured 1.78M extra bonds added 259 MiB RSS.
    host_parts['restraints_mib'] = max(0, extra_bonds) * 192 / 1024**2
    gpu_parts['restraints_mib'] = max(0, extra_bonds) * 96 / 1024**2
    # Neighbor-buffer volume correction; keep patch layouts in the tested domain.
    gpu_parts['neighbor_allowance_mib'] = 0.16 * 3500 * n * max(0, (pairlist / 13.5)**3 - 1)
    gpu_parts['fine_pme_allowance_mib'] = 0.
    grid=None
    if box_angstrom is not None:
        from backend.core.namd_pme import pme_grid
        try:
            grid=pme_grid(tuple(float(d) for d in box_angstrom),float(pme_spacing))
            if pme_spacing<1.5:
                base=pme_grid(tuple(float(d) for d in box_angstrom),1.5)
                # Retain the qualified bytes/point allowance while removing
                # the obsolete 20%-per-axis guess for FFT-friendly dimensions.
                gpu_parts['fine_pme_allowance_mib']=max(0,math.prod(grid)-math.prod(base))*48/1024**2
        except ValueError as exc:
            issues.append(str(exc))
    elif pme_spacing<1.5:
        issues.append('box dimensions required for finer PME grid')
    layout=None
    if box_angstrom is not None and check_patch:
        from backend.core.namd_patch_grid import patch_layout
        layout=patch_layout(atoms,box_angstrom,pairlist=pairlist,margin=margin,threads=threads,two_away=two_away,shared_bytes=shared_bytes)
        if not layout['supported']:
            issues.append('CUDA patch layout exceeds its occupancy allowance or has too few patches; use qualified patch subdivision')
    components=dict(host=host_parts,gpu=gpu_parts,pme_grid=grid,
        basis='empirical allocation allowances; resolved PME grid for NAMD Git-2025-12-04',
        unresolved=['neighbor buffer capacity and growth','FFT plan workspace','profile/stage allocation residual'])
    return MemoryEstimate(atoms, gpu_resident, math.ceil(sum(host_parts.values())),
        math.ceil(sum(gpu_parts.values())), not issues, tuple(issues),patch_layout=layout,components=components)


@lru_cache(maxsize=64)
def _psf_atoms(path, size, mtime):
    with open(path) as stream:
        for line in stream:
            if '!NATOM' in line:
                return int(line.split()[0])
    raise ValueError('PSF has no atom count')


def psf_atoms(path):
    path = Path(path).resolve();stat = path.stat()
    return _psf_atoms(str(path), stat.st_size, stat.st_mtime_ns)


def configuration_memory(path, *, threads=16, fallback_box=None, resident_override=None, shared_bytes=49152,cuda_patch=True,
                         detailed=True, engine_binary=None, device='0'):
    """Read literal generated NAMD settings; unresolved Tcl is not a safe estimate."""
    path = Path(path)
    text=path.read_text()
    adaptive=re.search(r'^# NADOC_ADAPTIVE_MIN_BEGIN$.*?^# NADOC_ADAPTIVE_MIN_END$',text,re.M|re.S)
    from backend.core.namd_script import validate_static_order
    order_text=text[:adaptive.start()]+'minimize 0\n'+text[adaptive.end():] if adaptive else text
    validate_static_order(order_text)
    if adaptive:text=text[:adaptive.start()]+text[adaptive.end():]
    # Only generated, characterized directives are understood. A new feature or
    # Tcl command must not silently inherit an unrelated memory certification.
    known_directives = set('''set structure coordinates parameters paratypecharmm
        bincoordinates binvelocities extendedsystem binaryrestart outputname restartname
        cellbasisvector1 cellbasisvector2 cellbasisvector3 cellorigin
        gpuresident pme pmegridspacing pairlistdist margin twoawayx twoawayy twoawayz
        cutoff switchdist switching exclude onefourscaling
        extrabonds extrabondsfile constraints conskcol conskfile consref constraintscaling
        temperature langevin langevintemp langevindamping langevinhydrogen
        langevinpiston langevinpistondecay langevinpistonperiod langevinpistontarget
        langevinpistontemp useconstantarea useflexiblecell usegrouppressure
        timestep rigidbonds rigidtolerance nonbondedfreq fullelectfrequency
        stepspercycle seed wrapall wrapwater wrapnearest
        outputenergies outputtiming dcdfreq dcdfile restartfreq xstfreq xstfile
        firsttimestep run minimize'''.split())
    options = {};extra_files = [];variables = {}
    for line in text.splitlines():
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        if parts[0].lower() not in known_directives:
            raise ValueError('Uncharacterized configuration directive: '+parts[0])
        if len(parts)<2 or any(char in token for token in parts for char in ';[]\\'):
            raise ValueError('Dynamic Tcl configuration requires a measured resource profile')
        if parts[0].lower() == 'set' and len(parts) == 3:
            variables[parts[1]] = parts[2]
        value = ' '.join(parts[1:])
        value = re.sub(r'\$\{?(\w+)\}?', lambda m: variables.get(m[1], m[0]), value)
        if '$' in value:
            raise ValueError('Unresolved configuration value: '+parts[0])
        if parts[0].lower() == 'extrabondsfile':
            extra_files.append(value)
        options[parts[0].lower()] = value
    if any(key in options for key in ('pmegridsizex','pmegridsizey','pmegridsizez')):
        raise ValueError('Explicit PME grids require a measured resource profile')
    if float(options.get('cutoff',10)) > 14:
        raise ValueError('Force cutoff outside the measured range')
    if options.get('gbis','off').lower() in ('on','true','yes','1'):
        raise ValueError('Implicit-solvent memory requires a separate resource profile')
    for key in ('patchdimension','hgroupcutoff','hydrogengroupcutoff','minatomsperpatch','maxpatches','staticatomassignment','lcpo','usegroupcutoff'):
        if key in options:raise ValueError('Unqualified patch-layout override: '+key)
    if 'structure' not in options or '$' in options['structure']:
        raise ValueError('Cannot resolve the stage topology for memory admission')
    atoms = psf_atoms(path.parent / options['structure'])
    if adaptive:
        # Only the exact application-owned bounded minimizer is understood.
        # Markers alone never authorize arbitrary Tcl or changed allocation settings.
        maximum=re.search(r'^set nadoc_min_max (\d+)$',adaptive.group(),re.M)
        if not maximum:raise ValueError('Unrecognized adaptive minimization controller')
        from backend.core.md_protocols import _min_conf
        template=_min_conf(Path(options.get('outputname','')).name,'resource_template',(100.,100.,100.),False,int(maximum[1]),.5,no_enm=True,n_atoms=atoms)
        known=re.search(r'^# NADOC_ADAPTIVE_MIN_BEGIN$.*?^# NADOC_ADAPTIVE_MIN_END$',template,re.M|re.S)
        if not known or known.group()!=adaptive.group():raise ValueError('Modified adaptive controller requires separate resource qualification')
    extra_bonds = 0
    for name in extra_files:
        with (path.parent / name).open() as stream:
            extra_bonds += sum(1 for line in stream if line.split()[:1] == ['bond'])
    box = fallback_box
    if 'extendedsystem' in options and (path.parent / options['extendedsystem']).exists():
        with (path.parent / options['extendedsystem']).open() as stream:
            rows = [line.split() for line in stream if line.strip() and not line.startswith('#')]
        if rows:
            row = rows[-1]
            if any(float(row[j])!=0 for j in (2,3,4,6,7,8)):
                raise ValueError('Skewed checkpoint cells require separate patch qualification')
            box = [math.sqrt(sum(float(row[j])**2 for j in range(i,i+3))) for i in (1,4,7)]
    elif all('cellbasisvector'+str(i) in options for i in (1,2,3)):
        vectors=[list(map(float,options['cellbasisvector'+str(i)].split())) for i in (1,2,3)]
        if any(len(v)!=3 or any(x!=0 for j,x in enumerate(v) if j!=i) for i,v in enumerate(vectors)):
            raise ValueError('Skewed cells require separate patch-layout qualification')
        box = [v[i] for i,v in enumerate(vectors)]
    if box is None and cuda_patch:raise ValueError('Periodic box dimensions are required for patch-capacity admission')
    from backend.core.namd_patch_grid import two_away_options
    result=estimate_memory(atoms,
        gpu_resident=(options.get('gpuresident','off').lower() in ('on','true','yes','1')
                      if resident_override is None else bool(resident_override)),
        extra_bonds=extra_bonds, pairlist=float(options.get('pairlistdist',13.5)),
        pme_spacing=float(options.get('pmegridspacing',1.5)), box_angstrom=box,
        margin=float(options.get('margin',3)), threads=threads,
        two_away=two_away_options(options),shared_bytes=shared_bytes,check_patch=cuda_patch)
    if detailed and cuda_patch and box is not None and result.supported:
        from backend.core.namd_allocation_model import prepared_allocation
        result=replace(result,expected=prepared_allocation(path,options,box,result,
                            engine_binary=engine_binary,device=device,threads=threads))
        if result.expected.get('exceeds_admission'):
            result=replace(result,supported=False,limitations=result.limitations+(
                'Detailed allocation forecast exceeds the admission envelope; separate qualification is required',))
    return result


def prepared_resource_summary(package, *, threads=16, devices='0'):
    """Compare expected engine peaks with the full workflow admission ceiling."""
    import json
    from backend.core.md_protocols import segments_from_manifest
    package=Path(package);manifest=json.loads((package/'manifest.json').read_text())
    _,segments=segments_from_manifest(package/'manifest.json')
    names=[manifest['minimization']['name']]+[s.name for s in segments]
    stages=[];cpu=not devices or str(devices).lower() in ('cpu','none')
    for name in names:
        try:
            e=configuration_memory(package/(name+'.conf'),threads=threads,
                fallback_box=manifest.get('box_ang'),cuda_patch=not cpu,device=devices)
            stages.append(dict(name=name,**e.as_dict()))
        except (ValueError,OSError,MemoryError) as exc:
            stages.append(dict(name=name,supported=False,limitations=[str(exc)],expected=None))
    supported=all(s['supported'] for s in stages)
    expected={k:(max(s['expected'][k] for s in stages)
        if all(s.get('expected') and s['expected'].get(k) is not None for s in stages) else None)
        for k in ('ram_mib','gpu_mib')}
    admission=None
    if supported:
        health=max(health_memory_mib(s['atoms']) for s in stages)
        admission=dict(engine_ram_mib=max(s['ram_mib'] for s in stages),health_ram_mib=health,
            workflow_ram_mib=max(s['ram_mib'] for s in stages)+health,
            gpu_mib=0 if cpu else max(s['gpu_mib'] for s in stages))
    health_expected=[health_expected_mib(s['atoms']) for s in stages if 'atoms' in s]
    expected_health=(max(health_expected) if len(health_expected)==len(stages)
                     and all(v is not None for v in health_expected) else None)
    return dict(supported=supported,expected_engine_peak=expected,
        expected_health_peak_ram_mib=expected_health,admission=admission,stages=stages,
        confidence=None,policy='Expected engine usage is descriptive. Admission includes the conservative engine envelope plus health RAM; OS/application reserves are additional.')
