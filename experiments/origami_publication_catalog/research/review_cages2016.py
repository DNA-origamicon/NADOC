"""Review three qualifying enzyme-cage architectures and retain recipe conflicts."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
    key='10.1038/ncomms10619';run='SEQ0003-followup'
    xml=L.ROOT/'assets/sources/PMC4749968.xml'
    si=L.ROOT/'assets/sources/pre2020-expansion/supplements/PMC4749968-41467_2016_BFncomms10619_MOESM965_ESM.pdf'
    em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4749968/fullTextXML','Results encapsulation strategy and SH/SS/DS density comparison; Methods cage construction and enzyme assembly. Full activity/kinetics audit not performed.')
    es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fncomms10619/MediaObjects/41467_2016_BFncomms10619_MOESM965_ESM.pdf','Figure1/7/60/61 captions PDF1/7/60/61; Figure60 PDF60 visually inspected. Note4 PDF69-103 staple/linker/probe headings and rows indexed; probe lists PDF80/91-92/103 inspected. Full base-by-base audit pending.')
    pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f')
    sections={};section=None
    for i in range(68,103):
        for line in pages[i].split('\n'):
            stripped=line.strip()
            if stripped.startswith('Sequences of staple strands') or stripped in ['AB-Linker strands','SS-linker strands','DS-linker strands'] or stripped.startswith(('SH-probe strands.','SS-probes.','DS-probes.')):
                section=stripped.split('. ')[0];sections.setdefault(section,[])
            m=re.match(r'^\s*(\d+\[\d+\])\s+([ACGT][ACGT ]*)$',line)
            if m and section:sections[section].append(dict(position=m[1],first_line_sequence=m[2].replace(' ',''),pdf_page=i+1))
    cores=[(name,rows) for name,rows in sections.items() if name.startswith('Sequences')]
    assert len(cores)==6 and all(len(rows)>=100 for _,rows in cores)
    assert len(sections['AB-Linker strands'])==24
    L.atomic(L.HERE/'cages2016_source_index.json',json.dumps(dict(evidence=es,sections=sections,counts={n:len(v) for n,v in sections.items()},limitations='Position/first-line inventory; continued sequence lines omitted from this index. Not complete synthesis lists. Probe labels/amounts and linker counts vary; no automatic repair or pooling across half-cages.'),indent=2)+'\n')
    common=('Two M13mp18 half-cages assemble into one full cage; half-cages retained as components rather than counted as six unrelated designs. '
            'SH main dimensions54x27x26nm and inner cavity20x20x17nm; main reports24bridging strands. '
            'SI has separate SH/SS/DS left/right staple pools, linker pools and enzyme-probe replacements. '
            'Capture-probe discrepancy: Results says two anchor probes, Methods four per half, SI lists three left and three right probes per family. '
            'Open-/closed-wall variants in Figure7 and protein cargo changes require mapping; not counted as extra cores. Complete recipes unverified.')
    notes={'SH':'Single-layer honeycomb walls, approximately2-3nm pores; Figure1 explicitly honeycomb.', 'SS':'Single-layer square walls, approximately0.5-1nm pores; Figure60 explicitly square, wall arrangement visually inspected.', 'DS':'Double-layer square walls; Figure61 explicitly square; separate source pools from SS.'}
    checks=['Reconcile two/four/three capture-probe statements and exact experimental recipes without guessing.', 'Verify all half-cage strands, linkers, probe replacements and scaffold coverage against source images.', 'Map open-/closed-wall controls and cargo conditions to specific strand subsets; preserve core/assembly distinction.', 'Confirm prior-design relationships and native files; detailed geometry eligibility beyond stated lattice remains unresolved.']
    p=next(x for x in L.read('publication_reviews') if x['registry_key']==key)
    p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',rationale=common+' '+str(notes),reviewer='Codex targeted cage/source review',run_id=run,date=L.DATE,access='main_XML_and_SI_PDF_available',unresolved_questions=checks)
    for e in [em,es]:
        if e not in p['evidence']:p['evidence'].append(e)
    root=E.parse(xml).getroot();pd=root.find('.//article-meta/pub-date')
    if pd is not None and pd.findtext('day'):p['date_evidence']=dict(date=f"{pd.findtext('year')}-{pd.findtext('month').zfill(2)}-{pd.findtext('day').zfill(2)}",primary_verified=True,source=em,meaning='Deposited XML publication date')
    L.upsert('publication_reviews',p,'Distinguish three cage architectures and preserve recipe discrepancy')
    for did,name in [('RDE0086','SH'),('RDE0087','SS'),('RDE0088','DS')]:
        old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or old['publication_keys']==[key]
        L.upsert('design_evidence',dict(design_id=did,publication_keys=[key],named_objects=[name+' enzyme nanocage',name+' left/right half-cage components and linker/probe variants'],identity_status='Distinct reported cage architecture; exact variant/parent reconciliation pending',core_variant_composition=notes[name]+' '+common,lattice_decision=notes[name]+' Narrow catalog geometry audit remains open.',source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility='unresolved',review_stage='source_reviewed',run_id=run,review_run=run,date=L.DATE,legacy_record={},relationships=[],variant_links=[],outstanding_checks=checks),'Record architecture family without multiplying cargo/assembly states')
    refs=root.findall('.//ref-list/ref')
    for r in refs:
        rid=r.get('id');doi=r.find('.//pub-id[@pub-id-type="doi"]');link=r.find('.//ext-link[@ext-link-type="doi"]')
        target=doi.text.lower() if doi is not None else link.get('{http://www.w3.org/1999/xlink}href').lower() if link is not None else 'citation:cages2016:'+rid
        L.upsert('discovery_edges',dict(edge_id='CAGES2016:'+rid,source_key=key,target_key=target,relation='cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XML reference '+rid,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retain bibliography for qualifying source')
    print(json.dumps(dict(section_counts={n:len(v) for n,v in sections.items()},references=len(refs),validation=L.validate())))
if __name__=='__main__':main()
