"""Explicit decisions from inspected B0003 sources; safe to resume partial batch."""
import json
import ledger as L
from review_batch_0001 import evidence

# Contribution, inspected locator, supported finding, remaining source check.
DECISIONS = {
'nl203217m': ('new_design','PDF pp.2–3 Fig S1 and caption; Table S1 heading','Scaffold/staple diagram visually inspected: colored staple groups and unpaired central bases form the actuator. The caption connects colors to Table S1.','Match colored staples to sequences; garbled extraction prevents completeness certification. AFM use of the word honeycomb is not a lattice assignment.'),
'nn203161y': ('modified_design','PDF p.8 Fig 7; pp.9,14 Tables 1–2','CpG-functionalized origami includes unextended core staples and optional handle-extended staples; internal/external presentation variants are documented.','Reconcile p8634 tube routing, handles, CpG-H sequences and exact internal/external combinations.'),
'la2037873': ('modified_design','PDF p.2 Figs S1–S4 captions and design descriptions','Rectangular scaffold/helper design is modified with six surface loop groups A–F and dumbbell inserts; linker sets connect numbered sites.','Match core, inserted dumbbell and linker sequences to each tested variant; verify parent design.'),
'ja209861x': ('reused_design,modified_design','PDF p.2 Preparation of rectangular template; Self-assembly','Rectangle omits side staples and extends three adjacent staples per AuNP site by 15 bases; folding strands transform the decorated rectangle into a tube.','Resolve parent reference 2 and match capture/folding sets to handedness variants.'),
'nl204098n': ('new_design','PDF pp.1–2 Experimental methods','Linearized p8634 scaffold is annealed with staples and characterized/purified as origami nanopores.','Inspect routing, pore variants and complete staple tables; do not infer lattice from a nanopore title.'),
'ja209719k': ('new_design','PDF pp.2–3 Figs S1–S6; pp.9–15 Figs S9–S15; pp.16,18,20,22,25,28 table headings','Four close-packed hexagonal and two hybrid bundles have separate diagrams/tables. Fig S15 visually compares 18HB honeycomb, 20HB square and 24HB hexagonal cross-sections.','The six main close-packed/hybrid objects are outside the narrow standard-lattice scope; determine whether standard-lattice comparators constitute eligible reuse with recoverable sources before excluding the publication.'),
'ja209023u': ('modified_design','PDF p.4 Figs S2–S3; five-well frame staple sequence heading','AFM captions report selective dsDNA-III incorporation and alkylation inside well III of a five-well DNA frame; a frame staple list follows.','Inspect complete routing, incorporated duplex connection sequences and parent frame source; frame/filled-domain scope remains unresolved.'),
'nl3004336': ('new_design,modified_design','SI p.2 Table S1; primary XML body design description and conclusion','Two FRET switches use a serpentine scaffold, three common staples and control-strand variants across eight 14nt domains. Main article explicitly identifies DNA origami techniques.','Small three-helix device requires explicit scope assessment; reconcile control/removal/return strands and dyes with each switch.'),
'nn300718z': ('uncertain','PDF pp.2–3 Table 1 and DX-tile experiments','SI experiments and sequences concern five-oligonucleotide DX tiles, their variants and triplex-forming oligonucleotides. This does not establish an origami experiment.','Inspect primary article before final not-origami exclusion; origami may be prospective context rather than experimental reuse.'),
'ja300897h': ('reused_design,modified_design','PDF p.2 DNA origami preparation; references to Figs S16–S21','7249nt M13 rectangle with core/probe sets organizes an enzyme cascade using protein-binding sequences.','Resolve parent reference 1 and inspect all position/probe variants and Figs S16–S21.'),
'nn3010747': ('reused_design,modified_design','PDF pp.1–3 methods, modified strand list, Fig S1 and references','Rothemund 2006 triangle and original staple numbering support disulfide/biotin probe substitutions and mixed TT/SS-TT experiments.','Resolve exact triangular variant and complete combinations of core/probe substitutions.'),
'nl301399z': ('new_design,modified_design','PDF p.2 assembly and frame transformation','M13 Frame 1 is transformed using a 42-strand release set and 38-strand closure set; later Frame 2 to 3 transformation uses a different temperature.','Inspect all frame routing, scope and release/closure sets; frame names alone do not determine lattice eligibility.'),
'jp302316p': ('reused_design,modified_design','PDF pp.1–2 Fig S1 and attachment diagrams','T-origami branches bear metallization seeds with different AuNP ratios and attachment sites.','Resolve parent and whole routing; Poppler returned syntax warnings, so verify source images before interpreting sequences or completeness.'),
'ja3017939': ('reused_design','PDF pp.1–2 preparation and AFM heating/cooling; Rothemund reference','Thermal response experiments use M13 rectangles assembled by a modified Rothemund protocol with excess staples. Protocol modification alone does not demonstrate new routing.','Resolve exact rectangular variant and core set; assess whether any structural modification was actually introduced.'),
'nn302896c': ('new_design,modified_design','PDF pp.1–3 methods, Figs S1–S2','Small lambda-derived objects use 32nt staples; large triangles use 52nt staples. Two offset ssDNA scaffold routes and square/triangle/24HB gel variants are shown.','Separate dsDNA-derived scaffold variants and reconcile all core sets and lattice evidence.')}

def main():
    acs={r['doi']:r for r in json.loads((L.ROOT/'acs_acquisition.json').read_text())['records']}
    for r in L.read('publication_reviews'):
        suffix=r['doi'].split('/')[-1]
        if suffix not in DECISIONS or r.get('run_id')!='bootstrap-20261105':continue
        contrib,loc,note,question=DECISIONS[suffix]
        f=next(f for f in acs[r['doi']]['files'] if f.get('local_file','').endswith('.pdf'))
        ev=[evidence(L.ROOT/'assets'/f['local_file'],f['url'],loc)]
        if suffix=='nl3004336':ev.append(evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC3324986.xml','https://pmc.ncbi.nlm.nih.gov/articles/PMC3324986/','body: scaffold/staple construction and concluding DNA origami statement'))
        r.update(review_stage='design_sources_reviewed',relevance='uncertain' if contrib=='uncertain' else 'design_bearing',catalog_eligibility='unresolved',design_contributions=contrib.split(','),evidence=ev,rationale=note,unresolved_questions=[question],access='partial',reviewer='Codex source inspection',run_id='B0003',date=L.DATE)
        L.upsert('publication_reviews',r,'B0003 inspected SI sections; no title-only classification')
    d=next(d for d in L.read('design_evidence') if d['design_id']=='S058')
    if not d.get('review_run'):
        r=next(r for r in L.read('publication_reviews') if r['doi']=='10.1021/nl203217m')
        d.update(review_run='B0003',evidence=r['evidence'],source_completeness='not_verified',lattice_decision='unresolved',outstanding_checks=r['unresolved_questions'])
        L.upsert('design_evidence',d,'Visually inspect nanoactuator Fig S1; preserve sequence/color reconciliation gap')
    batch=next(b for b in L.read('batches') if b['batch_id']=='B0003')
    if batch['status']=='completed':
        print(json.dumps(L.validate()));return
    batch.update(completed_actions=['Inspected source sections for all 15 prioritized ACS records; 14 supported design-bearing, one DX-tile paper remains uncertain.','Visually inspected nanoactuator routing and hexagonal-paper comparator cross-sections.'],after_counts=L.counts(),validation=[L.validate()],unresolved_keys=batch['input_keys'],next_queue=batch['input_keys'][15:])
    L.upsert('batches',batch,'Save partial B0003; ten rotating records still pending')
    print(json.dumps(L.validate()))

if __name__=='__main__':main()
