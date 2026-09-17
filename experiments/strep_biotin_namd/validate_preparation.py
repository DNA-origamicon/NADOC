"""Native protein topology and gold-free linkage-map validation, without MD."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import parmed
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating
from backend.core.gold_strep_dna import build_dna_set
from backend.core.strep_biotin_namd import write_preparation, resolve_psf_identity
from backend.core.namd_topology import _psfgen_script, find_psfgen
from backend.core.md_charge import parse_psf_atoms


def main(output):
    p = Nanoparticle(diameter_nm=10, coating=build_streptavidin_coating(10, count_override=1))
    entries = build_dna_set(p, 'ACGTACGT', linker_nm=1.8)
    p.biotin_dna = [r for r, _, _ in entries]
    d = Design(nanoparticles=[p], helices=[h for _, h, _ in entries], strands=[s for _, _, s in entries])
    manifest = write_preparation(d, output)
    root = output.resolve()
    (root/'source.nadoc').write_text(d.to_json())
    segments = [dict(segid=f.stem, path=f, is_protein=True, first_resid=13, last_resid=133)
                for f in (root/'inputs').glob('P*.pdb')]
    (root/'validate_protein.tcl').write_text(_psfgen_script(segments, root/'protein_reference'))
    proc = subprocess.run([find_psfgen(), str(root/'validate_protein.tcl')], capture_output=True, text=True, timeout=60)
    (root/'protein_psfgen.log').write_text(proc.stdout+'\n'+proc.stderr)
    proc.check_returncode()
    psf = (root/'protein_reference.psf').read_text()
    atoms = parse_psf_atoms(psf)
    mapped = resolve_psf_identity(psf, [a for a in manifest['identity'] if a['component']=='protein'])
    structure = parmed.charmm.CharmmPsfFile(str(root/'protein_reference.psf'))
    parameter_path = Path('backend/data/forcefield/par_all36m_prot.prm')
    structure.load_parameters(parmed.charmm.CharmmParameterSet(str(parameter_path)))
    result = dict(simulation_ready=False, protein_atoms=len(atoms),
                  mapped_protein_heavy_atoms=len(mapped), protein_hydrogens=sum(a.mass<2 for a in atoms),
                  protein_charge=sum(a.charge for a in atoms), protein_bonds=len(structure.bonds),
                  protein_angles=len(structure.angles), protein_dihedrals=len(structure.dihedrals),
                  protein_cmaps=len(structure.cmaps), protein_parameters_resolved=True,
                  parameter_sha256=hashlib.sha256(parameter_path.read_bytes()).hexdigest(),
                  ligand_heavy_atoms=sum(a['component']=='biotin_teg' for a in manifest['identity']),
                  covalent_links=manifest['covalent_links'], blocked_by=manifest['blocked_by'])
    (root/'protein_identity.json').write_text(json.dumps(mapped,indent=2)+'\n')
    (root/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
