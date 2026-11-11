"""Qualifying deposition sources: new double-triangle record, existing bundle, explicit reuse."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
    key='10.1038/srep15634';run='SEQ0003-followup'
    xml=L.ROOT/'assets/sources/PMC4616047.xml'
    si=L.ROOT/'assets/sources/pre2020-expansion/supplements/PMC4616047-41598_2015_BFsrep15634_MOESM1_ESM.pdf'
    em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4616047/fullTextXML','Results DNA origami nanostructures and coating; Methods folding/preparation; references7/52. Source-design review, not a full experimental replication audit.')
    es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fsrep15634/MediaObjects/41598_2015_BFsrep15634_MOESM1_ESM.pdf','Notes2-4 PDF2-3; linker TablesS1/S2 PDF4; FigureS4 PDF5 visually inspected at whole-page scale; TablesS3/S4 PDF6-8/10-12. FigureS5 PDF9 caption only this pass. Base-by-base image audit pending.')
    pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f')
    tables=[]
    for name,a,b,expected in [('S3',5,8,163),('S4',9,12,141)]:
        rows=[]
        for i in range(a,b):
            for m in re.finditer(r'(?m)^\s*(\d+\[\d+\])\s+(\d+\[\d+\])\s+([ACGT]+)',pages[i]):
                rows.append(dict(start=m[1],end=m[2],first_line_sequence=m[3],pdf_page=i+1))
        assert len(rows)==expected and len({(r['start'],r['end']) for r in rows})==expected
        tables.append(dict(table=name,rows=rows))
    L.atomic(L.HERE/'deposition2015_source_index.json',json.dumps(dict(evidence=es,tables=tables,limitations='Row/first-line extraction only; not full sequence certification. Shared M13mp18 designation does not prove exact coverage. Additional Cy5 linker recipes must be checked independently.'),indent=2)+'\n')
    dt='Single-layer double-triangle with163staples (TableS3), M13mp18 scaffold. Methods explicitly describe square helix packing with skipped scaffold bases to compensate global twist. FigureS4 shows two connected filled triangular domains; native caDNAno used for CanDo is mentioned, but editable file not established. Flexibility/deposition conformations are not additional cores.'
    hb='Existing D024 60-helix bundle retained. TableS4 lists141staples; Methods add six separate TableS2 linkers to anchor Cy5-labelled strands. SI Note4 gives linker overhang TTTTTTCTCCTTTCCC and reporter 5-prime-Cy5-GGGAAAGGAGAAAAA-3-prime. Do not treat141as the full labelled recipe. Legacy honeycomb assessment retained, not independently revalidated in this pass.'
    reuse='Seeman tile and hexagonal tube explicitly reused from references7 and52, with sidestrands omitted to suppress stacking. Hexagonal tube uses five TableS1 linkers. Their full core lists are referred to prior papers; no additional group or complete-source claim made here.'
    checks=['Verify complete sequences and scaffold coverage against routing, including skipped bases and all modified/linker strands.', 'Reconcile double-triangle and60HB prior-template identity; native design files not acquired.', 'Map omitted sidestrands for reused Seeman tile/hexagonal tube to parent sources; no exact variant match established.']
    p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
    p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design','reused_design','uncertain'],catalog_eligibility='unresolved',rationale=dt+' '+hb+' '+reuse,reviewer='Codex targeted design/source and reuse review',run_id=run,date=L.DATE,access='main_XML_and_SI_PDF_available',unresolved_questions=checks)
    for e in [em,es]:
        if e not in p['evidence']:p['evidence'].append(e)
    root=E.parse(xml).getroot();pd=root.find('.//article-meta/pub-date')
    p['date_evidence']=dict(date=f"{pd.findtext('year')}-{pd.findtext('month').zfill(2)}-{pd.findtext('day').zfill(2)}",primary_verified=True,source=em,meaning='Deposited XML publication date')
    L.upsert('publication_reviews',p,'Review explicit source lists and distinguish reused templates')
    for did,name,note,lattice in [('D024','60-helix bundle',hb,'Legacy honeycomb decision retained; not independently revalidated this pass'),('RDE0084','Twist-corrected planar double-triangle',dt,'Square packing explicitly stated in Methods; filled planar domains in FigureS4')]:
        old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or old['publication_keys']==[key]
        d=old or dict(design_id=did,publication_keys=[key],legacy_record={},relationships=[],variant_links=[])
        d.update(named_objects=[name],identity_status='Source family; exact prior-core reconciliation pending',core_variant_composition=note,lattice_decision=lattice,source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility='eligible',review_stage='source_reviewed',run_id=run,review_run=run,date=L.DATE,outstanding_checks=checks)
        L.upsert('design_evidence',d,'Preserve D024 and record separately supported planar double-triangle')
    refs=root.findall('.//ref-list/ref')
    for r in refs:
        rid=r.get('id');doi=r.find('.//ext-link[@ext-link-type="doi"]')
        target=doi.get('{http://www.w3.org/1999/xlink}href').lower() if doi is not None else 'citation:deposition2015:'+rid
        L.upsert('discovery_edges',dict(edge_id='DEPOSITION2015:'+rid,source_key=key,target_key=target,relation='reused_design' if rid in ['b7','b52'] else 'cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XML reference '+rid,reconciliation_state='pending_exact_variant_and_source_verification' if rid in ['b7','b52'] else 'pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retain bibliography and explicitly reused templates')
    print(json.dumps(dict(table_rows=[len(t['rows']) for t in tables],references=len(refs),validation=L.validate())))
if __name__=='__main__':main()
