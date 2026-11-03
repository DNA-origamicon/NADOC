"""Dry canonical-DNA atom counts from the same CHARMM residue/terminal patches as prep."""
from functools import lru_cache
from pathlib import Path

TOPOLOGY = Path(__file__).resolve().parents[1]/'data/forcefield/top_all36_na.rtf'
RESIDUES = {'DA':'ADE','DT':'THY','DC':'CYT','DG':'GUA'}
NAMES = {'OP1':'O1P','OP2':'O2P','C7':'C5M'}


@lru_cache(maxsize=4)
def _templates(size,mtime):
    blocks={};current=None
    for line in TOPOLOGY.read_text().splitlines():
        fields=line.split('!',1)[0].split()
        if not fields:continue
        if fields[0] in ('RESI','PRES'):
            current=blocks.setdefault(fields[1],dict(add=set(),delete=set()))
        elif current is not None and fields[0]=='ATOM':current['add'].add(fields[1])
        elif current is not None and fields[:2]==['DELETE','ATOM']:current['delete'].add(fields[2])
    return blocks


def canonical_dna_atoms(pdb_text):
    """Return a topology count for unmodified canonical DNA, or None if unresolved.

    TER records disambiguate reused single-character PDB chain IDs. Atom-set
    checks reject proteins, linkers, incomplete sugars and modified heavy atoms.
    This does not estimate water or build coordinates.
    """
    stat=TOPOLOGY.stat();templates=_templates(stat.st_size,stat.st_mtime_ns)
    segments=[];segment=[];previous=None
    for line in pdb_text.splitlines():
        if line.startswith('TER'):
            if segment:segments.append(segment)
            segment=[];previous=None
        elif line.startswith(('ATOM  ','HETATM')):
            residue=line[17:20].strip()
            if residue not in RESIDUES:return None
            key=(line[21:27],residue)
            if key!=previous:
                segment.append([residue,set()]);previous=key
            name=line[12:16].strip();segment[-1][1].add(NAMES.get(name,name))
    if segment:segments.append(segment)
    if not segments:return None
    total=0
    for segment in segments:
        for index,(name,observed) in enumerate(segment):
            atoms=set(templates[RESIDUES[name]]['add'])
            # Exported heavy DNA may still contain the terminal phosphate which
            # 5TER removes. Validate against the unpatched residue first.
            allowed=atoms|{"H2''"}
            if not observed<=allowed or not {"C1'","C2'","C3'","C4'","C5'"}<=observed:return None
            patches=[]
            if index==0:patches.append('5TER')
            if index==len(segment)-1:patches.append('3TER')
            patches.append('DEO5' if index==0 else 'DEOX')
            for patch in patches:
                atoms.difference_update(templates[patch]['delete'])
                atoms.update(templates[patch]['add'])
            total+=len(atoms)
    return total
