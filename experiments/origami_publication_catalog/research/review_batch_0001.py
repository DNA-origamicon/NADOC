"""Explicit human-readable decisions from source inspection on 2026-11-05.
No classifier: each entry is a manually assessed evidence statement.
Re-running retains newer reviews and never rebuilds the legacy structure map.
"""
import hashlib
import json
import ledger as L

# id: contribution, locator, supported conclusion, remaining checks
XML = {
'P0176': ('new_design', 'Results: The design of nanomechanical DNA origami devices; Methods: Preparation; Fig. 2', 'Pliers and forceps have two planar six-helix levers joined at a scaffold fulcrum; pinching, zipping and unzipping are functional variants.', 'Inspect SI Figs S5–S10 and Tables S1–S3 for each device and modification.'),
'P0399': ('new_design', 'Main text paragraph beginning We tested four linker designs; DNA-templated design and synthesis', 'Four 7560-base scaffold bundles with six, eight, ten and twelve helices were constructed and imaged; Table S1 is explicitly cited for staples.', 'Retrieve SI and confirm lattice cross-sections and Table S1 per bundle.'),
'P0551': ('new_design', 'Results: wireframe DNO design; Methods: DNA nano-octahedron synthesis', 'The paper explicitly describes a wireframe octahedron with twelve curved six-helix struts, p7308 scaffold and inner/outer functional handles. Broadly design-bearing; complete octahedron excluded by the catalog wireframe rule.', 'Reconcile source variants and original design files; excluded geometry is not a literature exclusion.'),
'P0750': ('new_design,modified_design', 'Results first paragraph; Programmable polymerization of DNA origami triskelions; Methods: DNA origami design and folding', 'Three-layer rectangular blocks and truncated Y constructs are assembled with cholesterol anchors, fluorescent handles and distinct dimerization/multimerization staples. Triskelion network geometry must be assessed separately from local bundle packing.', 'Inspect SI Fig S1 and Tables 1–2, including reused block provenance and Y component lattice.'),
'P1058': ('modified_design', 'Methods: DNA Origami Preparation', 'The funnel porin is explicitly designed on a square lattice and adapted from an earlier design; 19 cholesterol tags anchor the porin. SI Tables S1–S6 are cited.', 'Inspect SI Tables S1–S6 and reconcile reference 16 with the earlier template before catalog promotion.'),
'P1241': ('modified_design', 'Materials and Methods: DNA origami design and assembly; abstract', 'The article constructs left- and right-handed templates with variant pH-sensitive locks; routing and core/lock sequences are referred to Fig S1 and Tables S1–S2.', 'Inspect routing/lattice and lock-specific staple combinations; reconcile parent template.'),
'P1281': ('modified_design,reused_design', 'Abstract; Results: tunable brightness', 'Origami fluorophore templates carry varied dye and handle mixtures and capture strands. A 90 by 60 nm template is used; this is functional origami use, not background-only literature.', 'Inspect SI routing, source template citation and dye/handle substitutions; do not count 124 colors as 124 geometries.'),
'P1483': ('new_design,reused_design', 'Results: benchmark systems; Methods: DNA origami folding', 'Two 418-nucleotide single-layer benchmark systems are explicitly called Hc (honeycomb) and Sq (square). Published multilayer structures are also reused computationally. The legacy square-only candidate does not cover all objects in this paper.', 'Inspect Table S3 and benchmark routing; extract Hc separately and reconcile reused multilayer designs.'),
'P1508': ('new_design,modified_design', 'Results: DNA origami membrane sculpting; Methods: DNA origami design and folding', '20-helix H, Q and L designs use p7249 scaffold; Q-E5/E7/E13 and Q-S14 are oligomerization variants. Methods say hexagonal lattice, which needs figure-level reconciliation with the catalog rule.', 'Inspect SI Figs 2–4 and external/core staple substitutions; resolve hexagonal versus honeycomb designation.'),
'P1805': ('new_design,modified_design', 'Methods: Design of 6HB structures; Results: Sequence design to control twist; Fig. 4', 'Six-helix bundles with ten twisting blocks and terminal flags use staple nick placements to tune torsion. Two pairs of stiff, moderate and flexible variants are reported; all constituting staples are referred to SI Table S18.', 'Inspect S18 against S15–S17 and insertion variants; confirm lattice from routing.'),
'P1889': ('new_design,modified_design', 'Results: domain and edge topology design; Methods: DNA origami assembly', 'Three monolayer domains A/B/C share geometry but differ in sequence; e(-), e(0), e(1), e(2) edge configurations alter constraints. Supplementary Data 1 is cited for sequences.', 'Inspect domain routing and Data 1; distinguish sequence variants from distinct geometries.'),
'P2165': ('new_design', 'Results: DNA origami-based thick filaments; Methods: DNA origami preparation; Fig. 1', 'A 10HB backbone carries six 40-nm 2HB linkers with myosin handles and uses p8064 scaffold. Supplementary Data 2 is cited as the oligonucleotide list.', 'Inspect SI Fig 1 and Data 2 for lattice, core/linker and handle composition.'),
'P2168': ('new_design,modified_design', 'Results: DOC protocol; Methods: Generating sequences; Joining E- and F-tiles', 'Message strands and origami folding encode patterns; methods describe deliberate loss of some staple crossovers and E/F tile linkage. Patterns alone are not distinct molecular geometries.', 'Inspect each scaffold geometry, sequence lists and M-strand substitutions; reconcile variants.'),
}
SI = {
'P0021': ('new_design,modified_design', 'PDF pp.1–2, 6–7; Oligonucleotides and assembly recipes', 'Planar dolphin construction follows Rothemund-style crossover spacing. Stable tails replace same-named left/right staples with tail-seam staples; dimers additionally use red versus blue interaction sets.', 'Color-coded per-dimer replacements and author SARSE file availability remain unverified.'),
'P0023': ('modified_design,reused_design', 'PDF p.1 DNA Origami Design; p.3 reference 1; pp.12–15 Appendix B', 'A revised 410-nm 6HB uses 28 repeated 42-base units; the rectangle is explicitly identical to Rothemund 2006. Staple list heading is Appendix B, despite page 1 pointing to Appendix A.', 'Inspect all sequence rows and Fig S1 cross-section; reconcile 6HB parent design and exact rectangular variant.'),
'P0039': ('modified_design', 'PDF p.1 Design and hybridization; Figs S4–S5 and Table S1 referenced', 'Circular origami is designed by the Rothemund method with NTA-conjugated strands I and II; AFM assays test protein positioning.', 'Inspect Figs S4–S5 and Table S1; method reuse alone does not prove reuse of an identical published geometry.'),
'P0065': ('new_design', 'PDF pp.1–3,5,8,11; named scaffold and staple headings', 'Named sequence sets cover 756-base lambda rectangle, M13 rectangle, 2958-base M13 T, 3840-base lambda U and 4808-base lambda B designs.', 'Lattice/routing remains unresolved; sequence lists and shape names are insufficient to certify catalog scope or source completeness.'),
'P0116': ('reused_design,modified_design', 'PDF p.1; p.3 Table S1; p.7 Table S2 and reference 1; p.15 Fig S6 (visually inspected)', 'Tube design is explicitly reused from Stearns et al.; named staples are replaced by thiolated extensions. Fig S6 identifies a six-helix bundle and shows a hexagonal cross-section.', 'Resolve Stearns citation identity; inspect each experimental thiol combination and exact sequence correspondence.'),
'P0189': ('new_design,modified_design', 'PDF p.10 Fig S9 (visually inspected)', 'Fig S9 shows a flexible-attachment 6HB and rigid-attachment 6HB/4HB; the caption specifies a 7560-nt scaffold, manually added end staples and chemical modifications. Red crosses in the 4HB are drawing gaps to fit an 8-bp lattice into a 63-bp unit cell, not deleted molecular bases.', 'Inspect full-resolution template/sequence labels and lattice/attachment variants before eligibility decision.'),
'P0279': ('new_design', 'PDF pp.2–4: S1 small box design, Figs S1-1/S1-2 (visually inspected)', 'The 3.9-zL box combines normal 32-base crossovers with a second edge-connection rule described as hexagonal and 45-degree. Five-helix faces do not alone establish eligibility of the entire box.', 'Resolve nonstandard/hybrid lattice question from full routing before promotion or final exclusion; inspect staple list at p.27 onward.'),
'P0462': ('new_design,modified_design,reused_design', 'PDF pp.23–30: Nanoplate Design Details; Figs S35–S38; sequence-list heading', 'Four named HC/RR/2LL/3LL nanoplates have routing diagrams and separate staple sections. Gel caption identifies p7560 for HC/RR and p7704 for 2LL/3LL.', 'Inspect all four routing diagrams, complete sequence sections and tail replacements; reconcile reused RR provenance.'),
}


def evidence(path, url, locator):
    return {'local_file': str(path.relative_to(L.ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'url': url, 'locator': locator}


def main():
    rows = L.read('publication_reviews')
    acs = {r['doi']: r for r in json.loads((L.ROOT/'acs_acquisition.json').read_text())['records']}
    batch = L.read('batches')[0]
    for r in rows:
        if r['registry_key'] not in batch['input_keys'] or r.get('run_id') != 'bootstrap-20261105':
            continue
        identifier = r['registry_id']; legacy = r['legacy_record']; doi = r['doi']
        if identifier in XML:
            contribution, locator, rationale, question = XML[identifier]
            path = L.ROOT/'assets'/legacy['xml_file']
            ev = evidence(path, 'https://doi.org/'+doi, locator)
            stage = 'fulltext_reviewed'
        elif identifier in SI:
            contribution, locator, rationale, question = SI[identifier]
            f = next(f for f in acs[doi]['files'] if f.get('local_file','').endswith('.pdf'))
            ev = evidence(L.ROOT/'assets'/f['local_file'], f['url'], locator)
            stage = 'design_sources_reviewed'
        else:
            path = L.ROOT/'assets/research-20261105'/(doi.replace('/','_')+'.json')
            data = json.loads(path.read_text())['message']
            ev = evidence(path, 'https://api.crossref.org/works/'+doi, 'message.title, published-online, abstract when supplied')
            contribution = 'uncertain'; stage = 'metadata_screened'
            rationale = 'Publisher-deposited Crossref metadata inspected. Title alone does not resolve design contribution or catalog eligibility.'
            if identifier == 'P0300':
                rationale = 'Publisher-deposited abstract reports cryo-EM and a pseudoatomic model of a discrete designed DNA object; design-bearing, with source completeness unresolved.'
            question = 'Retrieve primary article and design supplements; title/metadata do not resolve the candidate.'
        r.update(review_stage=stage, relevance='design_bearing' if identifier in XML or identifier in SI or identifier=='P0300' else 'uncertain',
                 design_contributions=contribution.split(','), catalog_eligibility='excluded' if identifier=='P0551' else 'unresolved',
                 access='partial', evidence=[ev], rationale=rationale, reviewer='Codex source inspection',
                 run_id='B0001', date=L.DATE, unresolved_questions=[question])
        if identifier == 'P0551':
            f=next(f for f in acs[doi]['files'] if f.get('local_file','').endswith('.pdf'))
            r['evidence'].append(evidence(L.ROOT/'assets'/f['local_file'], f['url'], 'PDF p.3 Supporting Fig.1 caption: routing through twelve struts; independent second-pass scope audit'))
        L.upsert('publication_reviews',r,'B0001 substantive source inspection; preserve legacy decision')
    # Design-specific extractions preserve stable IDs; no synthesis-completeness claims.
    selected = {'S041': ('excluded_wireframe', 'DNO core plus inner fluorophore and variable outer lipid handles', 'Article explicitly wireframe; SI Fig 1 twelve-strut routing confirms the exclusion.'),
                'S047': ('planar_parallel_helices_supported', 'Left/right/body core; stable tail substitutes tail seam; dimer red/blue interaction sets replace matching staples', 'Recipes inspected on SI pp.6–7; color mapping not fully extracted.'),
                'S048': ('unresolved', 'Separate M13/lambda 756-nt rectangle sequence sets', 'SI pp.3–4; routing review pending.'),
                'S049': ('unresolved', '2958-nt M13 T scaffold plus its staples', 'SI pp.5–7; routing review pending.'),
                'S050': ('unresolved', '3840-nt lambda U scaffold plus its staples', 'SI pp.8–10; routing review pending.'),
                'S051': ('unresolved', '4808-nt lambda B scaffold plus its staples', 'SI pp.11–14; routing review pending.'),
                'S057': ('six_helix_hexagonal_cross_section_supported', 'Core Table S1 with named Table S2 thiolated replacements', 'SI pp.1,3,7,15; Fig S6 cross-section inspected.'),
                'S059': ('unresolved', 'Flexible 6HB; rigid 6HB and 4HB; end staples and biotin/digoxigenin modifications', 'SI p.10 Fig S9; graphical gaps must not be interpreted as deletions.'),
                'S060': ('unresolved_hybrid_edge_rule', '1774-base box scaffold; five-helix faces and distinct edge connections', 'SI pp.2–4; requires full routing scope decision.'),
                'S063': ('unresolved', 'HC/RR p7560 and 2LL/3LL p7704; core and protruding tails require matching', 'SI pp.23–30; all four routing panels still require visual assessment.')}
    current = {r['registry_key']: r for r in L.read('publication_reviews')}
    for d in L.read('design_evidence'):
        if d['design_id'] not in selected or d.get('review_run'): continue
        lattice, composition, note = selected[d['design_id']]
        r=current[d['publication_keys'][0]]
        d.update(lattice_decision=lattice, core_variant_composition=composition,
                 evidence=r['evidence'], source_completeness='not_verified',
                 extraction_note=note, outstanding_checks=r['unresolved_questions'], review_run='B0001',
                 catalog_sync='legacy_map_retained; sidecar scope decision is newer')
        if d['design_id']=='S057':
            d['relationships']=[{'relation':'reuses_with_modification','target':'Stearns et al., Angew. Chem. Int. Ed. 2009, pp.8494–8496', 'status':'bibliographic_identity_pending','evidence':r['evidence'][0]}]
        L.upsert('design_evidence',d,'B0001 design-specific evidence extraction')
    print(json.dumps(L.validate(),indent=2))


if __name__=='__main__':main()
