"""Record inspected selected Rothemund bibliography without claiming completeness."""
import ledger as L
from review_batch_0001 import evidence


def main():
    url='https://rothemundlab.caltech.edu/publications/'
    ev=evidence(L.ROOT/'assets/research-20261105/rothemund-publications.html',url,'Entire Highlights and Selected List; explicit link to full Google Scholar list')
    # Exact DOI-bearing links inspected on the official lab page; all pre-2020 targets already in registry.
    dois=['10.1038/nature18287','10.1021/nn506014s','10.1038/ncomms5889','10.1038/nchem.1070','10.1038/nnano.2009.311','10.1038/nature04586','10.1038/440283a']
    pubs={r['doi']:r['registry_key'] for r in L.read('publication_reviews') if r['doi']}
    run={'run_id':'author-rothemund-selected-20261105','route':'author_bibliography',
         'query_or_seed':{'name':'Paul W. K. Rothemund','affiliation':'Caltech','identity_evidence':url,'variants':['P.W.K. Rothemund','Paul Rothemund'],
                          'linked_scholar_id':'MnQWxDEAAAAJ'},
         'source_url':url,'date':L.DATE,'pagination':{'single_page_inspected':True,'bibliography':'explicitly selected'},
         'provider_total':None,'retrieved_count':1,'deduplicated_additions':sum(doi not in pubs for doi in dois),
         'additions_unit':'unmatched DOI leads, not eligible works','failures':[],
         'checkpoint':'Selected page inspected. Follow linked full bibliography, Caltech DNA group bibliography, non-DOI Science links and primary dates.',
         'closure_state':'in_progress','evidence':[ev],
         'unresolved_questions':['Selected list is not full publication history.','Lab citation for nature18287 has an inconsistent volume/year-style label; verify publisher metadata.','RNA and post-2019 entries are not eligible DNA-origami designs; retain as route context, not inferred inclusions.']}
    L.upsert('discovery_runs',run,'Inspect selected author bibliography and preserve incomplete-history status')
    for doi in dois:
        edge={'edge_id':'author-rothemund:'+doi,'source_key':run['run_id'],'target_key':pubs.get(doi,doi),'relation':'author_bibliography',
              'evidence_url':url,'local_file':ev['local_file'],'sha256':ev['sha256'],'locator':'DOI-bearing publication link '+doi,
              'reconciliation_state':'matched_registry_doi' if doi in pubs else 'pending_identity_and_scope','run_id':run['run_id']}
        L.upsert('discovery_edges',edge,'Record author bibliography link; no new eligibility inferred')
    print(L.validate())


if __name__=='__main__':main()
