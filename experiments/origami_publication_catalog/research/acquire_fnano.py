"""Restore official schedule links actually present in retained FNANO overview.
No guessed URLs; download is not content review or conference-year closure.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin
import ledger as L
from acquire_sources import fetch
from review_batch_0001 import evidence


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls=[]
    def handle_starttag(self, tag, attrs):
        if tag=='a' and 'href' in dict(attrs):self.urls.append(dict(attrs)['href'])


def main():
    url='https://www2.cs.duke.edu/fnano/overview.html'
    result=fetch(url,'fnano-overview.html')
    if result['status']!='available':raise RuntimeError(result)
    source=L.ROOT/result['local_file'];parser=Links();parser.feed(source.read_text())
    found={}
    for link in parser.urls:
        match=re.search(r'/FNANO(\d\d)schedule\.pdf$',link)
        if match and 2006<=2000+int(match[1])<=2019:
            found[2000+int(match[1])]=urljoin(url,link)
    for year,link in sorted(found.items()):
        result=fetch(link,f'FNANO{str(year)[2:]}schedule.pdf')
        row=next(r for r in L.read('discovery_runs') if r['run_id']==f'fnano-{year}')
        row['source_url']=link
        row['evidence']=[evidence(source,url,'Official schedules table; actual hyperlink for '+str(year))]
        if result['status']=='available':
            row['evidence'].append({**result,'locator':'Entire schedule; acquisition verified, content review separately tracked'})
            row.update(closure_state='in_progress',retrieved_count=1,
                       checkpoint='Schedule retained and hashed. '+('Only p.1 reviewed; four leads recorded. ' if year==2019 else 'Content not yet reviewed. ')+'Locate abstract book and reconcile presentation leads.')
            if year!=2019:row['pagination']={'pages_reviewed':[],'page_total':'not_indexed'}
        else:
            row['failures']=row.get('failures',[])+[result]
            row.update(closure_state='blocked',checkpoint='Official linked schedule failed; try alternate archive while other years proceed.')
        L.upsert('discovery_runs',row,'Acquire actual official overview schedule link; no coverage closure claimed')
        print(year,result['status'],flush=True)


if __name__=='__main__':main()
