"""Construct a fully supported publication route through native recorded actions."""
import argparse
import hashlib
import json
from pathlib import Path

from backend.core.publication_authoring import compile_publication
from backend.core.publication_reconstruction_report import classify_reconstruction
from tools.design_archive.recorded_authoring import construct
from scripts.agent_structure_guard import publish, audit
from backend.core.models import Design


def compare(design, evidence):
    sources = {int(k):v for k,v in evidence.get('helix_sources', {}).items()}
    ids={v:sources.get(int(k), {'source_helix':int(k)})['source_helix'] for k,v in evidence['helix_ids'].items()}
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
        raise ValueError('Native directed routes differ from PDF evidence: '+str([k for k in expected.keys()|actual.keys() if expected.get(k)!=actual.get(k)][:12]))
    loops=sorted((ids[h.id],m.bp_index,m.delta) for h in design.helices for m in h.loop_skips)
    plan = evidence.get('insertion_representation', {})
    if loops!=sorted(tuple(x) for x in plan.get('duplex_insertions', evidence['insertions']['counts'])):
        raise ValueError('Native insertion counts differ from PDF evidence')
    expected_loops = sorted((x['source_helix'], x['source_bp'], x['direction'], x['length'])
                            for x in plan.get('scaffold_loops', []))
    actual_loops = sorted((ids[x.helix_id], x.bp_index, x.direction.value, x.length)
                          for s in design.strands for x in s.loops if s.is_scaffold)
    if actual_loops != expected_loops or any(s.loops for s in design.strands if not s.is_scaffold):
        raise ValueError('Native strand-owned insertion loops differ from source evidence')
    for i,path in enumerate(evidence['classified']['stap'],1):
        strand=next(s for s in design.strands if s.name==f'Staple {i}')
        if strand.sequence!=evidence.get('assigned_staple_sequences', [p['table_row']['sequence'] for p in evidence['classified']['stap']])[i-1]:
            raise ValueError('Native sequence differs from published oligo')
    from backend.core.sequences import PUBLICATION_SCAFFOLDS
    expected_scaffold=PUBLICATION_SCAFFOLDS[evidence['sequence_search']['scaffold_name']]
    offset=evidence['sequence_search']['best']['offset']
    expected_scaffold=expected_scaffold[offset:]+expected_scaffold[:offset]
    expected_scaffold=evidence.get('reconstruction_report',{}).get('scaffold_sequence_assigned',expected_scaffold)
    scaffolds=[s for s in design.strands if s.is_scaffold]
    if len(scaffolds)!=1 or scaffolds[0].sequence!=expected_scaffold:
        raise ValueError('Native scaffold sequence differs from aligned source')
    cells={int(k):v for k,v in evidence['cells'].items()}
    for key,hid in evidence['helix_ids'].items():
        if tuple(design.find_helix(hid).grid_pos)!=tuple(cells[int(key)]):
            raise ValueError('Native lattice placement differs from recorded inference')
    if design.extensions:
        raise ValueError('Unexpected terminal-extension substitution')
    expected_overhangs={tuple(b['site']) for r in evidence.get('staple_overhangs',{}).get('runs',[]) for b in r['bases']}
    actual_overhangs={(ids[d.helix_id],bp) for s in design.strands for d in s.domains if d.overhang_id
                     for bp in range(min(d.start_bp,d.end_bp),max(d.start_bp,d.end_bp)+1)}
    specs={o.id:o for o in design.overhangs}
    if any(d.overhang_id and (d.overhang_id not in specs or specs[d.overhang_id].strand_id!=s.id)
           for s in design.strands for d in s.domains):
        raise ValueError('Native overhang ownership is incomplete')
    if actual_overhangs != expected_overhangs:
        raise ValueError(f'Native overhang sites differ: missing {len(expected_overhangs-actual_overhangs)}, extra {len(actual_overhangs-expected_overhangs)}')
    if evidence.get('appearance'):
        style=evidence['appearance']
        expected_order=[evidence['helix_ids'].get(h,evidence['helix_ids'].get(str(h))) for h in style['helix_order']]
        if [h.id for h in design.helices]!=expected_order:
            raise ValueError('Native helix row order differs from the source figure')
        for i,item in enumerate(style['staple_colors'],1):
            if item['color'] and next(s for s in design.strands if s.name==f'Staple {i}').color!=item['color']:
                raise ValueError('Native staple color differs from source appearance evidence')
    derived = len(evidence.get('derived_staples', []))
    return {'routes':len(expected),'insertions':len(loops)+len(actual_loops),'strand_owned_loops':len(actual_loops),'published_staples':len(expected)-1-derived,
            'derived_staples':derived,
            'scaffold_sequence_matches':True,'source_scaffold_bases':len(expected_scaffold),
            'native_helices':len(design.helices),
            'native_reference_consulted':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--diagram-page',type=int,required=True)
    parser.add_argument('--table-page',type=int,required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--continuous-staples', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--periodic-staple-seams', action=argparse.BooleanOptionalAction, default=True,
                        help='Classify end-to-end same-helix scaffold-extrema joins as polymerization seams')
    parser.add_argument('--expected-existing-sha256')
    parser.add_argument('--allow-partial', action=argparse.BooleanOptionalAction, default=True)
    args=parser.parse_args()
    if args.output.exists() and hashlib.sha256(args.output.read_bytes()).hexdigest() != args.expected_existing_sha256:
        raise FileExistsError('Replacement requires the exact existing design hash')
    pdf=args.pdf.read_bytes()
    dependency=args.output.parent/'.provenance'/args.name/args.pdf.name
    relative='Shared Designs/'+dependency.relative_to(args.output.parent).as_posix()
    recipe,evidence=compile_publication(pdf,diagram_page=args.diagram_page,table_page=args.table_page,
        name=args.name,source_path=relative, continuous_staples=args.continuous_staples,
        periodic_staple_seams=args.periodic_staple_seams, allow_partial=args.allow_partial)
    recipe['execution_code']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in [
        'backend/core/publication_authoring.py','backend/core/publication_insertion_loops.py','backend/core/strand_loops.py','backend/core/publication_routing.py',
        'backend/core/publication_sequence_search.py','backend/core/publication_unpaired_scaffold.py','backend/core/publication_auxiliary_placement.py','backend/core/publication_ligation_placement.py','backend/core/publication_native_tracks.py',
        'tools/design_archive/recorded_authoring.py','backend/core/publication_precursors.py',
        'backend/core/publication_missing_staples.py','backend/core/publication_lattice_insets.py',
        'backend/core/publication_base_labels.py','backend/core/publication_staple_overhangs.py',
        'backend/core/publication_base_conflicts.py','backend/core/publication_route_search.py','backend/core/publication_appearance.py',
        'backend/core/scaffold_gap_overhangs.py','backend/api/part_strand_patch.py','backend/core/lattice.py',
        'backend/core/publication_vector_panels.py','backend/core/publication_diagram_labels.py',
        'backend/core/publication_reconstruction_report.py','backend/core/sequences.py',
        'backend/core/m13mp18.txt','backend/core/p7560.txt','backend/core/p7704.txt','backend/core/p8064.txt',
        'backend/core/p8634.txt','backend/core/p8634.source.json','backend/core/pegfp.txt','backend/core/pegfp.source.json']}
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
    published=publish(design,args.output,expected_existing_sha256=args.expected_existing_sha256)
    reopened=Design.model_validate_json(args.output.read_bytes())
    comparison=compare(reopened,evidence)
    result={'publication':published,'reopened':audit(reopened),'comparison':comparison,
            'source_sha256':hashlib.sha256(pdf).hexdigest(),
            'design_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}
    report = evidence['reconstruction_report']
    report['verification'] = result
    report['classification'] = classify_reconstruction(report, native_file=args.output.name)
    (dependency.parent/'reconstruction-report.json').write_text(json.dumps(report,indent=2)+'\n')
    args.output.with_suffix('.reconstruction.json').write_text(json.dumps(report,indent=2)+'\n')
    (dependency.parent/'publication-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    for filename, digest in recipe['execution_code'].items():
        data = Path(filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Construction code changed during execution: '+filename)
        snapshot = dependency.parent/'code'/filename
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        snapshot.write_bytes(data)
    (dependency.parent/'construction-code.json').write_text(json.dumps(recipe['execution_code'],indent=2)+'\n')
    print(json.dumps(comparison),flush=True)


if __name__=='__main__':
    main()
