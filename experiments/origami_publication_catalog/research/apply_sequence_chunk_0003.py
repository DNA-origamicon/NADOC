"""Save inspected first-source decisions for frozen balanced SEQ0003 inputs."""
import json
import re
import subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence


def main():
    keys=json.loads((L.HERE/'sequence_chunk_0003_keys.json').read_text())
    rows={p['registry_key']:p for p in L.read('publication_reviews')}
    assert keys[:5]==['10.1038/srep12257','10.1038/srep15634','10.1038/ncomms9634','10.1038/ncomms10591','10.1038/ncomms10619']
    notes=[
        ('no_qualifying_table_found','Saved DOCX word/document.xml inspected: Supplementary TableS1 concerns topographic cues and magnets, not DNA staples. No qualifying sequence list found. Embedded media not exhaustively transcribed; no design/relevance exclusion inferred.'),
        ('prioritize','SI PDF6-8 TableS3 explicitly lists 163 double-triangle staples; 163 start/end-position rows confirmed. TableS4 PDF10-12 separately lists141 staples for60HB. No combined-table count used.'),
        ('no_qualifying_table_found','Saved16-page SI: only Supplementary Table1, PDF8-9, contains amplification/nicking primers, not a100-entry origami staple table. PDF9 primer rows inspected;26long candidate strings are not a complete staple list. Other sources not exhausted; move on.'),
        ('prioritize','SI PDF18-22 Supplementary Table1 is the origami-template staple list. 140 core-staple rows alone meet threshold; separate handles and azobenzene-modified strands retain their chemistry. Source gate only, no complete-set claim.'),
        ('prioritize','SI Supplementary Note4 PDF69-74: SH Full-Cage-Left section contains210position-labelled strand rows before SH-right section begins. Other cage lists not summed. Source gate only; full/half-cage naming and variants await review.')]
    report=[]
    for i,key in enumerate(keys):
        p=rows[key];legacy=p['legacy_record']
        if p.get('source_triage',{}).get('run_id')=='SEQ0003':
            report.append(dict(registry_key=key,**p['source_triage']));continue
        if i<5:
            decision,note=notes[i];s=legacy['downloaded_supplements'][0]
            ev=evidence(L.ROOT/'assets'/s['local_file'],s['url'],note)
        else:
            assert not legacy.get('downloaded_supplements') and not legacy.get('supplement_links') and not legacy.get('xml_file') and not legacy.get('repository_links') and not p.get('evidence')
            decision='no_qualifying_table_found'
            note='No qualifying table found in saved source inventory: no downloaded supplements, supplement links, fulltext XML, repositories or publication evidence recorded. Availability unknown, not proven absence. Move on without rescue retrieval.'
            ev=evidence(L.ROOT/'publication_registry.json','',key+': '+note)
        triage=dict(run_id='SEQ0003',decision=decision,threshold=100,note=note,evidence=[ev],source_coverage='Inspected readily available saved sources and registry links only; not an exhaustive publisher/repository search.',date=L.DATE,reopen_condition='New source evidence or explicit user request only')
        p['source_triage']=triage
        assert p['review_stage']=='unreviewed'
        p.update(review_stage='metadata_screened',reviewer='Codex first-source screening with table context inspection',run_id='SEQ0003',date=L.DATE,rationale=note,access='saved_supplement_inspected' if i<5 else 'source_availability_unknown')
        p['evidence'].append(ev)
        p['unresolved_questions'].append('Source gate only; relevance and design identity not adjudicated. Failed/unknown gates inactive until new evidence or user request.')
        L.upsert('publication_reviews',p,'Record source gate without inferring molecular relevance from availability')
        report.append(dict(registry_key=key,**triage))
    validation=L.validate();summary=dict(Counter(r['decision'] for r in report))
    out=dict(run_id='SEQ0003',records=report,summary=summary,selection='Five available-source and five low-signal year-rotated records; not a representative corpus sample.',validation=validation,limitations='Counts are source-screen decisions, not article reviews or verified designs. No measured end-to-end speedup; parser time excludes manual inspection. DOCX inspected outside PDF-only index.',exclusion_audit={'final_scientific_exclusions':0,'same_agent_second_pass':'ncomms9634 PDF9 primer identities and16-page SI scope rechecked; no qualifying staple list in inspected file. Retain relevant-design uncertainty.'})
    L.atomic(L.HERE/'sequence_chunk_0003_report.json',json.dumps(out,indent=2)+'\n')
    b=next(b for b in L.read('batches') if b['batch_id']=='SEQ0003')
    b.update(status='completed',after_counts=L.counts(),completed_actions=['First-source screening of all10 frozen inputs:3prioritize,7inactive no qualifying table found; no deep-review or design completion claim.'],validation=[validation],exclusion_audit=out['exclusion_audit'],unresolved_keys=[r['registry_key'] for r in report if r['decision']!='prioritize'],next_queue=[r['registry_key'] for r in report if r['decision']=='prioritize'])
    L.upsert('batches',b,'Complete screening batch and retain three qualifying review candidates')
    print(json.dumps(dict(summary=summary,validation=validation)))

if __name__=='__main__':main()
