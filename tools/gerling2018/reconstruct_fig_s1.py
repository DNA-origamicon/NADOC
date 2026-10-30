"""Recover Fig. S1 directly from its PDF vectors and verify the entire staple list.

Run from the repository root with .venv/bin/python. Scientific outputs go to
the mounted Archive. No source design, phase constant or production code changes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
ARCHIVE = Path('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018')
DEFAULT_OUT = ROOT/'.development-artifacts/gerling2018_trace_reconstruction_20261027'
SOURCE = ROOT/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc'
NAME = 'Gerling2018_FigS1_p7560_SEQUENCE_RECONSTRUCTED'


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2)+'\n')


def csv_rows(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_pdf(pdf_path, spacing=2.02):
    import pymupdf
    with pymupdf.open(pdf_path) as document:
        drawings = document[2].get_drawings()
    gray = [d for d in drawings if d['color'] and .53<d['color'][0]<.54]
    blue = [d for d in drawings if d['color'] and abs(d['color'][0])<1e-6
            and abs(d['color'][1]-.4)<1e-5 and abs(d['color'][2]-.8)<1e-5]
    assert len(gray)==213 and len(blue)==1
    rows = sorted({round(p.y,3) for d in gray for it in d['items'] for p in (it[1],it[-1])})
    assert len(rows)==42
    row_for = lambda y: min(range(42),key=lambda i:abs(rows[i]-y))
    # The first blue run goes from the scaffold break towards the left face.
    first = next(it for it in blue[0]['items'] if it[0]=='l' and abs(it[1].x-it[-1].x)>.01)
    assert row_for(first[1].y)==41 and first[1].x>first[-1].x
    origin_x, origin_bp = first[-1].x, -5
    continuous_bp = lambda x:(x-origin_x)/spacing+origin_bp
    bp = lambda x:round(continuous_bp(x))
    walk, scaffold_domains, tail_lines = [], [], []
    for i,it in enumerate(blue[0]['items']):
        if it[0]!='l' or abs(it[1].x-it[-1].x)<.01:
            continue
        a,b = it[1],it[-1]
        h = row_for(a.y)
        if abs(rows[h]-a.y)>3:
            tail_lines.append({'pdf_item':i,'x_start':a.x,'x_end':b.x,
                               'drawn_length_inferred_nt':round(abs(b.x-a.x)/spacing)+1})
            continue
        start,end = bp(a.x),bp(b.x)
        step = 1 if start<=end else -1
        scaffold_domains.append({'helix_label':str(h),'start_bp':start,'end_bp':end,
                                  'first_scaffold_index_0based':len(walk),'pdf_item':i})
        walk.extend((h,k) for k in range(start,end+step,step))
    assert len(walk)==len(set(walk))==7494 and len(scaffold_domains)==83
    assert len(tail_lines)==1 and tail_lines[0]['drawn_length_inferred_nt']==66
    bounds = {h:(min(b for a,b in walk if a==h),max(b for a,b in walk if a==h)) for h in range(42)}
    paths = []
    for pi,d in enumerate(gray):
        items = d['items']
        curves = {j:bp(it[1].x) for j,it in enumerate(items) if it[0]=='c'}
        path = []
        for j,it in enumerate(items):
            if it[0]!='l' or abs(it[1].x-it[-1].x)<.001:
                continue
            a,b = it[1],it[-1]
            assert abs(a.y-b.y)<.01
            forward = a.x<b.x
            segment = {'path_0based':pi,'helix_label':str(row_for(a.y)),
                       'forward':forward,'xlo':min(a.x,b.x),'xhi':max(a.x,b.x),'lo':None,'hi':None}
            if j-1 in curves:
                segment['lo' if forward else 'hi'] = curves[j-1]
            if j+1 in curves:
                segment['hi' if forward else 'lo'] = curves[j+1]
            path.append(segment)
        assert len(path)==len(curves)+1
        paths.append(path)
    # Neighboring segments tile each helix. Ordinary nicks fall at the midpoint
    # of their drawn endpoints; base centers are inclusive and integer indexed.
    for h in range(42):
        segments = sorted([s for path in paths for s in path if s['helix_label']==str(h)],key=lambda s:s['xlo'])
        segments[0]['lo'],segments[-1]['hi'] = bounds[h]
        for a,b in zip(segments,segments[1:]):
            if a['hi'] is not None and b['lo'] is not None:
                assert b['lo']==a['hi']+1
            elif a['hi'] is not None:
                b['lo'] = a['hi']+1
            elif b['lo'] is not None:
                a['hi'] = b['lo']-1
            else:
                cut = round(continuous_bp((a['xhi']+b['xlo'])/2)-.5)
                a['hi'],b['lo'] = cut,cut+1
        assert all(s['lo']<=s['hi'] for s in segments)
    return {'scaffold_domains':scaffold_domains,'scaffold_walk':walk,'staple_paths':paths,
            'tail_lines':tail_lines,'helix_bounds':bounds,
            'calibration':{'pdf_points_per_base':spacing,'pdf_origin_x':origin_x,'origin_bp':origin_bp,
                           'note':'Uniform spacing; BP origin is the visible coordinate convention, not an inferred sequence offset.'}}


def match_staples(trace, scaffold, refs):
    complement = scaffold.translate(str.maketrans('ACGT','TGCA'))
    inv = {tuple(loc):i for i,loc in enumerate(trace['scaffold_walk'])}
    by_sequence = {r['sequence']:r['index'] for r in refs}
    assert len(by_sequence)==213
    records,used = [],Counter()
    for pi,path in enumerate(trace['staple_paths']):
        blocks,locations = [],[]
        for s in path:
            bps = range(s['lo'],s['hi']+1) if s['forward'] else range(s['hi'],s['lo']-1,-1)
            positions = [inv[int(s['helix_label']),b] for b in bps]
            locations.append(positions)
            blocks.append(''.join(complement[p] for p in positions))
        core = 'TT'.join(blocks)
        matches = [(by_sequence['T'*a+core+'T'*b],a,b) for a in (1,5,10) for b in (1,5,10)
                   if 'T'*a+core+'T'*b in by_sequence]
        assert len(matches)==1,(pi,matches)
        pid,left,right = matches[0]
        mapping,segments,parts = [-1]*left,[],[]
        def segment(kind,seq):
            start = 1+sum(s['length'] for s in segments)
            segments.append({'kind':kind,'start_1based':start,'end_1based':start+len(seq)-1,
                             'length':len(seq),'sequence':seq})
            parts.append(seq if kind=='paired_candidate' else '*'+seq+'*')
        segment('unpaired_T_candidate','T'*left)
        for k,(word,positions) in enumerate(zip(blocks,locations)):
            segment('paired_candidate',word)
            mapping += positions
            used.update(positions)
            if k<len(blocks)-1:
                segment('unpaired_T_candidate','TT')
                mapping += [-1,-1]
        segment('unpaired_T_candidate','T'*right)
        mapping += [-1]*right
        q = 'T'*left+core+'T'*right
        assert q==refs[pid-1]['sequence'] and len(mapping)==len(q)
        assert all(q[k]==complement[p] for k,p in enumerate(mapping) if p>=0)
        records.append({'published_id':pid,'path_0based':pi,'sequence':q,'base_i53':mapping,
                        'domains':path,'paired_block_scaffold_indices':locations,'paired_sequences':blocks,
                        'terminal_T_5prime':left,'terminal_T_3prime':right,
                        'annotation':{'annotated_sequence':''.join(parts),'segments':segments}})
    assert sorted(r['published_id'] for r in records)==list(range(1,214))
    assert set(used)==set(range(7494)) and set(used.values())=={1}
    return sorted(records,key=lambda r:r['published_id'])


def make_contactmap(records,scaffold):
    sys.path.insert(0,str(ROOT/'.development-artifacts/revnano-gerling2018'))
    from contactmap.contactutils import _reset_sc_from_st
    st = {}
    for r in records:
        mapping = r['base_i53']
        lengths = [1]
        for a,b in zip(mapping,mapping[1:]):
            if a==b==-1 or a>=0 and b>=0 and b==(a-1)%len(scaffold):
                lengths[-1] += 1
            else:
                lengths.append(1)
        st[r['published_id']-1] = {'sequence53':r['sequence'],'base_i53':mapping,
                                  'section_lengths':lengths,'num_sections':len(lengths),'section_scaffold_domain_ids':[]}
    result = [st,{p:{'base_letter':b} for p,b in enumerate(scaffold)},True]
    _reset_sc_from_st(result)
    for sid,m in st.items():
        for k,p in enumerate(m['base_i53']):
            if p>=0:
                assert result[1][p]['staple_id']==sid and result[1][p]['staple_base_id']==k
    return result


def build_design(trace,records,scaffold,output):
    from backend.core.models import Design, Domain, Strand, Crossover, HalfCrossover, StrandExtension
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.sequences import assign_staple_sequences
    from backend.core.validator import validate_design
    from backend.core.scaffold_length import scaffold_length_checks
    from backend.physics.oxdna_interface import topology_rows
    source = Design.model_validate_json(SOURCE.read_text())
    helices = [h.model_copy(deep=True) for h in source.helices]
    for i,h in enumerate(helices):
        lo,hi = trace['helix_bounds'][i]
        h.label = str(i)
        h.bp_start,h.length_bp = lo,hi-lo+1
        h.axis_start.z,h.axis_end.z = lo*BDNA_RISE_PER_BP,hi*BDNA_RISE_PER_BP
        assert not h.loop_skips and not h.native_residues
    design = Design(id='gerling2018-figs1-p7560-reconstructed',helices=helices,
                    lattice_type=source.lattice_type,lattice_frames=source.lattice_frames,
                    cluster_transforms=source.cluster_transforms)
    design.metadata.name = NAME
    design.metadata.description = (
        'Sequence-verified reconstruction of Gerling et al. 2018 Fig. S1 / Table S1 42hb (1)-(3). '
        'All213 published oligos match exactly, including junction TT and terminal T/10T. '
        'Scaffold traced directly from blue PDF path with uniform2.02 PDF points/base; '
        '7494 paired bases plus66 unpaired bases =7560. Scaffold sequence index0 at helix41 BP71. '
        'NADOC linearizes the circular scaffold; its66-nt excess segment is stored as a3-prime '
        'extension, as drawn. No physical nick is inferred. '
        'Coordinates are a lattice reconstruction, not relaxed molecular geometry. '
        '213 staple names are published IDs. Full synthesis sequences are in the accompanying '
        'published_staples.csv; Strand.sequence holds paired domains, with TT and tails stored '
        'as crossover inserts and extensions. No CPDs or simulations applied. Evidence: '+str(output))
    design.metadata.tags = ['Gerling2018','FigS1','42hb','sequence-verified','p7560','reconstruction']
    def domain(h,a,b):
        return Domain(helix_id=helices[int(h)].id,start_bp=a,end_bp=b,direction='FORWARD' if a<=b else 'REVERSE')
    sd = [domain(d['helix_label'],d['start_bp'],d['end_bp']) for d in trace['scaffold_domains']]
    scaf = Strand(id='p7560_scaffold',name='p7560 / 7494 paired + 66 unpaired',strand_type='scaffold',
                  domains=sd,sequence=scaffold[:7494],custom_scaffold_length=7560,
                  color='#0066cc',notes='Sequence start: helix41 BP71; 66-base excess is a terminal extension at helix41 BP72. Circular sequence linearized for NADOC.')
    design.strands.append(scaf)
    design.extensions.append(StrandExtension(id='p7560_excess66',strand_id=scaf.id,end='three_prime',
                                             sequence=scaffold[7494:],label='p7560 unpaired excess, indices7494–7559'))
    def crossovers(strand,extra):
        for j,(a,b) in enumerate(zip(strand.domains,strand.domains[1:])):
            assert a.helix_id!=b.helix_id and a.end_bp==b.start_bp
            design.crossovers.append(Crossover(id=f'{strand.id}_junction_{j+1}',
                half_a=HalfCrossover(helix_id=a.helix_id,index=a.end_bp,strand=a.direction),
                half_b=HalfCrossover(helix_id=b.helix_id,index=b.start_bp,strand=b.direction),
                extra_bases=extra,process_id='Gerling2018_FigS1_PDF_trace'))
    crossovers(scaf,None)
    previous = json.loads((ROOT/'analysis/gerling2018_lattice_completion_20261027/42hb13_best_contactmap.json').read_text())[0]
    for r in records:
        pid = r['published_id']
        color = '#078087' if str(pid-1) not in previous else '#9163ad' if previous[str(pid-1)]['base_i53']!=r['base_i53'] else '#668ba8'
        domains = [domain(s['helix_label'],s['lo'] if s['forward'] else s['hi'],s['hi'] if s['forward'] else s['lo']) for s in r['domains']]
        s = Strand(id=f'published_{pid:03d}',name=f'42hb (1)-(3) #{pid}',domains=domains,color=color,
                   notes=f'Exact published sequence; Fig.S1 vector path{r["path_0based"]}. Full oligo: {r["sequence"]}')
        design.strands.append(s)
        crossovers(s,'TT')
        for end,n in [('five_prime',r['terminal_T_5prime']),('three_prime',r['terminal_T_3prime'])]:
            design.extensions.append(StrandExtension(id=f'{s.id}_{end}',strand_id=s.id,end=end,sequence='T'*n,
                                                     label=f'Published {n}T terminus'))
    design = assign_staple_sequences(design)
    validation = validate_design(design)
    assert validation.passed,[dataclasses.asdict(r) for r in validation.results if not r.ok]
    lengths = scaffold_length_checks(design)
    assert lengths[0]['actual_nt']==7560 and lengths[0]['complete']
    # Independent native nucleotide walk includes real bases, TT inserts and tails.
    topology,count = topology_rows(design)
    native_sequences = defaultdict(str)
    for sid,base,n3,n5 in topology:
        native_sequences[sid] += base
    assert count==214 and native_sequences[1]==scaffold
    assert all(native_sequences[i+2]==r['sequence'] for i,r in enumerate(records))
    path = output/(NAME+'.nadoc')
    path.write_text(design.model_dump_json(indent=2)+'\n')
    loaded = Design.model_validate_json(path.read_text())
    assert validate_design(loaded).passed and topology_rows(loaded)==(topology,count)
    write_json(output/'nadoc_validation.json',{'passed':True,'scaffold_length':lengths,
        'native_walk_full_published_matches':213,'native_walk_scaffold_matches_p7560':True,
        'save_reload_topology_identical':True,'nucleotides':len(topology),'strands':count,
        'validator_checks':len(validation.results),'design_sha256':sha(path)})
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output.resolve()
    assert os.path.ismount('/media/jojo/Archive') and str(out).startswith('/media/jojo/Archive/')
    out.mkdir(parents=True,exist_ok=True)
    (out/'tmp').mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(out/'tmp')
    for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
        os.environ[k] = '1'
    import openpyxl
    scaffold = (ROOT/'backend/core/p7560.txt').read_text().strip()
    refs = json.loads((ROOT/'backend/data/gerling2018_42hb13.json').read_text())['sequences']
    wb = openpyxl.load_workbook(ARCHIVE/'aau1157_Table_S1.xlsx',data_only=True,read_only=True)
    original = {int(i):s.strip().upper() for i,s in list(wb['42hb (1)-(3)'].values)[1:] if isinstance(s,str)}
    assert all(original[r['index']]==r['sequence'] for r in refs)
    wb.close()
    hashes = {str(p):sha(p) for p in [SOURCE,ARCHIVE/'aau1157_SM.pdf',ARCHIVE/'aau1157_Table_S1.xlsx',ROOT/'backend/core/p7560.txt']}
    trace = trace_pdf(ARCHIVE/'aau1157_SM.pdf')
    records = match_staples(trace,scaffold,refs)
    write_json(out/'figure_trace.json',trace)
    write_json(out/'matched_staples.json',records)
    write_json(out/'annotations.json',[r['annotation'] for r in records])
    contact = make_contactmap(records,scaffold)
    write_json(out/'contactmap.json',contact)
    from contactmap.iohandler import write_origami_contactmap
    write_origami_contactmap(contact,str(out),'contactmap.csv',madeby='Gerling Fig.S1 vector reconstruction, all213 sequences verified')
    (out/'input.rev').write_text('# Exact Fig.S1-derived annotations; all published bases retained\nCIRCULAR\n'+scaffold+'\n'+
                                 '\n'.join(r['annotation']['annotated_sequence'] for r in records)+'\n')
    previous = json.loads((ROOT/'analysis/gerling2018_lattice_completion_20261027/42hb13_best_contactmap.json').read_text())[0]
    old_annotations = json.loads((ROOT/'analysis/gerling2018_lattice_completion_20261027/42hb13_best_annotations.json').read_text())
    rows = []
    for r in records:
        pid = r['published_id']
        old = previous.get(str(pid-1))
        rows.append({'published_id':pid,'source_path_0based':r['path_0based'],
                     'status_vs_previous':'newly_resolved' if old is None else 'unchanged' if old['base_i53']==r['base_i53'] else 'corrected',
                     'annotation_changed':old_annotations[pid-1]['annotated_sequence']!=r['annotation']['annotated_sequence'],
                     'helix_labels_in_order':' → '.join(s['helix_label'] for s in r['domains']),
                     'domain_bp_ranges':'; '.join(f"{s['lo']}–{s['hi']}" for s in r['domains']),
                     'paired_domain_lengths':';'.join(str(len(s)) for s in r['paired_sequences']),
                     'paired_nt':sum(len(s) for s in r['paired_sequences']),
                     'terminal_T_5prime':r['terminal_T_5prime'],'terminal_T_3prime':r['terminal_T_3prime'],
                     'full_sequence_5to3':r['sequence'],'annotated_sequence':r['annotation']['annotated_sequence']})
    csv_rows(out/'published_staples.csv',rows)
    csv_rows(out/'scaffold_coordinates.csv',[{'scaffold_index_0based':i,'helix_label':h,'bp':b,'scaffold_base':scaffold[i]}
                                            for i,(h,b) in enumerate(trace['scaffold_walk'])])
    design_path = build_design(trace,records,scaffold,out)
    summary = {'source_hashes':hashes,'full_published_staples_matched':213,'unique_source_paths':213,
        'paired_scaffold_bases':7494,'unpaired_scaffold_bases':66,'paired_region_coverage_percent':100.,
        'whole_scaffold_paired_percent':7494/7560*100,'missing_staples':[],'overlap_bases':0,'sequence_mismatches':0,
        'newly_resolved':[r['published_id'] for r in rows if r['status_vs_previous']=='newly_resolved'],
        'corrected_existing':[r['published_id'] for r in rows if r['status_vs_previous']=='corrected'],
        'unchanged_existing':[r['published_id'] for r in rows if r['status_vs_previous']=='unchanged'],
        'annotation_changed':[r['published_id'] for r in rows if r['annotation_changed']],
        'total_raw_staple_nt':sum(len(r['sequence']) for r in records),
        'unpaired_staple_T_nt':sum(p<0 for r in records for p in r['base_i53']),
        'staple_crossover_TT_sites':sum(len(r['domains'])-1 for r in records),
        'terminal_T_counts':dict(Counter(x for r in records for x in (r['terminal_T_5prime'],r['terminal_T_3prime']))),
        'scaffold_start':{'helix_label':'41','bp':71,'sequence_index':0},
        'scaffold_unpaired_segment':{'start_0based':7494,'end_0based_inclusive':7559,'length':66,'sequence':scaffold[7494:]},
        'scaffold_domains':len(trace['scaffold_domains']),'staple_domains':sum(len(r['domains']) for r in records),
        'helix_core_lengths':dict(Counter(b-a+1 for a,b in trace['helix_bounds'].values())),
        'new_design':str(design_path),'physical_validation':'No relaxation or folding validation; topology and all sequences agree with figure/table.'}
    write_json(out/'summary.json',summary)
    assert all(sha(Path(p))==digest for p,digest in hashes.items())
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
