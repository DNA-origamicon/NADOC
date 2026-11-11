"""Resume public primary-source acquisition for the rotated B0008 remainder."""
from acquire_sources import fetch
SOURCES = [
 ('https://pubs.rsc.org/en/content/getauthorversionpdf/C3CC41707G', 'wang-2013-rna-author.pdf'),
 ('https://www.rsc.org/suppdata/cc/c3/c3cc41707g/c3cc41707g.pdf', 'wang-2013-rna-si.pdf'),
 ('https://link.springer.com/chapter/10.1007/978-3-642-36077-0_10', 'liu-fan-2013-chapter.html'),
 ('https://api.crossref.org/works/10.1080/07391102.2013.786383', 'nanophotonic-2013-crossref.json'),
 ('https://api.crossref.org/works/10.1016/j.bpj.2012.11.019', 'kauert-2013-crossref.json'),
 ('https://www.nature.com/articles/ncomms2690', 'shen-2013-graphene.html'),
 ('https://www.rsc.org/suppdata/cc/c2/c2cc37257f/c2cc37257f.pdf', 'raab-2013-crystallization-si.pdf'),
 ('https://pubs.rsc.org/en/content/articlelanding/2013/cc/c2cc37257f', 'raab-2013-crystallization.html'),
]
if __name__ == '__main__':
 for url,name in SOURCES:
  print(name,fetch(url,name),flush=True)
