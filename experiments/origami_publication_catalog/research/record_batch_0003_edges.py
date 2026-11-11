"""Explicitly inspected source relationships; unresolved targets remain leads."""
import ledger as L

def main():
    pubs={r['registry_key']:r for r in L.read('publication_reviews')}
    specs=[
        ('10.1021/nn3010747','10.1038/nature04586','reuses_design_from','SI pp.1–3: original triangle staple numbering and reference 1'),
        ('10.1021/ja3017939','10.1038/nature04586','reuses_design_from','SI p.1: rectangle preparation and Rothemund reference'),
        ('10.1126/science.1150082','10.1038/nature04586','uses_method_from','Printed pp.180–181: scaffolded origami method and reference 6; exact parent geometry unresolved'),
        ('10.3410/f.1119443.575638','10.1021/ja8030196','is_review_of','Crossref message.relation.is-review-of'),
        ('PMC2577351','lead:sanger-team104-cover-model','cover_credit_lead','XML body final Cover paragraph: Alex Bateman; http://www.sanger.ac.uk/Teams/Team104/')]
    existing={e['edge_id'] for e in L.read('discovery_edges')}
    for source,target,relation,locator in specs:
        eid=relation+':'+source+':'+target
        if eid in existing:continue
        ev=pubs[source]['evidence'][0]
        L.upsert('discovery_edges',{'edge_id':eid,'source_key':source,'target_key':target,'relation':relation,'evidence_url':ev['url'],'local_file':ev['local_file'],'sha256':ev['sha256'],'locator':locator,'reconciliation_state':'publication_link_supported; exact_variant_pending' if target in pubs else 'pending_identity_and_scope','run_id':'B0003','date':L.DATE},'Retain explicit source relationships without merging versions or claiming complete design')
    print(L.validate())

if __name__=='__main__':main()
