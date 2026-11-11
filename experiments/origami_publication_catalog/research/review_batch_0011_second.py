"""Second source-backed B0011 pass; source completeness remains explicitly open."""
import json
import ledger as L
from review_batch_0001 import evidence

NOTES = [
('10.1021/acs.langmuir.7b01659', '9348397-la7b01659_si_001.pdf', '9348397',
 'SI pp1–3 FigsS1–S3 and preparation; staple table headings pp4,9,14 and final page19',
 'A shared DNA breadboard carries gold-nanorod seed arrangements described as rectangular, square and T-shaped structures. These labels do not establish three different origami-core outlines. FigsS1/S2/S3 describe seven capture strands per site, ten/eleven across three helices, and fourteen across four helices respectively. Preparation specifies M13mp18 and ten adenines at modified staple 3-prime ends, with modified sequences colored blue. Separate arrangement tables start pp4,9,14. Plating/CTAB conditions are not new core designs. Complete table composition, color-coded replacements and lattice/parent routing remain unverified.',
 ['Acquire main Methods and trace the breadboard parent and exact routing/lattice.', 'Compare all three sequence tables and colored modifications against attachment diagrams; do not infer core identity from seed-pattern names.']),
('10.1021/jacs.7b08087', '9442525-ja7b08087_si_001.pdf', '9442525',
 'SI p4 assembly methods; p7 TL TEM; p9 length distributions; pp10–11 scattering discussion; p12 sequence-table start and p18 table tail/references',
 'TL nanosheet preparation uses p7560 scaffold. Separately, 2H×8H and 4H×12H ribbons are assembled from equimolar short DNA strands; the inspected ribbon method does not establish scaffolded origami. Peptide/TL coassembly products and nanowire-length distributions are distinguished from core designs. The p12 TL staple table and p18 table tail were located, but intervening headers and full sequence composition remain unchecked. Dietz/Douglas/Shih Science2009 is cited for scaffold preparation and must not automatically be assigned as the exact TL-core parent. Scattering equations contain extraction artifacts and were not interpreted.',
 ['Inspect main article, intervening sequence headers and all TL design diagrams to identify core, lattice and parent.', 'Keep short-strand ribbon systems separate unless their actual design evidence establishes origami; audit TL and peptide/handle compositions separately.']),
('10.1021/acs.nanolett.7b03946', '9496861-nl7b03946_si_001.pdf', '9496861',
 'SI p2 assembly; p5 SchemeS1; p19 particle/capture strands; pp20–22 controller families; pp22–25 core-table headings; p26 references',
 'Triangular I and II origami are separately folded from M13mp18 p7249 and then mixed 1:1 into a rhomboid through sticky-end/controller connections. Thus the assembled object contains two folded scaffold units, not a single enlarged core. SchemeS1 places capture binding sites on opposite faces in an L arrangement for a gold-nanorod dimer. TriangleI polyA handles and triangleII ATA handles are distinct from thiolated particle strands. Controller tables include ordinary, disulfide SS, EcoRV EV, i-motif iM and telomere TD families; these stimulus-responsive connections are not automatically distinct core designs. Core A/B/C table headers were located but full routing/sequence compositions remain unverified. Ref1 cites Rothemund2006 as an explicit parent-method lead.',
 ['Acquire main Methods and compare triangle routing with Rothemund2006; verify per-triangle modified/core staple composition.', 'Trace each controller/capture set to its experiment and assembly connections; audit complete core tables and lattice.'])]

def main():
    pubs={p['registry_key']:p for p in L.read('publication_reviews')}
    for key,name,fid,loc,note,questions in NOTES:
        ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
        p=pubs[key]
        p.update(review_stage='design_sources_reviewed',relevance='design_bearing',publication_type=['journal_article'],design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale=note,unresolved_questions=questions,reviewer='Codex named supplement sections and table-heading inspection',run_id='B0011',date=L.DATE)
        L.upsert('publication_reviews',p,'Record inspected source distinctions without certifying complete sequence sets')
    p=pubs['10.1093/nar/gku233']
    ev=evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC4027175.xml','https://pmc.ncbi.nlm.nih.gov/articles/PMC4027175/','Abstract; entire Materials and Methods and Discussion; all Results subsection headings/opening paragraphs; Discussion refs42/43')
    p.update(review_stage='fulltext_reviewed',relevance='not_origami',publication_type=['journal_article'],design_contributions=[],catalog_eligibility='excluded',access='partial',evidence=[ev],rationale='Implemented system is a cell-free transcriptional incoherent feed-forward circuit: DNA genelet templates, activator/inhibitor strands, T7 RNA polymerase/RNaseR, and malachite-green RNA aptamer output. Results construct and characterize this circuit and model fold-change detection. Discussion mentions DNA origami refs42/43 only among available building blocks for future spatiotemporal programs/artificial cells. No origami design execution is established in inspected experimental/model sections. This is a source-supported exclusion of the article from the design census, not exclusion of its citation neighborhood.',unresolved_questions=['Reconcile all52 bibliography targets and follow origami references; supplement sequences have not been independently audited.'],reviewer='Codex primary XML section inspection with same-agent second Results pass',run_id='B0011',date=L.DATE)
    L.upsert('publication_reviews',p,'Record non-origami circuit implementation after Methods/Discussion and Results audit')
    b=next(b for b in L.read('batches') if b['batch_id']=='B0011')
    action='Reviewed next3ACS supplements and rotating gku233 primary XML; seven of25 B0011 first passes saved.'
    if action not in b['completed_actions']: b['completed_actions'].append(action)
    b.update(after_counts=L.counts(),validation=[L.validate()],exclusion_audit={'sample':['10.1093/nar/gku233'],'denominator':'One catalog exclusion in B0011 so far','reason':'Same-agent second inspection of every Results subsection heading/opening paragraph confirms implemented transcription circuit; Discussion origami references are prospective background. Not independent review.'},next_queue=['Review9remaining ACS and9rotating B0011records','Reconcile all52 gku233 bibliography targets and investigate exact source parents','Continue FNANO2012/program abstracts, forward citations and author histories'])
    L.upsert('batches',b,'Checkpoint7/25 first passes and explicit exclusion audit')
    L.atomic(L.HERE/'batch_0011_second_audit.json',json.dumps(dict(batch_id='B0011',first_pass_count=7,input_count=25,complete_source_certifications=0,validation=L.validate(),counts=L.counts()),indent=2)+'\n')
    print(L.validate())

if __name__=='__main__': main()
