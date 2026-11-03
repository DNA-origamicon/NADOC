import urllib.request,urllib.parse,json
from pathlib import Path
out=Path('experiments/origami_publication_catalog/assets/sources/pre2020-expansion');items=[];logs=[]
for q in ['DNA origami','scaffolded DNA nanostructures']:
 url='https://api.crossref.org/works?'+urllib.parse.urlencode({'query.title':q,'filter':'until-pub-date:2019-12-31,from-pub-date:2000-01-01','rows':1000,'select':'DOI,title,published,link,type,relation,URL'})
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'NADOC-literature-research'}),timeout=90) as r:d=json.load(r)
  got=d['message']['items'];items+=got;logs.append({'query':q,'url':url,'returned':len(got),'total_results':d['message']['total-results'],'limit_note':'Relevance-limited discovery, not an exhaustive Crossref enumeration'})
 except Exception as e:logs.append({'query':q,'error':str(e)})
(out/'crossref.json').write_text(json.dumps(items));(out/'crossref_queries.json').write_text(json.dumps(logs,indent=2));print(logs)
