"""Two individually inspected literature-only design groups; no map promotion."""
import ledger as L

def main():
    paper=next(r for r in L.read('publication_reviews') if r['doi']=='10.1021/ja209719k')
    for did,name,loc,decision,table in [
        ('RDE0001','12HB-L','PDF p.9 Fig S9, visually inspected; p.15 Fig S15 lattice distinction','excluded_close_packed_hexagonal','Table S1 begins PDF p.16'),
        ('RDE0002','56HB hybrid','PDF p.13 Fig S13, visually inspected; p.15 Fig S15 lattice distinction','excluded_hybrid_lattice','Table S5 begins PDF p.25')]:
        if any(d['design_id']==did for d in L.read('design_evidence')):continue
        ev={**paper['evidence'][0],'locator':loc+'; '+table}
        row={'design_id':did,'publication_keys':[paper['registry_key']],'named_objects':[name],'variant_links':[],
             'relationships':[{'relation':'presented_in','target_key':paper['registry_key'],'evidence':ev}],
             'evidence':[ev],'source_files':[ev],'lattice_decision':decision,'catalog_eligibility':'excluded',
             'catalog_sync':'research_only_out_of_scope; do_not_add_to_accepted_map',
             'core_variant_composition':table+'; complete sequence-to-route combination not verified.',
             'source_completeness':'not_verified','outstanding_checks':['Verify nucleotide strings against original page images and all route correspondences.','Other objects and standard-lattice comparators in the paper remain separately unresolved.'],
             'legacy_record':{},'review_run':'B0003','date':L.DATE,'revision_history':[]}
        L.upsert('design_evidence',row,'Record named source-reviewed design separately from unresolved paper-level scope')
    b=next(b for b in L.read('batches') if b['batch_id']=='B0003')
    b['exclusion_audit']['design_sample']=['RDE0001','RDE0002']
    b['exclusion_audit']['design_findings']='Both newly excluded groups checked in source images: Fig S9 close-packed cross-section and Fig S13 hybrid cross-section; Fig S15 explicitly distinguishes honeycomb, square and hexagonal packing. Paper-level eligibility remains unresolved because standard-lattice comparator provenance is not resolved.'
    b['after_counts']=L.counts();b['validation']=[L.validate()]
    L.upsert('batches',b,'Add two named design exclusions and same-agent source-image audit')
    print(L.validate())

if __name__=='__main__':main()
