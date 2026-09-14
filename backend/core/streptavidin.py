"""PDB-derived, particle-local streptavidin coatings; not a force-field model."""
from functools import lru_cache
from pathlib import Path
import hashlib
import math
import json

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.core.models import Mat4x4, StreptavidinCoating
from backend.core.protein import parse_protein_pdb

PDB_PATH = Path(__file__).resolve().parents[1] / 'data/proteins/1STP-assembly1.pdb'


@lru_cache(maxsize=2)
def streptavidin_asset(mode='adsorption'):
    # In this biological-assembly file, four MODEL records are assembly copies,
    # not an NMR ensemble. Flatten explicitly before the normal first-model parser.
    text = PDB_PATH.read_text()
    records, model = [], 0
    for line in text.splitlines():
        if line.startswith('MODEL'):
            model += 1
        if line.startswith('ATOM  ') or (line.startswith('HETATM') and line[17:20] == 'BTN' and model == 1 and mode == 'biotin_tether'):
            if not 1 <= model <= 4:
                raise ValueError('Unexpected 1STP biological assembly layout')
            records.append(line[:21] + 'ABCD'[model - 1] + line[22:])
    asset = parse_protein_pdb('\n'.join(records), name='Streptavidin tetramer (1STP assembly 1)', source_filename=PDB_PATH.name)
    if len({a.chain_id for a in asset.atoms if a.name == 'CA'}) != 4:
        raise ValueError('Streptavidin requires the complete biological tetramer')
    center = np.mean([[a.x, a.y, a.z] for a in asset.atoms if a.res_name != 'BTN'], axis=0)
    for atom in asset.atoms:
        atom.x, atom.y, atom.z = (np.array([atom.x, atom.y, atom.z]) - center).tolist()
    asset.center_of_mass = [0., 0., 0.]
    asset.id = 'streptavidin-1stp-assembly1-' + mode
    asset.metadata.update({
        'pdb_id': '1STP', 'assembly': 1, 'source_url': 'https://files.rcsb.org/download/1STP.pdb1',
        'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'preparation': 'Four assembly copies renamed A–D; waters removed; crystallographic coordinates retained. Only tether-site biotin retained for biotin mode. Missing residues/hydrogens are not rebuilt.',
    })
    return asset


def estimate_streptavidin(diameter_nm, footprint_nm2=40.0):
    if not 5 <= diameter_nm <= 100:
        raise ValueError('Streptavidin packing currently supports core diameters 5–100 nm.')
    if not 25 <= footprint_nm2 <= 100:
        raise ValueError('Streptavidin footprint must be 25–100 nm² per tetramer.')
    return max(1, math.floor(math.pi * diameter_nm**2 / footprint_nm2))


def build_streptavidin_coating(diameter_nm, mode='adsorption', footprint_nm2=40., spacer_nm=None, seed=1, coverage_reference=None, count_override=None):
    if mode not in ('adsorption', 'biotin_tether'):
        raise ValueError('Unsupported streptavidin conjugation mode')
    spacer = (0.3 if mode == 'adsorption' else 4.0) if spacer_nm is None else spacer_nm
    if not math.isfinite(spacer) or not 0 <= spacer <= 20:
        raise ValueError('Spacer must be finite and between 0 and 20 nm.')
    count = estimate_streptavidin(diameter_nm, footprint_nm2)
    source = 'https://doi.org/10.1016/j.mee.2007.01.247'
    if coverage_reference is not None:
        presets = json.loads((PDB_PATH.parent / 'streptavidin_coverage.json').read_text())['presets']
        preset = next((p for p in presets if p['id'] == coverage_reference), None)
        if preset is None:
            raise ValueError('Unknown streptavidin coverage publication')
        count = max(1, math.floor(math.pi * diameter_nm**2 / preset['effective_area_nm2'] + 1e-9))
        source = preset['url']
    if count_override is not None:
        if isinstance(count_override, bool) or not isinstance(count_override, int) or not 1 <= count_override <= 1500:
            raise ValueError('Tetramer count must be an integer from 1 to 1500')
        count = count_override
    asset = streptavidin_asset(mode).model_copy(deep=True)
    xyz = np.array([[a.x, a.y, a.z] for a in asset.atoms])
    anchor = next((np.array([a.x, a.y, a.z]) for a in asset.atoms if a.res_name == 'BTN' and a.name == 'C11'), None)
    tail = next((np.array([a.x, a.y, a.z]) for a in asset.atoms if a.res_name == 'BTN' and a.name == 'C10'), None)
    rng = np.random.default_rng(seed)
    placed, clouds = [], []
    radius = diameter_nm / 2
    for i in range(count):
        z = 1 - 2 * (i + 0.5) / count
        azimuth = i * math.pi * (3 - math.sqrt(5))
        normal = np.array([math.sqrt(1-z*z)*math.cos(azimuth), math.sqrt(1-z*z)*math.sin(azimuth), z])
        # Isotropic adsorption is an ensemble realization, not a claimed unique
        # contact chemistry. Biotin's outward carboxyl attachment points inward.
        rotation = Rotation.random(random_state=rng).as_matrix()
        if mode == 'biotin_tether':
            from backend.core.pdb_to_design import _rotation_between
            exit_axis = anchor - tail  # bound biotin's solvent-facing carboxyl tail
            rotation = _rotation_between(exit_axis / np.linalg.norm(exit_axis), -normal)
            rotation = Rotation.from_rotvec(normal * rng.uniform(0, 2*math.pi)).as_matrix() @ rotation
        rotated = xyz @ rotation.T
        if mode == 'adsorption':
            # Exact radial clearance of every imported heavy atom from the core.
            projections = rotated @ normal
            tangent2 = np.sum(rotated**2, axis=1) - projections**2
            offset = float(np.max(-projections + np.sqrt(np.maximum(0, (radius + spacer + .17)**2 - tangent2))))
            translation = normal * offset
        else:
            translation = normal * (radius + spacer) - rotation @ anchor
        cloud = rotated + translation
        if np.min(np.linalg.norm(cloud, axis=1)) < radius + .17:
            continue  # requested tether cannot place this protein outside the core
        center = cloud.mean(axis=0)
        extent = np.max(np.linalg.norm(cloud - center, axis=1))
        clash = False
        for other_center, other_extent, tree in clouds:
            if np.linalg.norm(center-other_center) <= extent + other_extent + .25:
                if np.min(tree.query(cloud, k=1)[0]) < .25:
                    clash = True
                    break
        if clash:
            continue
        pose = np.eye(4); pose[:3,:3] = rotation; pose[:3,3] = translation
        placed.append(Mat4x4(values=pose.ravel().tolist()))
        clouds.append((center, extent, cKDTree(cloud)))
    if not placed:
        raise ValueError('No clash-free streptavidin placement fits this size and spacer. Increase the spacer.')
    return StreptavidinCoating(coverage_reference=coverage_reference, count_override=count_override, source=source, mode=mode, footprint_nm2=footprint_nm2, spacer_nm=spacer, seed=seed,
        target_count=count, protein=asset, poses=placed,
        placement_note='Area-based target; deterministic Fibonacci sites with 0.25 nm inter-protein heavy-atom clearance. Clash-rejected sites are omitted and the actual count is reported. Adsorption orientations are sampled; biotin mode points the occupied pocket toward the surface. Linker is a geometric spacer, not an atomistic bond.')


def coating_simulation_gaps(design):
    particles = [p for p in design.nanoparticles if p.coating]
    fixed_ready = False
    if particles:
        from backend.core.gold_strep_dna import validate_fixed_core_design
        try:
            validate_fixed_core_design(design)
            fixed_ready = True
        except ValueError:
            pass
    return {
        'oxdna_fixed_core_ready': fixed_ready,
        'coated_particles': len(particles), 'tetramers': sum(len(p.coating.poses) for p in particles),
        'simulation_ready': not particles,
        'engines': {
            'NAMD': 'Missing coating expansion into PSF, terminal/missing-residue preparation, biotin/linker parameters, gold/QD core interactions and protein–core attachment forces.',
            'OpenMM': 'Implicit builder currently constructs DNA-only Amber topology. Needs protein/cofactor topology, core interactions and attachment forces.',
            'oxDNA/DNANM': 'CPU/GPU job support: fixed gold core, one PDB tetramer and one biotinylated DNA per particle, with core repulsion, ANM, positional anchors and a prescribed DNA tether. Configure in Conjugate Manager. Mobile cores, multiple tetramers, live oxpy and calibrated adsorption/binding energetics remain unsupported. GPU convergence and sampling validation remain open.',
            'mrDNA': 'DNA multiresolution/ARBD mapping lacks coating rigid bodies, core excluded volume, tether forces and persistent identity across resolution changes.',
            'CanDo': 'DNA elastic-beam model lacks particle/protein rigid bodies, their mass and hydrodynamic drag, contact and attachment constraints.',
            'SNUPI': 'DNA mechanics/hydrodynamics lacks coating bodies, attachment constraints and protein/core contact and drag contributions.',
            'Geometric relaxation': 'DNA/linker geometry solvers do not include protein-coating excluded volume or coating attachment mechanics.',
        },
    }


def require_coating_simulation_support(design, engine):
    if engine in ('oxDNA', 'oxDNA/DNANM') and any(getattr(p, 'oxdna_fixed_core', False) for p in getattr(design, 'nanoparticles', [])):
        from backend.core.gold_strep_dna import validate_fixed_core_design
        validate_fixed_core_design(design)
        return
    if any(getattr(p, "coating", None) for p in getattr(design, "nanoparticles", [])):
        raise ValueError(f'{engine}: streptavidin-coated nanoparticles are not simulation-ready. Core interactions, coating instances and attachment force-field parameters are not implemented; refusing to silently omit the coating. See docs/streptavidin_simulation_audit.md.')
