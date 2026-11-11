"""Inspect photoswitch source family without counting conformational states as cores."""
import json,re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
    key='10.1038/ncomms10591';run='SEQ0003-followup'
    xml=L.ROOT/'assets/sources/pre2020-expansion/PMC4740900.xml'
    si=L.ROOT/'assets/sources/pre2020-expansion/supplements/PMC4740900-41467_2016_BFncomms10591_MOESM891_ESM.pdf'
    em=evidence(xml,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4740900/fullTextXML','Results design and switching; Methods materials/template preparation and reference14 inspected. Optical model and complete experimental replication not audited.')
    es=evidence(si,'https://static-content.springer.com/esm/art%3A10.1038%2Fncomms10591/MediaObjects/41467_2016_BFncomms10591_MOESM891_ESM.pdf','Table1 PDF18-22; annealing Table2 PDF23; template/azobenzene/folding methods PDF24. Figure3 PDF3 visually inspected. Whole routing Figure1 not independently audited.')
    pages=subprocess.check_output(['pdftotext','-layout',str(si),'-']).decode().split('\f')
    rows=[];section='shared'
    for i in range(17,22):
        for line in pages[i].split('\n'):
            if 'Right-handed structures only' in line:section='right-handed only'
            if 'Left-handed structures only' in line:section='left-handed only'
            if '"core" staple' in line:
                pair=re.search(r'(\d+\[\d+\])\s+(\d+\[\d+\])',line);assert pair
                rows.append(dict(section=section,start=pair[1],end=pair[2],pdf_page=i+1,literal_line=line.strip()))
    assert len(rows)==140 and sum(r['section']=='shared' for r in rows)==138
    handles=sum(pg.count('nanorod handle') for pg in pages[17:22]);assert handles==24
    L.atomic(L.HERE/'photoswitch2016_source_index.json',json.dumps(dict(evidence=es,core_rows=rows,nanorod_handle_entries=handles,modified_strand_source_text=pages[21],limitations='Core label inventory only. 138shared plus one RH-only and one LH-only are not140simultaneous staples. Wrapped handle sequences, X azobenzene and disulfide bonds must not be stripped to ACGT. Published p7650 scaffold designation retained literally, not corrected by assumption.'),indent=2)+'\n')
    note=('Template adopted from Kuzyk2014,10.1038/nmat4031 (reference14): two14-helix bundles,80x16x8nm each, scaffold crosses twice with8nt unfolded spacers. '
          'Main andSI specify p7650, preserved literally pending sequence identity verification. Photoswitching adds handedness-specific branches with20bp dsDNA segment and disulfide-linked Azo-ODN1/2 carrying3/4azobenzenes. '
          'Table1 contains138shared core rows plus oneRH-only and oneLH-only row,24nanorod handles, and distinct modified branch/ODN recipes. RH/LH and locked/relaxed states are grouped as variants/states, not independent new cores. '
          'Prior-core identity explicitly attributed, but exact sequence/routing equivalence and narrow lattice eligibility remain unverified.')
    checks=['Reconcile exact core and variant sequences to2014parent; do not count adopted core twice after reconciliation.', 'Verify full scaffold identity/coverage using published p7650 designation; no silent p7560 substitution.', 'Audit all modified branch sequences, disulfides, azobenzene positions, spacers and handedness-specific substitutions against images.', 'Confirm bundle packing and native-file availability; no complete source certification.']
    p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
    p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design','reused_design'],catalog_eligibility='unresolved',rationale=note,reviewer='Codex targeted photoswitch source review',run_id=run,date=L.DATE,access='main_XML_and_SI_PDF_available',unresolved_questions=checks)
    for e in [em,es]:
        if e not in p['evidence']:p['evidence'].append(e)
    root=E.parse(xml).getroot();pd=root.find('.//article-meta/pub-date[@pub-type="epub"]')
    if pd is not None:p['date_evidence']=dict(date=f"{pd.findtext('year')}-{pd.findtext('month').zfill(2)}-{pd.findtext('day').zfill(2)}",primary_verified=True,source=em,meaning='Deposited XML epub date')
    L.upsert('publication_reviews',p,'Record adopted core and photoswitch modifications separately')
    did='RDE0085';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or old['publication_keys']==[key]
    L.upsert('design_evidence',dict(design_id=did,publication_keys=[key],named_objects=['Photoswitchable two-14-helix-bundle template','RH/LH branch and AuNR-handle variants'],identity_status='Modified source family explicitly adopted from2014parent; exact core equivalence pending',core_variant_composition=note,lattice_decision='Bundle packing audit pending; seven-base routing labels alone not full lattice proof',source_files=[em,es],evidence=[em,es],source_completeness='not_verified',catalog_eligibility='unresolved',review_stage='source_reviewed',run_id=run,review_run=run,date=L.DATE,legacy_record={},relationships=[dict(relation='modified_from',publication_key='10.1038/nmat4031',evidence=em,locator='Methods template preparation; reference14')],variant_links=[],outstanding_checks=checks),'Record modified source family without asserting a novel core')
    refs=root.findall('.//ref-list/ref')
    for r in refs:
        rid=r.get('id');doi=r.find('.//pub-id[@pub-id-type="doi"]')
        target=doi.text.lower() if doi is not None else 'citation:photoswitch2016:'+rid
        L.upsert('discovery_edges',dict(edge_id='PHOTOSWITCH2016:'+rid,source_key=key,target_key=target,relation='modifies_design_from' if rid=='b14' else 'cites',citation=' '.join(r.itertext()),evidence_url=em['url'],local_file=em['local_file'],sha256=em['sha256'],locator='XML reference '+rid,reconciliation_state='pending_exact_variant_and_source_verification' if rid=='b14' else 'pending_identity_date_scope_reconciliation',run_id=run,date=L.DATE),'Retain explicit parent and full bibliography')
    print(json.dumps(dict(shared_core_rows=138,handedness_specific_core_rows=2,nanorod_handles=handles,references=len(refs),validation=L.validate())))
if __name__=='__main__':main()
