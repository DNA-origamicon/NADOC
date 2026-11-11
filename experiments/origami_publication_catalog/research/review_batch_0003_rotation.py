"""B0003 rotating queue: inspected primary excerpts and deposited metadata."""
import json
import ledger as L
from review_batch_0001 import evidence


def main():
    root=L.ROOT/'assets/research-20261105'
    b=next(b for b in L.read('batches') if b['batch_id']=='B0003')
    if b['status']=='completed':
        print(json.dumps(L.validate()));return
    for r in L.read('publication_reviews'):
        k=r['registry_key']
        if k not in b['input_keys'][15:] or r.get('run_id')!='bootstrap-20261105':continue
        stage='metadata_screened';rel='uncertain';elig='unresolved';contrib=['uncertain']
        if k=='PMC2577351':
            ev=[evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC2577351.xml','https://pmc.ncbi.nlm.nih.gov/articles/PMC2577351/','front and entire body, including final cover credit')]
            stage='fulltext_reviewed';rel='background_or_review';elig='excluded';contrib=[]
            note='Administrative subscription/pricing/permissions notice, not a molecular experiment. Final cover credit names a DNA origami model by Alex Bateman and links to Sanger Team104; it supplies no molecular routing or synthesis evidence.'
            question='Follow the cover-credit link as a separate unresolved lead; do not assume its model is molecular rather than a paper model.'
            r['publication_type']=['front_matter','subscription_notice']
        elif k=='10.1126/science.1150082':
            ev=[evidence(root/'soluble-nanoarrays.pdf','https://cancer-insights.asu.edu/wp-content/uploads/2010/02/Soluble-nanoarrays.pdf','PDF pp.2–3, printed pp.180–181: tile design, preparation, Fig 1 and bar-coded variants')]
            stage='fulltext_reviewed';rel='design_bearing';contrib=['modified_design','reused_design']
            note='M13 7249-base rectangular tiles carry paired 20-base probes and dumbbell index loops. Four bar-coded variants and position-dependent probe variants are experimentally assembled. Rothemund is the methodological/template reference.'
            question='Acquire linked supporting online material and reconcile full core/probe/index combinations; rectangular dimensions alone do not certify lattice/source eligibility.'
        else:
            ep=root/('epmc-'+r['doi'].replace('/','_')+'.json')
            if ep.exists() and json.loads(ep.read_text()).get('hitCount',0):
                url=json.loads((root/'acquisition.json').read_text())[ep.name]['url']
                ev=[evidence(ep,url,'resultList.result: title, publication types and abstract where supplied')]
                note='Deposited bibliographic record inspected; source body and supplements remain unreviewed.'
                if k=='10.2147/nsa.s4092':note='Abstract and publication types describe a review of protein cages, rings and tubes. Full text must be inspected for substantive origami reuse before final background-only disposition.'
                if k=='10.1038/nnano.2008.164':note='Abstract reports distance-controlled multivalent ligands on DNA nanostructures; it does not identify scaffolded origami. Primary methods must distinguish origami from oligonucleotide tile assembly.'
            else:
                p=root/(r['doi'].replace('/','_')+'.json')
                ev=[evidence(p,'https://api.crossref.org/works/'+r['doi'],'message title/type/published/abstract/relation')]
                note='Publisher-deposited metadata inspected; no body reviewed and title alone does not support a final relevance decision.'
                if k=='10.1073/pnas.0803841105':note='Deposited abstract describes five-point-star motifs assembled using three component strands into cages/icosahedra. This suggests non-origami tiles, but methods/supplement inspection remains required for final exclusion.'
                if k=='10.3410/f.1119443.575638':
                    note='Deposited type is dataset, title is a Faculty Opinions recommendation, and is-review-of points to 10.1021/ja8030196. Preserve as a separate recommendation version; no original-design evidence reviewed.'
                    r['publication_type']=['recommendation'];r['version_links']=[{'relation':'is-review-of','target_key':'10.1021/ja8030196','evidence':ev[0]}]
            question='Retrieve primary body and relevant supplements; metadata stage is not a completed exclusion or source review.'
        r.update(review_stage=stage,relevance=rel,catalog_eligibility=elig,design_contributions=contrib,evidence=ev,rationale=note,unresolved_questions=[question],access='available' if k=='PMC2577351' else 'partial',reviewer='Codex source inspection',run_id='B0003',date=L.DATE)
        L.upsert('publication_reviews',r,'B0003 broad and low-signal rotation; preserve uncertainty')
    b.update(status='completed',after_counts=L.counts(),validation=[L.validate()],completed_actions=b['completed_actions']+['Screened ten rotating records: one primary design paper, one administrative notice, eight unresolved metadata cases.'],exclusion_audit={'sample':['PMC2577351'],'sampling_method':'Only final exclusion in batch: census audit (100%, no random seed needed).','reviewer':'Same-agent second pass, not independent','finding':'Re-read complete saved XML: body is administrative; final cover credit retained as unresolved discovery lead, not a complete design.'},next_queue=['Follow cover-credit link from PMC2577351','Acquire primary bodies/SI for eight metadata-only records','Inspect source completeness and lattice gaps for 15 ACS records','Follow references and forward citations, then next balanced screening batch'])
    L.upsert('batches',b,'Complete first-pass screening B0003; unresolved source checks persist')
    print(json.dumps(L.validate()))

if __name__=='__main__':main()
