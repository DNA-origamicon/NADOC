"""Record all references from the first reviewed XML batch and conference leads.
This enumerates reference lists, never infers eligibility from title keywords.
"""
import hashlib
import json
from urllib.parse import parse_qs
import xml.etree.ElementTree as ET
import ledger as L
from review_batch_0001 import evidence


def main():
    pubs=L.read('publication_reviews'); known={r['doi']:r['registry_key'] for r in pubs if r['doi']}
    edges={r['edge_id']:r for r in L.read('discovery_edges')}
    seeds=[]; evidence_refs=[]; count=0; targets=set()
    for r in pubs:
        if r.get('run_id')!='B0001' or r['review_stage']!='fulltext_reviewed':continue
        path=L.ROOT/'assets'/r['legacy_record']['xml_file']; root=ET.parse(path).getroot(); seeds.append(r['registry_key'])
        ev=evidence(path,'https://doi.org/'+r['doi'],'all XML ref elements')
        evidence_refs.append(ev)
        for i,ref in enumerate(root.findall('.//ref'),1):
            doi=next((''.join(e.itertext()).strip().lower() for e in ref.findall('.//pub-id') if e.get('pub-id-type')=='doi'),'')
            links=ref.findall('.//ext-link')
            if not doi:
                doi=next((e.get('{http://www.w3.org/1999/xlink}href','').removeprefix('https://doi.org/').lower() for e in links if e.get('ext-link-type')=='doi'),'')
            scholar=next((parse_qs(e.get('{http://www.w3.org/1999/xlink}href','')) for e in links if e.get('ext-link-type')=='google-scholar'),{})
            locator=ref.get('id') or str(i)
            target=known.get(doi,doi or 'reference:'+r['registry_key']+':'+locator)
            edge_id='cites:'+r['registry_key']+':'+locator
            title=ref.find('.//article-title');year=ref.find('.//year')
            # All references retained, including pre-2006 background and non-origami methods.
            record={'edge_id':edge_id,'source_key':r['registry_key'],'target_key':target,
                         'relation':'cites','evidence_url':ev['url'],'local_file':ev['local_file'],'sha256':ev['sha256'],
                         'locator':'XML ref '+locator,'target_doi':doi,
                         'target_title':''.join(title.itertext()) if title is not None else scholar.get('title',[None])[0],
                         'target_year':year.text if year is not None else scholar.get('publication_year',[None])[0],
                         'reconciliation_state':'matched_registry_doi' if doi in known else 'pending_identity_and_scope',
                         'run_id':'backward-B0001','date':L.DATE}
            old=edges.get(edge_id)
            if old and any(old.get(k)!=v for k,v in record.items()):
                record['revision_history']=old.get('revision_history',[])+[{'superseded':{k:v for k,v in old.items() if k!='revision_history'},'reason':'Resolve DOI and bibliographic metadata from JATS ext-link fields as well as pub-id','date':L.DATE}]
                edges[edge_id]=record
            elif not old:
                edges[edge_id]=record
            count+=1;targets.add(target)
    L.save('discovery_edges',list(edges.values()))
    run={'run_id':'backward-B0001','route':'backward_citations','query_or_seed':seeds,
         'source_url':'retained PMC XML; see evidence','date':L.DATE,'pagination':{'method':'all XML ref elements','complete':True},
         'provider_total':count,'retrieved_count':count,'unique_targets':len(targets),
         'deduplicated_additions':len(targets-set(known.values())),
         'additions_unit':'unresolved reference targets, NOT newly eligible publications',
         'failures':[],'checkpoint':'all 13 source reference lists extracted; target review pending',
         'closure_state':'exhausted','closure_scope':'reference extraction for these seeds only; recursive and forward routes pending',
         'evidence':evidence_refs,'revision_history':[]}
    L.upsert('discovery_runs',run,'Record uncapped reference extraction with both JATS DOI encodings')
    for year in range(2006,2020):
        rid=f'fnano-{year}'
        if any(r['run_id']==rid for r in L.read('discovery_runs')):continue
        run={'run_id':rid,'route':'conference','query_or_seed':f'FNANO {year} official program and abstract book',
             'source_url':None,'date':L.DATE,'pagination':None,'provider_total':None,'retrieved_count':0,
             'deduplicated_additions':0,'failures':[],'checkpoint':'Locate official or archived program and abstracts',
             'closure_state':'pending','evidence':[],'revision_history':[]}
        if year==2019:
            path=L.ROOT/'assets/research-20261105/FNANO19schedule.pdf'
            url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO19schedule.pdf'
            run.update(source_url=url,closure_state='in_progress',retrieved_count=1,
                       pagination={'pages':10,'pages_reviewed':[1]},
                       checkpoint='Official 10-page schedule retained; p.1 inspected. Review pp.2–10 and locate abstract book; reconcile leads.',
                       failures=[{'url':'https://www2.cs.duke.edu/FNANO/','error':'web tool HTTP 403; schedule accessible by direct public fetch'}],
                       evidence=[evidence(path,url,'PDF p.1; April 15, 2019 schedule')])
        L.upsert('discovery_runs',run,'Initialize explicit conference-year coverage')
    # The schedule identifies presentations, not complete molecular designs.
    entries=[('nixon','Exploring the addressability of DNA-decorated multifunctional gold nanoparticles with DNA origami template',['Rachel Nixon','Wenyan Liu','Shuo Yang','Risheng Wang'],'poster'),
             ('yang','pH-Driven hierarchical assembly of DNA origami nanostructures',['Shuo Yang','Wenyan Liu','Risheng Wang'],'poster'),
             ('chakraborty','A DNA Origami based multi-input logic gate for modifying DNA by enzyme nano-factory',['Banani Chakraborty','Elmar Weinhold'],'poster'),
             ('zeng','Fabrication of a DNA Origami Integrated Hydrogen Peroxide Sensing Platform',['Yun Zeng','Wenyan Liu','Risheng Wang'],'invited_talk')]
    ev=evidence(L.ROOT/'assets/research-20261105/FNANO19schedule.pdf','https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO19schedule.pdf','PDF p.1 Monday April 15 schedule')
    for suffix,title,authors,kind in entries:
        key='conference:fnano2019:'+suffix
        if any(r['registry_key']==key for r in L.read('publication_reviews')):continue
        L.upsert('publication_reviews',{'registry_key':key,'registry_id':None,'doi':'','title':title,'authors':authors,
                 'canonical_work_id':'work:'+key,'canonical_work_status':'provisional_unreconciled','version_links':[],
                 'publication_type':['conference_'+kind],'date_evidence':{'date':'2019-04-15','source':ev,'primary_verified':True,'meaning':'scheduled presentation date, not verified first public release'},
                 'review_stage':'metadata_screened','relevance':'uncertain','design_contributions':['uncertain'],
                 'catalog_eligibility':'unresolved','access':'partial','evidence':[ev],
                 'rationale':'Program title and authors verified. Presentation is a lead; no abstract or full design inspected.',
                 'reviewer':'Codex source inspection','run_id':'fnano-2019','date':L.DATE,
                 'unresolved_questions':['Find abstract and reconcile journal/preprint counterpart; assess actual design contribution.'],
                 'legacy_record':{},'revision_history':[]},'Record conference publication type without assuming design completeness')
        L.upsert('discovery_edges',{'edge_id':'fnano2019:'+suffix,'source_key':'fnano-2019','target_key':key,
                 'relation':'conference_lead','evidence_url':ev['url'],'locator':ev['locator'],
                 'local_file':ev['local_file'],'sha256':ev['sha256'],'reconciliation_state':'journal_preprint_counterpart_pending'},'Persist unreconciled conference lead')
    for route,seed in [('forward_citations',seeds),('author_bibliography',['Ebbe Sloth Andersen','Ralf Jungmann','Risheng Wang','Banani Chakraborty','Elmar Weinhold']),('bibliographic_search','Replace capped Crossref title queries with cursor/date-partition discovery after inspecting API capabilities')]:
        rid=route+'-initial'
        if any(r['run_id']==rid for r in L.read('discovery_runs')):continue
        L.upsert('discovery_runs',{'run_id':rid,'route':route,'query_or_seed':seed,'source_url':None,'date':L.DATE,
             'pagination':None,'provider_total':None,'retrieved_count':0,'deduplicated_additions':0,'failures':[],
             'checkpoint':'Not yet executed','closure_state':'pending','evidence':[]},'Persist unfinished discovery route')
    print(json.dumps({'counts':L.counts(),'citation_edges':count,'unique_reference_targets':len(targets),'validation':L.validate()},indent=2))


if __name__=='__main__':main()
