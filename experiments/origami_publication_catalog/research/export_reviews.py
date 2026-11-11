"""Readable projections of durable reviews; never a decision authority."""
import csv
import io
import json
import ledger as L


def main():
    buffer=io.StringIO();writer=csv.writer(buffer)
    writer.writerow(['key','legacy_or_research_id','doi','title','review_stage','relevance','catalog_eligibility','contributions','run','evidence_locations','unresolved_questions'])
    for r in L.read('publication_reviews'):
        if r['review_stage']=='unreviewed':continue
        writer.writerow([r['registry_key'],r.get('registry_id'),r['doi'],r.get('title') or r.get('legacy_record',{}).get('publication',''),r['review_stage'],r['relevance'],r['catalog_eligibility'], '; '.join(r['design_contributions']),r['run_id'],'; '.join(e.get('url','')+' | '+e.get('locator','') for e in r['evidence']),'; '.join(r['unresolved_questions'])])
    L.atomic(L.HERE/'reviewed_records.csv',buffer.getvalue())
    L.atomic(L.HERE/'counts.json',json.dumps(L.counts(),indent=2)+'\n')


if __name__=='__main__':main()
