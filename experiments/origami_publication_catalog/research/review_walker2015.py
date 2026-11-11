"""Review qualifying plasmonic walker tracks, preserving published table discrepancies."""
import collections
import json
import re
import subprocess
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence


def main():
    key='10.1038/ncomms9102'; run='SEQ0001-followup'
    xml=L.ROOT/'assets/sources/PMC4560816.xml'
    si=L.ROOT/'assets/sources/pre2020-expansion/supplements/PMC4560816-41467_2015_BFncomms9102_MOESM1085_ESM.pdf'
    em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4560816/fullTextXML','Results design/walking sections and Methods track preparation inspected; optical and chemical procedures not fully audited.')
    es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fncomms9102/MediaObjects/41467_2015_BFncomms9102_MOESM1085_ESM.pdf','Tables1/2 PDF12-20 position inventory; Table3 PDF21 functional strands; Figure7 PDF7 cross-section and Table2 PDF20 visually inspected. Figure9/11 captions read, routing not audited.')
    pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f')
    tables=[]
    for number,a,b in [(1,11,16),(2,16,20)]:
        rows=[]; section='Core staple strands'
        for i in range(a,b):
            for line in pages[i].split('\n'):
                if line.strip().startswith(('Core staple','Staple strands')): section=line.strip()
                m=re.match(r'^\s*(\d+\[\d+\])\s+(\d+\[\d+\])',line)
                if m: rows.append(dict(start=m[1],end=m[2],section=section,pdf_page=i+1))
        counts=collections.Counter((r['start'],r['end']) for r in rows)
        tables.append(dict(table=number,rows=rows,entry_count=len(rows),unique_position_pairs=len(counts),duplicate_pairs=[dict(start=a,end=b,count=n) for (a,b),n in counts.items() if n>1]))
    assert [(t['entry_count'],t['unique_position_pairs']) for t in tables]==[(210,210),(147,141)]
    L.atomic(L.HERE/'walker2015_source_index.json',json.dumps(dict(evidence=es,tables=tables,limitations='Position-pair inventory, not complete sequence extraction. Six repeated pairs in Table2; E/F duplicates confirmed in PDF20 image. Do not deduplicate silently or infer missing recipes. Wrapped sequences and chemical modifications require source verification.'),indent=2)+'\n')
    plate='42-helix two-layer plate, 58x42x7 nm, explicitly honeycomb in Methods; p7560 scaffold, T6 edge extensions. Six foothold rows A-F with five binding sites each define five walker stations. Table1 has 210 unique start/end pairs including core, stator and foothold staples. Walking stations and blocker additions are states of one track, not new core designs.'
    prism='Separate triangular-prism track, 35 nm long, cross-section side lengths about29/26/38 nm. Figure7 shows a filled helix cross-section, not a wireframe prism. Seven foothold rows A-G define six stations. Table2 has147 entries but141 distinct start/end pairs; six pairs repeat. PDF20 image confirms identical E-row69[105]-70[98] and F-row53[105]-54[98] entries repeated. No silent correction or complete-set certification. Exact lattice assignment and prior-core identity remain unresolved.'
    checks=['Audit full sequence strings, lengths, p7560 coverage and functional extensions against routing and source images.', 'Resolve Table2 repeated position pairs without guessing replacements; verify all foothold and stator recipes.', 'Reconcile prior track cores and establish triangular-prism narrow lattice eligibility; native design files unverified.']
    p=next(x for x in L.read('publication_reviews') if x['registry_key']==key)
    p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design','uncertain'],catalog_eligibility='unresolved',rationale=plate+' '+prism,reviewer='Codex targeted main/SI review with table discrepancy image check',run_id=run,date=L.DATE,access='main_XML_and_SI_PDF_available',unresolved_questions=checks)
    for e in [em,es]:
        if e not in p['evidence']:p['evidence'].append(e)
    root=E.parse(xml).getroot(); pd=root.find('.//article-meta/pub-date')
    p['date_evidence']=dict(date=f"{pd.findtext('year')}-{pd.findtext('month').zfill(2)}-{pd.findtext('day').zfill(2)}",primary_verified=True,source=em,meaning='Deposited XML publication date')
    L.upsert('publication_reviews',p,'Distinguish existing plate and separate prism; preserve published duplicate rows')
    for did,names,note,elig,lattice in [('S013',['42-helix two-layer walking track'],plate,'eligible','Methods explicitly specify honeycomb packing'),('RDE0083',['Triangular-prism plasmonic walking track'],prism,'unresolved','Filled cross-section visually supported; exact lattice audit pending')]:
        old=next((d for d in L.read('design_evidence') if d['design_id']==did),None)
        assert old is None or old['publication_keys']==[key]
        d=old or dict(design_id=did,publication_keys=[key],legacy_record={},relationships=[],variant_links=[])
        d.update(named_objects=names,identity_status='Source family; exact prior-template identity unresolved',core_variant_composition=note,lattice_decision=lattice,source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility=elig,review_stage='source_reviewed',review_run=run,run_id=run,date=L.DATE,outstanding_checks=checks)
        L.upsert('design_evidence',d,'Preserve S013 and add only the separately documented prism')
    refs=root.findall('.//ref-list/ref')
    for r in refs:
        rid=r.get('id');doi=r.find('.//ext-link[@ext-link-type="doi"]')
        target=doi.get('{http://www.w3.org/1999/xlink}href').lower() if doi is not None else 'citation:walker2015:'+rid
        L.upsert('discovery_edges',dict(edge_id='WALKER2015:'+rid,source_key=key,target_key=target,relation='cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XML reference '+rid,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retain qualifying paper bibliography without asserting exact template reuse')
    print(json.dumps(dict(table_counts=[(t['entry_count'],t['unique_position_pairs']) for t in tables],references=len(refs),validation=L.validate())))

if __name__=='__main__':main()
