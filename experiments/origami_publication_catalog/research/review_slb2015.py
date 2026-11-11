"""Targeted review of the qualifying lipid-bilayer origami assembly sources."""
import json
import re
import subprocess
import xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence


def main():
    key = '10.1038/ncomms9052'
    run = 'SEQ0001-followup'
    xml = L.ROOT / 'assets/sources/PMC4560778.xml'
    si = L.ROOT / 'assets/sources/PMC4560778-41467_2015_BFncomms9052_MOESM1003_ESM.pdf'
    root = E.parse(xml).getroot()
    em = evidence(xml, 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4560778/fullTextXML',
                  'Results: cross-shaped units, surface modification and close packing; Methods; references 9/22/26/27/59/60. Targeted review, not complete article audit.')
    es = evidence(si, 'https://static-content.springer.com/esm/art%3A10.1038%2Fncomms9052/MediaObjects/41467_2015_BFncomms9052_MOESM1003_ESM.pdf',
                  'Tables 1-4 PDF28-32 inspected in layout text. Figure18 PDF25 routing image visually inspected; Figures19/20 captions PDF26/27 read. No base-by-base image verification.')
    pages = subprocess.check_output(['pdftotext', '-layout', str(si), '-']).decode().split('\f')
    labels = []
    for i in range(27, 30):
        labels.extend(dict(label=m[0], pdf_page=i+1) for m in re.finditer(
            r'\b(?:top-[A-R][1-6]|bot-[A-R][1-6]|L-[1-8][abc]|4HB[1-9]|loop[1-4])\b', pages[i]))
    assert len(labels) == len({x['label'] for x in labels}) == 215
    edge_rows = re.findall(r'(?m)^(top-[AR][1-6]-L|bot-[AR][1-6]-L)\s+([ACGTacgt]+)', pages[30])
    assert len(edge_rows) == 24 and all(s.startswith('tttt') and s.endswith('tttt') for _, s in edge_rows)
    tab3, tab4 = pages[31].split('Supplementary Table 4', 1)
    biotin4 = re.findall(r'(?m)^((?:top|bot)-[A-R][1-6] biotin)\s+(X[ACGTacgt]+)', tab3)
    periodic = re.findall(r'(?m)^((?:top|bot)-[A-R][1-6](?:’| biotin))\s+([XACGTacgt]+)', tab4)
    assert len(biotin4) == 4 and len(periodic) == 16
    assert sum(s.startswith('X') for _, s in periodic) == 8
    index = dict(evidence=es, table1_labels=labels,
                 table2_rows=[dict(label=n, literal_sequence=s) for n, s in edge_rows],
                 table3_rows=[dict(label=n, literal_sequence=s) for n, s in biotin4],
                 table4_rows=[dict(label=n, literal_sequence=s) for n, s in periodic],
                 limitations='Table1 label inventory only; not 215 verified sequences. Multiline L/4HB sequences and lowercase bases require preservation. X is biotin, not a nucleotide. No complete recipe or native-file certification.')
    L.atomic(L.HERE / 'slb2015_source_index.json', json.dumps(index, indent=2)+'\n')
    note = ('Twist-corrected cross-shaped M13mp18 origami with blunt edges forms stacking-mediated surface arrays. '
            'SI Table1 contains 215 unique labels including top/bot, linking L, 4HB and loop entries. '
            'Table2 has 24 replacement staples with T4 at both ends, giving 48 tails (12 per edge), suppressing stacking for close packing. '
            'Table3 has four biotin-labelled replacements for orientation marking. Table4 has 16 replacement entries, eight biotin-labelled and eight partners, for periodic streptavidin decoration. '
            'These are one provisional cross family with variants, not four proven unique cores. Figure18 shows connected TOP/BOTTOM routing domains and auxiliary 4HB/loop routing; exact folded packing and narrow catalog eligibility require further audit. '
            'Triangle and hexagon close-packing experiments cite Rothemund2006 and Yang2012 respectively; retain reuse leads without creating additional unverified design groups.')
    p = next(x for x in L.read('publication_reviews') if x['registry_key'] == key)
    checks = ['Verify Table1 multiline sequences against images, scaffold coverage and exact variant substitutions.',
              'Reconcile cross core with prior surface-assembly designs; determine narrow lattice eligibility from folded geometry.',
              'Resolve triangle and hexagon exact parent variants; no additional design group counted from these reuse mentions.',
              'Native design files and complete experimental sequence sets not verified.']
    p.update(review_stage='design_sources_reviewed', relevance='design_bearing',
             design_contributions=['modified_design', 'reused_design'], catalog_eligibility='unresolved',
             rationale=note, reviewer='Codex targeted source and routing review', run_id=run, date=L.DATE,
             access='main_XML_and_SI_PDF_available', unresolved_questions=checks)
    for e in [em, es]:
        if e not in p['evidence']: p['evidence'].append(e)
    pd = root.find('.//article-meta/pub-date')
    p['date_evidence'] = dict(date=f"{pd.findtext('year')}-{pd.findtext('month').zfill(2)}-{pd.findtext('day').zfill(2)}",
                              primary_verified=True, source=em, meaning='Deposited article XML publication date')
    L.upsert('publication_reviews', p, 'Review qualifying cross source and distinguish modification from reuse')
    did = 'RDE0082'
    old = next((x for x in L.read('design_evidence') if x['design_id'] == did), None)
    assert old is None or old['publication_keys'] == [key]
    L.upsert('design_evidence', dict(design_id=did, publication_keys=[key],
        named_objects=['Twist-corrected cross-shaped origami', 'T4 edge-blocking and four/eight-biotin variants'],
        identity_status='Provisional source family; novelty and prior cross-template identity unresolved',
        core_variant_composition=note, lattice_decision='Folded cross geometry and packing audit pending; array symmetry is not intradesign lattice evidence',
        source_files=[em, es], evidence=[em, es], source_completeness='not_verified', catalog_eligibility='unresolved',
        review_stage='source_reviewed', review_run=run, run_id=run, date=L.DATE, legacy_record={},
        relationships=[], variant_links=[], outstanding_checks=checks), 'Record one cross source family, preserving variant and reuse uncertainty')
    refs = root.findall('.//ref-list/ref')
    for r in refs:
        rid = r.get('id')
        doi = r.find('.//ext-link[@ext-link-type="doi"]')
        target = doi.get('{http://www.w3.org/1999/xlink}href').lower() if doi is not None else 'citation:slb2015:'+rid
        L.upsert('discovery_edges', dict(edge_id='SLB2015:'+rid, source_key=key, target_key=target,
            relation='reused_design' if rid in ['b9', 'b22'] else 'cites', citation=' '.join(r.itertext()),
            evidence_url=em['url'], local_file=em['local_file'], sha256=em['sha256'], locator='XML reference '+rid,
            reconciliation_state='pending_exact_variant_and_source_verification' if rid in ['b9', 'b22'] else 'pending_identity_date_scope_reconciliation',
            run_id=run, date=L.DATE), 'Retain qualifying paper bibliography and explicit template references')
    print(json.dumps(dict(table1_labels=len(labels), edge_replacements=len(edge_rows), references=len(refs), validation=L.validate())))


if __name__ == '__main__':
    main()
