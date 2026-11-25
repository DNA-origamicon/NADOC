"""Construct a fully supported publication route through native recorded actions."""
import argparse
import hashlib
import json
from pathlib import Path

from backend.core.publication_authoring import compile_publication
from tools.design_archive.recorded_authoring import construct
from scripts.agent_structure_guard import publish, audit
from backend.core.models import Design


def compare(design, evidence):
    ids={v:int(k) for k,v in evidence['helix_ids'].items()}
    actual={}
    for s in design.strands:
        sites=[]
        for d in s.domains:
            step=1 if d.direction.value=='FORWARD' else -1
            sites.extend((ids[d.helix_id],bp) for bp in range(d.start_bp,d.end_bp+step,step))
        actual['scaf' if s.is_scaffold else s.name]=sites
    expected={'scaf':evidence['classified']['scaf'][0]['sites']}
    expected.update({f'Staple {i}':p['sites'] for i,p in enumerate(evidence['classified']['stap'],1)})
    if actual!=expected:
        raise ValueError('Native directed routes differ from PDF evidence')
    loops=sorted((ids[h.id],m.bp_index,m.delta) for h in design.helices for m in h.loop_skips)
    if loops!=sorted(tuple(x) for x in evidence['insertions']['counts']):
        raise ValueError('Native insertion counts differ from PDF evidence')
    for i,path in enumerate(evidence['classified']['stap'],1):
        strand=next(s for s in design.strands if s.name==f'Staple {i}')
        if strand.sequence!=path['table_row']['sequence']:
            raise ValueError('Native sequence differs from published oligo')
    if design.extensions or design.overhangs:
        raise ValueError('Unexpected terminal-extension/overhang substitution')
    return {'routes':len(expected),'insertions':len(loops),'published_staples':len(expected)-1,
            'native_reference_consulted':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--diagram-page',type=int,required=True)
    parser.add_argument('--table-page',type=int,required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Never overwrite a shared design')
    pdf=args.pdf.read_bytes()
    dependency=args.output.parent/'.provenance'/args.name/args.pdf.name
    relative='Shared Designs/'+dependency.relative_to(args.output.parent).as_posix()
    recipe,evidence=compile_publication(pdf,diagram_page=args.diagram_page,table_page=args.table_page,
        name=args.name,source_path=relative)
    recipe['execution_code']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in [
        'backend/core/publication_authoring.py','backend/core/publication_routing.py',
        'backend/core/publication_sequence_search.py','tools/design_archive/recorded_authoring.py']}
    args.evidence.mkdir(parents=True,exist_ok=True)
    (args.evidence/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n')
    (args.evidence/'extraction.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(f"Constructing {len(recipe['operations'])} native commands",flush=True)
    design=construct(recipe,progress=lambda n,total:print(f'{n}/{total}',flush=True))
    comparison=compare(design,evidence)
    dependency.parent.mkdir(parents=True,exist_ok=True)
    if dependency.exists() and dependency.read_bytes()!=pdf:
        raise FileExistsError('Portable source dependency differs')
    dependency.write_bytes(pdf)
    published=publish(design,args.output)
    reopened=Design.model_validate_json(args.output.read_bytes())
    comparison=compare(reopened,evidence)
    result={'publication':published,'reopened':audit(reopened),'comparison':comparison,
            'source_sha256':hashlib.sha256(pdf).hexdigest(),
            'design_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}
    (dependency.parent/'publication-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(comparison),flush=True)


if __name__=='__main__':
    main()
