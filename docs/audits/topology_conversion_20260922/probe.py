"""Read-only audit probes. No app server, native engines, or user files mutated.

Run from repository root:
  .venv/bin/python docs/audits/topology_conversion_20260922/probe.py > /tmp/nadoc-topology-audit.json
These observations are not production guards or a replacement test suite.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.core.models import (Crossover, Design, Direction, Domain, ForcedLigation,
                                HalfCrossover, LatticeType, LoopSkip, Strand, StrandType)
from backend.core.lattice import make_bundle_design
from backend.core.lattice import make_autobreak, make_merge_short_staples
from backend.core.validator import validate_design
from backend.core.seamed_router import (auto_scaffold_seamed, auto_scaffold_matched,
                                       auto_scaffold_seamed_bounded, _place_xover)
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.crossover_positions import validate_crossover, crossover_neighbor
from backend.core.scadnano import import_scadnano, export_scadnano
from backend.core.cadnano import import_cadnano, export_cadnano, check_cadnano_compatibility
from backend.core.sequences import domain_bp_range, strand_sequence_length
from backend.core.scaffold_reset import reset_scaffold_to_structure
from backend.core.polymer_router import route_for_polymerization

ROWS = []

def record(name, fn):
    try:
        ROWS.append({"case": name, "result": fn()})
    except Exception as exc:
        ROWS.append({"case": name, "exception": type(exc).__name__, "message": str(exc)[:400]})

def bundle(lattice=LatticeType.HONEYCOMB, length=84):
    return make_bundle_design([(0,0),(0,1),(1,0),(1,1)], length_bp=length, lattice_type=lattice)

def occupied(d):
    slots = defaultdict(list)
    skips = {(h.id, ls.bp_index) for h in d.helices for ls in h.loop_skips if ls.delta == -1}
    for si, s in enumerate(d.strands):
        if s.is_reference:
            continue
        for di, dm in enumerate(s.domains):
            for bp in domain_bp_range(dm):
                if (dm.helix_id, bp) not in skips:
                    slots[(dm.helix_id, bp, dm.direction.value)].append((si, di, s.strand_type.value))
    return slots

def summary(d):
    report = validate_design(d)
    collisions = [(key, val) for key, val in occupied(d).items() if len(val)>1]
    return {"validator_passed": report.passed,
            "errors": [r.message for r in report.results if not r.ok][:5],
            "strands": len(d.strands), "crossovers": len(d.crossovers),
            "active_scaffolds": sum(s.is_scaffold and not s.is_reference for s in d.strands),
            "forced_ligations": len(d.forced_ligations),
            "domain_nt": sum(len(v) for v in occupied(d).values()),
            "collision_slots": len(collisions), "collision_examples": collisions[:2]}

ROUTERS = {"seamed": auto_scaffold_seamed, "matched": auto_scaffold_matched,
           "bounded": auto_scaffold_seamed_bounded, "seamless": auto_scaffold_seamless}

def route_case(lattice, router, obstacle_type=None, reference=False, opposite=False):
    d = bundle(lattice, 168)
    if obstacle_type is not None:
        h = next(h for h in d.helices if h.grid_pos==(0,1))
        direction = Direction.FORWARD if opposite else Direction.REVERSE
        start, end = (-9,-4) if opposite else (-4,-9)
        obstacle = Strand(id="audit_obstacle", strand_type=obstacle_type, is_reference=reference,
                          domains=[Domain(helix_id=h.id,start_bp=start,end_bp=end,direction=direction)])
        d = d.copy_with(strands=[*d.strands,obstacle])
    before = summary(d)
    out, result = router(d)
    return {"before":before,"after":summary(out),"warnings":result.warnings[:8]}

for lat in (LatticeType.HONEYCOMB,LatticeType.SQUARE):
    for name, router in ROUTERS.items():
        record(f"route/{lat.value}/{name}/clean", lambda l=lat,r=router:route_case(l,r))
        for st in (StrandType.LINKER,StrandType.OH_BINDER,StrandType.STAPLE):
            record(f"route/{lat.value}/{name}/{st.value}",lambda l=lat,r=router,s=st:route_case(l,r,s))
        record(f"route/{lat.value}/{name}/reference",lambda l=lat,r=router:route_case(l,r,StrandType.LINKER,True))
        record(f"route/{lat.value}/{name}/opposite",lambda l=lat,r=router:route_case(l,r,StrandType.LINKER,False,True))

def validator_case(kind):
    d = bundle()
    s = d.strands[0]
    dm = s.domains[0]
    if kind == "duplicate_strand_occupancy":
        d.strands.append(s.model_copy(update={"id":"duplicate"}))
    elif kind == "scaffold_self_overlap":
        s.domains.append(dm.model_copy())
    elif kind == "reversed_bounds":
        dm.start_bp, dm.end_bp = dm.end_bp, dm.start_bp
    elif kind == "missing_crossover_helix":
        d.crossovers.append(Crossover(half_a=HalfCrossover(helix_id="missing-a",index=10,strand=Direction.FORWARD),
                                      half_b=HalfCrossover(helix_id="missing-b",index=10,strand=Direction.REVERSE)))
    elif kind == "orphan_forced_ligation":
        d.forced_ligations.append(ForcedLigation(three_prime_helix_id="missing-a",three_prime_bp=10,
            three_prime_direction=Direction.FORWARD,five_prime_helix_id="missing-b",five_prime_bp=10,
            five_prime_direction=Direction.REVERSE))
    elif kind in ("missing_junction_records","duplicate_crossover_record"):
        d,_ = auto_scaffold_seamed(d)
        if kind == "missing_junction_records":
            d.crossovers=[]
        else:
            d.crossovers.append(d.crossovers[0].model_copy(update={"id":"duplicate-record"}))
    elif kind in ("insertion_correct_sequence","insertion_short_sequence"):
        h = next(h for h in d.helices if h.id==dm.helix_id)
        h.loop_skips=[LoopSkip(bp_index=10,delta=1)]
        n=strand_sequence_length(d,s)
        s.sequence="A"*(n if kind=="insertion_correct_sequence" else n-1)
        return {**summary(d),"expected_sequence_length":n,"actual_sequence_length":len(s.sequence)}
    # Revalidate via the public Pydantic model to check these are not solely a model_copy bypass.
    d=Design.model_validate(d.model_dump())
    return summary(d)

for kind in ("duplicate_strand_occupancy","scaffold_self_overlap","reversed_bounds",
             "missing_crossover_helix","orphan_forced_ligation","missing_junction_records",
             "duplicate_crossover_record","insertion_correct_sequence","insertion_short_sequence"):
    record("validator/"+kind,lambda k=kind:validator_case(k))

def empty_xover():
    d=bundle()
    h0,h1=d.helices[:2]
    bp=next(bp for bp in range(200,300) if any(crossover_neighbor(d.lattice_type,*h0.grid_pos,bp,is_scaffold=s)==h1.grid_pos for s in (True,False)))
    a=HalfCrossover(helix_id=h0.id,index=bp,strand=Direction.FORWARD)
    b=HalfCrossover(helix_id=h1.id,index=bp,strand=Direction.REVERSE)
    return {"bp":bp,"helper_error":validate_crossover(d,a,b)}
record("crossover/absent_nucleotides",empty_xover)

def rejected_xover():
    d=bundle()
    a=HalfCrossover(helix_id=d.helices[0].id,index=20,strand=Direction.FORWARD)
    b=HalfCrossover(helix_id=d.helices[1].id,index=21,strand=Direction.REVERSE)
    warnings=[]
    out,xo=_place_xover(d,a,b,20,20,"audit",warnings)
    return {"before":summary(d),"after":summary(out),"crossover_created":xo is not None,"warnings":warnings}
record("crossover/rejection_preserves_nicks",rejected_xover)

def sc_payload():
    return {"version":"0.19.0","grid":"square",
            "helices":[{"idx":0,"grid_position":[0,0],"max_offset":16},
                       {"idx":1,"grid_position":[0,1],"max_offset":16}],
            "strands":[{"is_scaffold":True,"domains":[
                {"helix":0,"forward":True,"start":0,"end":8},
                {"helix":1,"forward":False,"start":0,"end":8}]}]}

def sc_case(kind):
    p=sc_payload()
    strand=p["strands"][0]
    if kind=="loopout":
        strand["domains"].insert(1,{"loopout":3})
        strand["sequence"]="AAAAAAAA"+"TTT"+"CCCCCCCC"
    elif kind=="conflicting_insertions":
        strand["domains"][0]["insertions"]=[[3,1]]
        p["strands"].append({"domains":[{"helix":0,"forward":False,"start":0,"end":8,"insertions":[[3,2]]}]})
    elif kind=="duplicate_helix_index":
        p["helices"][1]["idx"]=0
        strand["domains"]=strand["domains"][:1]
    elif kind=="unknown_grid":
        p["grid"]="invalid-grid"
    elif kind=="empty_domain":
        strand["domains"][0]["end"]=0
    elif kind=="circular_scaffold":
        strand["circular"]=True
    elif kind=="circular_staple":
        p["strands"].append({"circular":True,"domains":[{"helix":0,"forward":False,"start":0,"end":8}]})
    d,w=import_scadnano(p)
    return {**summary(d),"warnings":w,"sequences":[s.sequence for s in d.strands],
            "extra_bases":[x.extra_bases for x in [*d.crossovers,*d.forced_ligations]],
            "loop_skips":[[ls.model_dump() for ls in h.loop_skips] for h in d.helices],
            "lattice":d.lattice_type.value}
for kind in ("clean","loopout","conflicting_insertions","duplicate_helix_index","unknown_grid","empty_domain","circular_scaffold","circular_staple"):
    record("scadnano/"+kind,lambda k=kind:sc_case(k))

def export_extras(fmt):
    d,_=auto_scaffold_seamed(bundle())
    d.crossovers[0].extra_bases="TT"
    if fmt=="scadnano":
        p=export_scadnano(d); out,w=import_scadnano(p)
    else:
        p=export_cadnano(d); out,w=import_cadnano(p)
    return {"input_extra_nt":2,"restored_extra_nt":sum(len(x.extra_bases or "") for x in [*out.crossovers,*out.forced_ligations]),
            "compatibility":check_cadnano_compatibility(d) if fmt=="cadnano" else None,"import_warnings":w}
for fmt in ("cadnano","scadnano"):
    record("export/extra_bases/"+fmt,lambda f=fmt:export_extras(f))

def cad_case(kind):
    p=export_cadnano(bundle())
    v=p["vstrands"][0]; arr=v["scaf"]; n=v["num"]
    if kind=="nonreciprocal":
        arr[2][0:2]=[-1,-1]
    elif kind=="same_helix_jump":
        arr[2][2:4]=[n,5]; arr[5][0:2]=[n,2]
        arr[3]=[-1,-1,-1,-1]; arr[4]=[-1,-1,-1,-1]
    elif kind=="circular_scaffold":
        arr[0][0:2]=[n,83]; arr[83][2:4]=[n,0]
    elif kind=="bad_target":
        arr[2][2:4]=[999,5]
    d,w=import_cadnano(p)
    return {**summary(d),"warnings":w,"first_scaffold_domains":[dm.model_dump() for s in d.strands if s.is_scaffold for dm in s.domains][:2]}
for kind in ("clean","nonreciprocal","same_helix_jump","circular_scaffold","bad_target"):
    record("cadnano/"+kind,lambda k=kind:cad_case(k))

def extension_probe(lat,router,side,st):
    base=bundle(lat,168)
    clean,_=router(base.model_copy(deep=True))
    original=occupied(base)
    new=[k for k,v in occupied(clean).items() if k not in original and any(t=="scaffold" for _,_,t in v)
         and (k[1]<0 if side=="low" else k[1]>=168)]
    if not new:
        return {"not_applicable":"clean route adds no scaffold slots on this face"}
    hid,bp,dr=sorted(new)[len(new)//2]
    strand=Strand(id="audit_discovered_obstacle",strand_type=st,
                  domains=[Domain(helix_id=hid,start_bp=bp,end_bp=bp,direction=Direction(dr))])
    base=base.copy_with(strands=[*base.strands,strand])
    out,result=router(base)
    return {"obstacle_slot":[hid,bp,dr],"after":summary(out),"warnings":result.warnings[:5]}
for lat in (LatticeType.HONEYCOMB,LatticeType.SQUARE):
    for name,router in ROUTERS.items():
        for side in ("low","high"):
            for st in (StrandType.LINKER,StrandType.OH_BINDER):
                record(f"extension/{lat.value}/{name}/{side}/{st.value}",
                       lambda l=lat,r=router,sd=side,s=st:extension_probe(l,r,sd,s))

def reset_case(kind):
    d=bundle()
    if kind=="mixed_supported_unpaired_helix":
        a,b=d.helices[:2]
        bp=max(bp for bp in range(84) if any(
            crossover_neighbor(d.lattice_type,*a.grid_pos,bp,is_scaffold=sc)==b.grid_pos or
            crossover_neighbor(d.lattice_type,*b.grid_pos,bp,is_scaffold=sc)==a.grid_pos
            for sc in (True,False)))
        d=bundle(length=bp+1)
        h1=d.helices[1].id
        s0,s1=[s for s in d.strands if s.is_scaffold][:2]
        s0.domains.extend(s1.domains)
        d.strands=[s for s in d.strands if s.id!=s1.id and not (s.strand_type==StrandType.STAPLE and s.domains[0].helix_id==h1)]
        # Model an existing cross-helix transition at a valid lattice site.
        a,b=s0.domains
        d.crossovers=[Crossover(half_a=HalfCrossover(helix_id=a.helix_id,index=a.end_bp,strand=a.direction),
                                half_b=HalfCrossover(helix_id=b.helix_id,index=b.start_bp,strand=b.direction),process_id="manual")]
    elif kind=="scaffold_gap":
        s=next(s for s in d.strands if s.is_scaffold)
        dm=s.domains[0]
        s.domains=[Domain(helix_id=dm.helix_id,start_bp=0,end_bp=20,direction=dm.direction)]
        d.strands.append(Strand(id="second_fragment",strand_type=StrandType.SCAFFOLD,
                                domains=[Domain(helix_id=dm.helix_id,start_bp=30,end_bp=83,direction=dm.direction)]))
    elif kind=="assigned_sequences":
        for s in d.strands:
            s.sequence="A"*strand_sequence_length(d,s)
    before=summary(d)
    old_scaf=sum(len(s.sequence or "") for s in d.strands if s.is_scaffold)
    out,w=reset_scaffold_to_structure(d)
    return {"before":before,"after":summary(out),"warnings":w,
            "assigned_scaffold_bases_before":old_scaf,
            "assigned_scaffold_bases_after":sum(len(s.sequence or "") for s in out.strands if s.is_scaffold)}
for kind in ("mixed_supported_unpaired_helix","scaffold_gap","assigned_sequences"):
    record("reset/"+kind,lambda k=kind:reset_case(k))

def polymer_roundtrip(fmt):
    d,_=auto_scaffold_seamed(bundle())
    d,result=route_for_polymerization(d)
    exporter,importer=(export_cadnano,import_cadnano) if fmt=="cadnano" else (export_scadnano,import_scadnano)
    out,w=importer(exporter(d))
    return {"before":summary(d),"after":summary(out),"route_warnings":result.warnings,
            "import_warnings":w,"periodic_records_before":sum(x.is_periodic_seam for x in d.forced_ligations),
            "periodic_records_after":sum(x.is_periodic_seam for x in out.forced_ligations)}
for fmt in ("cadnano","scadnano"):
    record("polymer_roundtrip/"+fmt,lambda f=fmt:polymer_roundtrip(f))

def ordinary_roundtrip(fmt):
    d,_=auto_scaffold_seamed(bundle())
    exporter,importer=(export_cadnano,import_cadnano) if fmt=="cadnano" else (export_scadnano,import_scadnano)
    out,w=importer(exporter(d))
    return {"before":summary(d),"after":summary(out),"import_warnings":w}
for fmt in ("cadnano","scadnano"):
    record("ordinary_roundtrip/"+fmt,lambda f=fmt:ordinary_roundtrip(f))

def staple_control(fn,stype,reference):
    d=bundle()
    obstacle=Strand(id="protected",strand_type=stype,is_reference=reference,
        domains=[Domain(helix_id=d.helices[0].id,start_bp=-13,end_bp=-30,direction=Direction.REVERSE)])
    d.strands.append(obstacle)
    original=obstacle.model_dump()
    out=fn(d)
    if isinstance(out,tuple): out=out[0]
    after=next((s for s in out.strands if s.id=="protected"),None)
    return {"protected_unchanged":after is not None and after.model_dump()==original,"after":summary(out)}
for name,fn in (("autobreak",make_autobreak),("merge",make_merge_short_staples)):
    for st,ref in ((StrandType.LINKER,False),(StrandType.OH_BINDER,False),(StrandType.STAPLE,True)):
        record(f"staple_control/{name}/{st.value}/reference={ref}",lambda f=fn,s=st,r=ref:staple_control(f,s,r))

def auto_crossover_case(kind):
    # Pure builder only: importing the API module does not launch its server/lifespan.
    from backend.api.crud import _place_auto_crossovers
    from backend.core.crossover_positions import all_valid_crossover_sites
    d=bundle()
    if kind=="reference_staples":
        for s in d.strands:
            if s.strand_type==StrandType.STAPLE: s.is_reference=True
        original=[s.model_dump() for s in d.strands if s.is_reference]
    elif kind=="deleted_sites":
        by_h=defaultdict(set)
        for site in all_valid_crossover_sites(d):
            for key in ("helix_a_id","helix_b_id"):
                by_h[site[key]].add(site["index"])
        for h in d.helices:
            h.loop_skips=[LoopSkip(bp_index=bp,delta=-1) for bp in sorted(by_h[h.id])]
    out=d
    passes=[]
    for _ in range(12):
        out,stats=_place_auto_crossovers(out)
        passes.append(stats)
        if stats["placed"]==0: break
    result={"after":summary(out),"passes":passes}
    if kind=="reference_staples":
        result["reference_strands_unchanged"]=[s.model_dump() for s in out.strands if s.is_reference]==original
    elif kind=="deleted_sites":
        result["crossovers_on_deleted_sites"]=sum(any(half.index in by_h[half.helix_id] for half in (xo.half_a,xo.half_b)) for xo in out.crossovers)
    return result
for kind in ("clean","reference_staples","deleted_sites"):
    record("auto_crossover/"+kind,lambda k=kind:auto_crossover_case(k))

def fixture_route(filename,router):
    path=ROOT/"tests"/"fixtures"/filename
    if not path.exists():
        return {"not_available":str(path.relative_to(ROOT))}
    d=Design.model_validate_json(path.read_text())
    out,result=router(d.model_copy(deep=True))
    before_slots=set(occupied(d)); after_slots=set(occupied(out))
    return {"before":summary(d),"after":summary(out),"lost_original_slots":len(before_slots-after_slots),
            "warnings":result.warnings[:8]}
for filename in ("teeth.nadoc","10-6-10hb_seamed.nadoc"):
    for name,router in (("seamed",auto_scaffold_seamed),("seamless",auto_scaffold_seamless)):
        record(f"fixture/{filename}/{name}",lambda f=filename,r=router:fixture_route(f,r))

print(json.dumps({"scope":"synthetic in-memory probes; no native simulation or UI",
                  "cases":ROWS},indent=2))
