"""Audit a returned CGenFF BTMP stream; successful audit does not qualify BTE5."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def audit(package, stream, output):
    import parmed
    from backend.core.namd_topology import find_psfgen
    from experiments.strep_biotin_namd.prepare_parameterization import digest, dump

    package, stream = package.resolve(), stream.resolve()
    if output.exists():
        raise FileExistsError(output)
    ff = package / 'reference_forcefield'
    for record in json.loads((package / 'reference_forcefield.json').read_text()):
        if digest(package / record['file']) != record['sha256']:
            raise ValueError('Reference force-field hash mismatch')
    raw = stream.read_text()
    version = re.search(r'For use with CGenFF(?: topology and parameter files)? version\s+([\d.]+)', raw, re.I)
    reference_version = re.search(r'Force Field v\.\s*([\d.]+)', (ff / 'top_all36_cgenff.rtf').read_text())
    if not version or not reference_version or version[1] != reference_version[1]:
        raise ValueError('Missing or incompatible CGenFF library version; obtain matching reference files')
    parameters = parmed.charmm.CharmmParameterSet(str(ff / 'top_all36_cgenff.rtf'),
                                                str(ff / 'par_all36_cgenff.prm'), str(stream))
    residue = parameters.residues.get('BTMP')
    if residue is None:
        raise ValueError('Expected BTMP residue in the returned stream')
    identity = json.loads((package / 'atom_mapping.json').read_text())
    expected = {a['name'] for a in identity}
    if len(residue.atoms) != len(expected) or {a.name for a in residue.atoms} != expected:
        raise ValueError('Atom names/count differ; explicit remapping is required')
    charge = sum(a.charge for a in residue.atoms)
    if abs(charge + 1) > 1e-5:
        raise ValueError(f'Wrong assigned total charge: {charge}')
    # MOL2 carries explicit hydrogen connectivity; residue topology may encode
    # resonance bond orders differently, so compare edges rather than orders.
    mol2_lines = (package / 'BTMP.mol2').read_text().splitlines()
    start = mol2_lines.index('@<TRIPOS>BOND') + 1
    edges = set()
    ids = {a['index_1based']: a['name'] for a in identity}
    for line in mol2_lines[start:]:
        if line.startswith('@'):
            break
        fields = line.split()
        edges.add(frozenset((ids[int(fields[1])], ids[int(fields[2])])) )
    actual = {frozenset((b.atom1.name, b.atom2.name)) for b in residue.bonds}
    if actual != edges:
        raise ValueError('Returned topology does not preserve the input connectivity')
    lines = raw.splitlines(keepends=True)
    begin = next((i+1 for i, line in enumerate(lines)
                  if re.match(r'\s*read\s+rtf\b', line, re.I)), None)
    if begin is None:
        raise ValueError('No RTF block found')
    end = next(i for i in range(begin, len(lines)) if lines[i].strip().upper() == 'END')
    with tempfile.TemporaryDirectory(prefix='assignment_audit_', dir=package) as temp:
        temp = Path(temp)
        rtf = temp / 'candidate.rtf'
        rtf.write_text(''.join(lines[begin:end+1]))
        script = temp / 'audit.tcl'
        psf = temp / 'candidate.psf'
        script.write_text(f'topology {{{ff / "top_all36_cgenff.rtf"}}}\n'
                          f'topology {{{rtf}}}\n'
                          'segment REF {\nfirst NONE\nlast NONE\nresidue 1 BTMP\n}\n'
                          'regenerate angles dihedrals\n'
                          f'writepsf {{{psf}}}\n')
        proc = subprocess.run([find_psfgen(), str(script)], capture_output=True, text=True, timeout=30)
        proc.check_returncode()
        structure = parmed.charmm.CharmmPsfFile(str(psf))
        structure.load_parameters(parameters)
        if len(structure.atoms) != len(identity):
            raise ValueError('Final PSF atom count mismatch')
    atom_penalties = []
    parameter_penalties = []
    for line in raw.splitlines():
        fields, _, comment = line.partition('!')
        tokens = fields.split()
        if tokens[:1] == ['ATOM'] and re.match(r'\s*\d+(?:\.\d+)?(?:\s|$)', comment):
            atom_penalties.append(dict(atom=tokens[1], atom_type=tokens[2],
                                       charge=float(tokens[3]), penalty=float(comment.split()[0])))
        penalty = re.search(r'penalty\s*=\s*([\d.]+)', comment, re.I)
        if penalty and tokens and tokens[0] != 'RESI':
            parameter_penalties.append(dict(assignment=fields.strip(), penalty=float(penalty[1]),
                                            provenance=comment.strip()))
    report = dict(status='assignment_graph_and_coverage_checked', simulation_ready=False,
                  source_stream=str(stream), sha256=digest(stream), cgenff_library=version[1],
                  atoms=len(identity), charge=charge, parameters_resolved=True,
                  psf_terms=dict(bonds=len(structure.bonds), angles=len(structure.angles),
                                 dihedrals=len(structure.dihedrals), impropers=len(structure.impropers)),
                  charge_penalties=atom_penalties, parameter_penalties=parameter_penalties,
                  max_charge_penalty=max((a['penalty'] for a in atom_penalties), default=None),
                  max_parameter_penalty=max((a['penalty'] for a in parameter_penalties), default=None),
                  review_lines=[line for line in raw.splitlines()
                                if re.search(r'penalty|warning|version', line, re.I)],
                  remaining=['review all charge and parameter penalties',
                             'QM/refinement of uncertain assignments',
                             'actual DNA context and BTE/BTE5 patch qualification',
                             'GPU NAMD physical validation'])
    dump(output, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('stream', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.package, args.stream, args.output), indent=2))
