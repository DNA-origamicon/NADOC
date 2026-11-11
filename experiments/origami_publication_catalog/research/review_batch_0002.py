"""Manual screening decisions from inspected B0002 source sections, 2026-11-05."""
import json
import ledger as L
from review_batch_0001 import evidence

# DOI suffix: contribution, exact source locator, review rationale, remaining question.
DECISIONS={
'nl901165f':('new_design','PDF p.1 Materials and Methods','M13 and staple strands are assembled into a tetrahedron cage and characterized by AFM/TEM. A tetrahedron name alone does not establish whether faces are filled or wireframe.','Inspect full face/routing design and staple tables; do not exclude from title alone.'),
'ja902569x':('new_design,modified_design','PDF pp.4–6 Figs S3–S5; p.12 sequence heading','Double-stranded scaffolds encode triangle-with-flaps and six-helix bundles on opposite strands; linearized pEGFP folds both strands into 6HBs.','Design diagrams have garbled extracted text; inspect images and distinguish scaffold/strand variants and the 6HB triangle.'),
'ja906381y':('new_design,modified_design','PDF p.4 Fig S1; pp.6–9 Figs S3–S6; pp.10,15,19,23 Tables S1–S4','SI explicitly labels 2-,3-,6-,8-layer square-lattice objects and three 3-layer deletion variants; separate staple table headings match the four core objects. Supports existing catalog eligibility, not new discovery.','Reconcile 3/4/5 deletions per 192 bases with core tables; no synthesis-ready completeness certification.'),
'ja907649w':('modified_design','PDF p.2 Fig S1 and Table S1','A DNA frame contains 64mer and 74mer duplexes with distinct connection sites and EcoRI recognition sequence. These functional modifications are part of the reported experiment.','Retrieve primary methods and original frame source; Table S1 here lists inserted duplexes, not a verified complete origami core.'),
'ja9101198':('reused_design,modified_design','PDF p.2 Self-assembly; p.10 sequence section','Triangular template follows Rothemund 2006, with modified helper strands binding AuNP conjugates of different sizes.','Reconcile exact parent triangular variant and probe replacements with full sequence list.'),
'ja104702q':('modified_design','PDF p.1 Formation; p.4 Fig S1; p.5 Table S1 heading','Punched origami combines M13 with anchor and His-tagged strands for enzyme nanoarrays; scaffold fold and staple table are supplied.','Inspect hole/filled-domain scope, route and complete modified/core composition; reconcile parent.'),
'nl1018468':('reused_design,modified_design','PDF p.2 Design of origami tiles; p.10 Fig S1 caption','Rectangular probe tiles and a previously described Rothemund triangle organize capsids; rectangle variants have different probe locations.','Inspect all templates and probe sequences; avoid counting capsid occupancy variants as independent geometries.'),
'ja106292x':('new_design,reused_design,modified_design','PDF p.1 Assembly of DNA Origami','12-,24-,40-helix zigzag designs are modeled in Tiamat; the planar 24-helix rectangle explicitly uses previously published Rothemund sequences. Edge helpers are omitted from core reactions.','Check zigzag lattice eligibility separately and reconcile edge-linker replacement sets.'),
'nl101079u':('new_design,modified_design','PDF p.2 Supporting Information S1 DNA Nanotube Design','M13 and 170 staples form six parallel helices; staples have repeating three 14-base domains. Quantum-dot functionalization is design-bearing.','Inspect cross-section, every functionalized staple and parent design relationship; optional unused extension sites are not experimental variants.'),
'nn101662a':('modified_design','PDF p.1 Fig S1; p.3 Fig S3','Origami platform uses 225 staples plus two bait-DNA oligonucleotides; hTopoIB interactions are measured on the protruding bait.','Retrieve exact core template and bait strand sequences from methods; verify lattice independently.'),
'nl103427w':('new_design,modified_design','PDF p.1 DNA origami design','LRO/RRO designs and LRO oligomers are explicitly linked to Fig S9 and Tables S10–S11; adjacent staples are split/rejoined to orient biotin anchors.','Inspect tables, routing and docking modifications; reconcile LRO/RRO parent designs.'),
'nn102701f':('modified_design','PDF p.2 Experimental Details: Assembly of the DNA Origami Scaffold','M13 rectangular origami carries biotin and photosensitizer-related oligonucleotide modifications for the singlet-oxygen experiment.','Inspect complete sequence/modification sections and original template citation; literature review only, no photochemistry simulation.'),
'nn1031627':('new_design,modified_design','PDF p.2 Figs S1–S2','Preassembled trimers and labeled jigsaw pieces assemble into larger two-dimensional objects, supported by AFM panels.','Inspect component routing and full staple list; separate tile designs from assembly configurations and decorative labels.'),
'nl104555t':('modified_design','PDF pp.1–2 Experimental Methods and Formation of DNA Origami Tiles','M13 tiles are coassembled with marker and marker-base strands for symbolic SNP detection; staple and marker concentrations differ.','Inspect marker/base lists and original origami routing; do not infer complete core set from marker recipes.'),
'ja1105464':('reused_design,modified_design','PDF p.3 Sample preparation and Table S1','All experiments explicitly use Rothemund original rectangular design with four-color dye modifications listed by original staple name.','Verify exact rectangular variant and all dye/immobilization combinations; functional dye variants are not new routing geometries.'),
'nl1040836':('reused_design','PDF p.1 Assembly of DNA Origami','Cell-lysate experiments assemble rectangular, triangular and cuboid origami from corresponding helper sets. This is substantive origami use despite the stability-focused title.','Resolve parent publications and lattice/source eligibility separately for all three objects; reuse origin remains provisional.'),
'bc2000098':('modified_design','PDF p.3 Fig S1, visually inspected','Diagram explicitly compares regular and altered staple patterns for modified staples; enzymatic functionalization is a structural-source lead.','Inspect whole object/core identity and enzymatically modified sequence sets; local schematic alone is not a full design.'),
'nl200306w':('reused_design,modified_design','PDF pp.1–2 DNA Origami Folding; p.5 Fig S1 caption','A previously reported rectangle receives sticky-end modifications for attachment to AuNP arrays.','Resolve reference 2 and precise rectangle identity; inspect modifications and core sequences.'),
'nl201603a':('new_design,modified_design','PDF p.2 Assembly Procedure','M13-based tiles have unique probes along two edges; separately folded PhiX174 frames and bridge strands organize higher-order assemblies.','Assess frame versus component scope independently, match bridge/probe sets, and inspect complete routing.'),
'ja204546h':('modified_design','PDF p.1 Materials and methods: Preparation of monomer tiles','M13 monomer tiles with number-encoding hairpins are assembled into trimers and tested after photo-cross-linking at different annealing temperatures.','Reconcile tile parent geometry and all staple/label combinations; no molecular reconstruction or simulation authorized.')}


def main():
    acs={r['doi']:r for r in json.loads((L.ROOT/'acs_acquisition.json').read_text())['records']}
    batch=next(b for b in L.read('batches') if b['batch_id']=='B0002')
    for r in L.read('publication_reviews'):
        if r['registry_key'] not in batch['input_keys'] or r.get('run_id')!='bootstrap-20261105':continue
        doi=r['doi'];suffix=doi.split('/')[-1];ev=[]
        if suffix in DECISIONS:
            contrib,loc,note,question=DECISIONS[suffix]
            f=next(f for f in acs[doi]['files'] if f.get('local_file','').endswith('.pdf'))
            ev=[evidence(L.ROOT/'assets'/f['local_file'],f['url'],loc)]
            stage='design_sources_reviewed';relevance='design_bearing';eligibility='eligible' if suffix=='ja906381y' else 'unresolved'
        elif r['registry_key']=='PMC7135719':
            path=L.ROOT/'assets'/r['legacy_record']['xml_file'];ev=[evidence(path,'https://pmc.ncbi.nlm.nih.gov/articles/PMC7135719/','XML front/article-meta; no body content')]
            stage='metadata_screened';relevance='uncertain';eligibility='unresolved';contrib='uncertain'
            note='Retained XML contains metadata for 1996 Protein engineering, DOI 10.1016/S0958-1669(96)80127-3, but no article body. Registry bibliography title and later archival dates require identity reconciliation.'
            question='Retrieve PDF before final exclusion; reconcile registry title/date and primary metadata. No substantive fulltext review possible from this XML.'
        elif doi=='10.1038/scientificamerican0506-28d':
            path=L.ROOT/'assets/research-20261105/scientificamerican-origami.html'
            ev=[evidence(path,'https://www.scientificamerican.com/article/origami-from-dna/','Full three-paragraph news text, byline/date and DOI footer')]
            stage='fulltext_reviewed';relevance='background_or_review';eligibility='excluded';contrib=''
            note='Complete short news item summarizes Rothemund work and prospective applications; no original experiment, modification or design reuse is reported. Retained as background/news.'
            question='Reconcile reports_on relation to Rothemund 2006; no design-source extraction warranted.'
            r['publication_type']=['news'];r['date_evidence']={'date':'2006-05-01','source':ev[0],'primary_verified':True,'meaning':'publisher displayed publication date'}
        else:
            path=L.ROOT/'assets/research-20261105'/(doi.replace('/','_')+'.json')
            ev=[evidence(path,'https://api.crossref.org/works/'+doi,'message.title/type/published; no abstract supplied')]
            stage='metadata_screened';relevance='uncertain';eligibility='unresolved';contrib='uncertain'
            note='Publisher-deposited metadata inspected; generic journal-article type and title do not establish an original design. No abstract supplied.'
            question='Retrieve primary body before final background-only exclusion. Direct publisher access attempt returned unavailable or preview-only content.'
            if doi=='10.1038/news060313-8':
                r['publication_type']=['news'];note+=' Nature publisher page identifies News, 15 March 2006, and cites Rothemund; only subscription preview accessible.'
                ev.append({'url':'https://www.nature.com/articles/news060313-8','locator':'News heading/date, subscription preview and References; inspected 2026-11-05'})
        r.update(review_stage=stage,relevance=relevance,catalog_eligibility=eligibility,design_contributions=contrib.split(',') if contrib else [],
                 evidence=ev,rationale=note,unresolved_questions=[question],access='available' if relevance=='background_or_review' else 'partial',
                 reviewer='Codex source inspection',run_id='B0002',date=L.DATE)
        L.upsert('publication_reviews',r,'B0002 source inspection with low-signal rotation')
    # Reaffirm one already mapped square-lattice group without inventing a new group.
    d=next(d for d in L.read('design_evidence') if d['design_id']=='S042')
    if not d.get('review_run'):
        r=next(r for r in L.read('publication_reviews') if r['doi']=='10.1021/ja906381y')
        d.update(review_run='B0002',lattice_decision='square_explicit_primary_source',evidence=r['evidence'],
                 core_variant_composition='Separate Tables S1–S4 for 2/3/6/8-layer cores; 3-layer deletion variants not reconciled.',
                 source_completeness='not_verified',outstanding_checks=r['unresolved_questions'])
        L.upsert('design_evidence',d,'Reinspect four core table headings and explicit square-lattice design labels')
    for doi in ['10.1021/ja9101198','10.1021/nl1018468','10.1021/ja106292x','10.1021/ja1105464','10.1038/scientificamerican0506-28d']:
        r=next(r for r in L.read('publication_reviews') if r['doi']==doi)
        relation='reports_on' if 'scientificamerican' in doi else 'reuses_design_from'
        edge={'edge_id':relation+':'+doi+':rothemund2006','source_key':r['registry_key'],'target_key':'10.1038/nature04586',
              'relation':relation,'evidence_url':r['evidence'][0]['url'],'local_file':r['evidence'][0]['local_file'],
              'sha256':r['evidence'][0]['sha256'],'locator':r['evidence'][0]['locator'],
              'reconciliation_state':'publication_link_supported; exact_variant_pending','run_id':'B0002'}
        if not any(e['edge_id']==edge['edge_id'] for e in L.read('discovery_edges')):L.upsert('discovery_edges',edge,'Record explicit original-template reference')
    print(json.dumps({'counts':L.counts(),'validation':L.validate()},indent=2))


if __name__=='__main__':main()
