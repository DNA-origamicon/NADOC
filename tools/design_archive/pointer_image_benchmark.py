"""Controlled Pointer diagram benchmark. Reference and extractor stay separate.

This renders an existing reference as a visible diagram, not a new design. It is
not the published Pointer figure. The extractor worker receives only the PDF,
scaffold sequence and published staples. Validation subsequently reads the oracle.
No NADOC model is created, exported, or published.
"""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

import pymupdf

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=ROOT/'tests/fixtures/cadnano_dietz_pointer.json.gz'
STAPLES=ROOT/'tests/fixtures/dietz_pointer_2017_staples.json'


def read_paths(source,kind):
    helices={h['num']:h for h in source['vstrands']}
    starts=sorted((h['num'],i) for h in helices.values() for i,p in enumerate(h[kind]) if p[:2]==[-1,-1] and p[2:]!=[-1,-1])
    paths=[]
    for start in starts:
        walk,seen,current=[],set(),start
        while current!=(-1,-1):
            if current in seen: raise ValueError('Circular reference unsupported by this renderer.')
            walk.append(current);seen.add(current)
            h,bp=current;current=tuple(helices[h][kind][bp][2:])
        paths.append(walk)
    return paths


def render_reference(source, *, scale=3, row_pitch=24, shuffle_seed=19, fragment=True):
    """Ordinary numbered caDNAno-style diagram; no hidden route IDs or JSON."""
    numbers=sorted(h['num'] for h in source['vstrands'])
    width=max(len(h['scaf']) for h in source['vstrands'])
    x0,y0=65,65
    inset_x=x0+(width+12)*scale
    rows={num:y0+i*row_pitch for i,num in enumerate(numbers)}
    rng=random.Random(shuffle_seed)
    with pymupdf.open() as doc:
        page=doc.new_page(width=inset_x+300,height=y0+len(numbers)*row_pitch+45)
        def label(text,x,y,size=8):
            page.insert_text((x-pymupdf.get_text_length(text,fontsize=size)/2,y+size*.388),text,fontsize=size)
        label('Base index',x0+width*scale/2,15,10)
        for bp in range(0,width+1,32): label(str(bp),x0+bp*scale,35)
        for num,y in rows.items(): label(str(num),30,y)
        label('Helix',30,35)
        primitives=[]
        for kind,color,dy in [('scaf',(0,.4,.8),-4),('stap',(.5,.5,.5),4)]:
            for path in read_paths(source,kind):
                runs=[];start=0
                for i in range(1,len(path)+1):
                    if i==len(path) or path[i][0]!=path[i-1][0]:
                        a,b=path[start],path[i-1]
                        runs.append(('l',a,b))
                        if i<len(path): runs.append(('c',path[i-1],path[i]))
                        start=i
                def point(site): return (x0+site[1]*scale,rows[site[0]]+dy)
                for tag,a,b in runs:
                    if a==b: continue
                    pa,pb=point(a),point(b)
                    # Primitive orientation/order carry no biological direction.
                    if rng.random()<.5: pa,pb=pb,pa
                    primitives.append((tag,pa,pb,color))
        rng.shuffle(primitives)
        for tag,a,b,color in primitives:
            shape=page.new_shape()
            if tag=='l':
                if fragment and abs(a[0]-b[0])>6*scale:
                    mid=((a[0]+b[0])/2,a[1])
                    # Fragment only at an actual base index, never hidden metadata.
                    mid=(x0+round((mid[0]-x0)/scale)*scale,mid[1])
                    shape.draw_line(a,mid);shape.finish(color=color,width=.6,closePath=False);shape.commit()
                    shape=page.new_shape();shape.draw_line(mid,b)
                else: shape.draw_line(a,b)
            else:
                bow=scale*.4
                shape.draw_bezier(a,(a[0]+bow,a[1]+(b[1]-a[1])/3),(b[0]+bow,b[1]-(b[1]-a[1])/3),b)
            shape.finish(color=color,width=.6,closePath=False);shape.commit()
        for h in source['vstrands']:
            if any(h['loop']): raise ValueError('Benchmark renderer does not support insertion symbols.')
            for bp,delta in enumerate(h['skip']):
                if delta==-1:
                    x,y=x0+bp*scale,rows[h['num']]
                    page.draw_line((x-2,y-2),(x+2,y+2),color=(.8,0,0),width=.8)
                    page.draw_line((x-2,y+2),(x+2,y-2),color=(.8,0,0),width=.8)
        rmin=min(h['row'] for h in source['vstrands']);cmin=min(h['col'] for h in source['vstrands'])
        label('Square-lattice cross-section',inset_x+120,35,10)
        for h in source['vstrands']:
            x,y=inset_x+(h['col']-cmin)*16,80+(h['row']-rmin)*16
            page.draw_circle((x,y),7,color=(1,.7,.2),fill=(1,.7,.2))
            label(str(h['num']),x,y,7)
        return doc.tobytes(deflate=True, no_new_id=True)


def compare_routing(source,result):
    """Compare every predecessor/successor, not just strand/base counts."""
    expected={}
    for h in source['vstrands']:
        for kind in ('scaf','stap'):
            for bp,p in enumerate(h[kind]):
                if p!=[-1]*4: expected[kind,h['num'],bp]=tuple(p)
    actual={}
    for kind,paths in result.get('directed_paths',{}).items():
        for path in paths:
            for i,(h,bp) in enumerate(path):
                key=kind,h,bp
                if key in actual: raise ValueError('Recovered paths overlap.')
                previous=path[i-1] if i else [-1,-1]
                following=path[i+1] if i+1<len(path) else [-1,-1]
                actual[key]=tuple(previous)+tuple(following)
    missing=set(expected)-set(actual);extra=set(actual)-set(expected)
    incorrect=[k for k in expected.keys() & actual.keys() if expected[k]!=actual[k]]
    deletions={(h['num'],i) for h in source['vstrands'] for i,v in enumerate(h['skip']) if v==-1}
    rmin=min(h['row'] for h in source['vstrands']);cmin=min(h['col'] for h in source['vstrands'])
    lattice={str(h['num']):[h['row']-rmin,h['col']-cmin] for h in source['vstrands']}
    actual_lattice={str(k):v for k,v in result['graph']['lattice'].items()}
    indels_match=deletions=={tuple(x) for x in result['graph']['deletions']}
    lattice_match=lattice==actual_lattice
    width_match=result['graph']['width']==max(len(h['scaf']) for h in source['vstrands'])
    return {'exact_routing':not(missing or extra or incorrect),'expected_sites':len(expected),'recovered_sites':len(actual),
            'missing_sites':len(missing),'extra_sites':len(extra),'wrong_pointers':len(incorrect),
            'deletions_match':indels_match,'lattice_match_up_to_translation':lattice_match,
            'width_match':width_match,
            'matched_staples':result['best']['matched_staples'],'resolved':result['resolved'],
            'complete':not(missing or extra or incorrect) and indels_match and lattice_match and width_match and result['resolved']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    raw=gzip.decompress(REFERENCE.read_bytes());source=json.loads(raw)
    pdf=render_reference(source)
    image_path=args.output/'pointer-reference-diagram.pdf'
    image_path.write_bytes(pdf)
    # Worker has only image and sequences on stdin. It does not import this module.
    worker='''import base64,json,sys
from backend.core.diagram_route_extraction import extract_routing
from backend.core.sequences import M13MP18_SEQUENCE
p=json.load(sys.stdin)
r=extract_routing(base64.b64decode(p['pdf']),M13MP18_SEQUENCE,p['staples'])
json.dump(r,sys.stdout)
'''
    inputs={'pdf':base64.b64encode(pdf).decode(),'staples':json.loads(STAPLES.read_text())['sequences']}
    response=subprocess.run([sys.executable,'-c',worker],input=json.dumps(inputs),text=True,capture_output=True,cwd=ROOT,check=True)
    result=json.loads(response.stdout)
    report=compare_routing(source,result)
    from backend.core.sequences import M13MP18_SEQUENCE
    report.update(source_kind='controlled rendering of pinned reference, not original publication image',
                  reference_sha256=hashlib.sha256(raw).hexdigest(),image_sha256=hashlib.sha256(pdf).hexdigest(),
                  staple_input_sha256=hashlib.sha256(STAPLES.read_bytes()).hexdigest(),
                  scaffold_sequence_sha256=hashlib.sha256(M13MP18_SEQUENCE.encode()).hexdigest(),
                  extractor_code_sha256=hashlib.sha256((ROOT/'backend/core/diagram_route_extraction.py').read_bytes()).hexdigest(),
                  renderer_parameters={'scale':3,'row_pitch':24,'shuffle_seed':19,'fragment':True},
                  extractor_method=result['method'],hypotheses_tested=result['hypotheses_tested'],
                  unknown_partner_bases=result['unknown_bases'],
                  recipe='uv run python -m tools.design_archive.pointer_image_benchmark --output OUTPUT',
                  process=['Read pinned reference for rendering only','Draw visible ruler, row labels, independent reversed/shuffled primitives, deletion and lattice inset',
                           'Send only PDF and published staples to isolated extractor worker',
                           'Recover an undirected edge graph from visible coordinates, without graphic path order',
                           'Test scaffold senses/registers and each staple sense using sequences',
                           'Compare every directed site pointer, deletion and normalized lattice position against reference'])
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not report['complete']: raise SystemExit(1)


if __name__=='__main__': main()
