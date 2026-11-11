"""Freeze five available-source records plus five low-signal year-rotated records."""
import json
import ledger as L

def main():
    out=L.HERE/'sequence_chunk_0003_keys.json'
    if out.exists():
        print(out.read_text());return
    rows=[p for p in L.read('publication_reviews') if p['review_stage']=='unreviewed' and not p.get('source_triage') and not p.get('run_id','').startswith('fnano-') and 'patent' not in str(p.get('publication_type',[])).lower()]
    acquired=[p for p in rows if p.get('legacy_record',{}).get('downloaded_supplements')][:5]
    low=[p for p in rows if p.get('legacy_record',{}).get('key') and not p['legacy_record'].get('downloaded_supplements') and not p['legacy_record'].get('sequence_evidence') and not p['legacy_record'].get('design_evidence')]
    picked=[];years=set()
    for p in low:
        year=str(p['legacy_record'].get('first_publication_date',''))[:4]
        if year not in years:
            picked.append(p);years.add(year)
        if len(picked)==5:break
    assert len(picked)==5
    keys=[p['registry_key'] for p in acquired+picked]
    L.atomic(out,json.dumps(keys,indent=2)+'\n')
    L.upsert('batches',dict(batch_id='SEQ0003',date=L.DATE,status='in_progress',input_keys=keys,selection='First five unreviewed records with saved supplements plus five records without prior sequence/design evidence from distinct publication years, in stable ledger order. Availability-balanced workflow sample, not random corpus estimate.',completed_actions=[],before_counts=L.counts(),after_counts=None,exclusion_audit={'sample':[],'reason':'No final exclusions yet'},validation=[],unresolved_keys=[],next_queue=['Inspect source inventories; apply threshold before deep review.'],revision_history=[]),'Freeze balanced source-screen inputs')
    print(json.dumps(keys))
if __name__=='__main__':main()
