"""Extract Figure 7(b) error-bar endpoints without assuming an error-bar type."""
import hashlib
import json
from pathlib import Path
import pymupdf
from experiments.peg_chudoba.extract_targets import COLORS


def main():
    root=Path(__file__).parent/'reference';source=root/'chudoba_2017_preprint.pdf'
    page=pymupdf.open(source)[8]
    targets=json.loads((root/'published_targets.json').read_text())['chain_dimensions']
    targets={(r['n'],r['temperature_K']):r for r in targets if r['figure']=='7b'}
    results=[]
    for drawing in page.get_drawings():
        color=drawing['color']
        if color is None or drawing['fill'] is not None:continue
        n=COLORS.get(tuple(round(x,3) for x in color))
        if n is None:continue
        for item in drawing['items']:
            if item[0]!='l':continue
            a,b=item[1:]
            if abs(a.x-b.x)>1e-5 or not 100<a.x<282 or not 209<a.y<323 or not 209<b.y<323:continue
            if abs(a.y-b.y)<.05:continue
            raw_t=280+(a.x-92.4639969)/194*120
            t=min([294,320,347,361,371,381,396],key=lambda k:abs(k-raw_t))
            if abs(t-raw_t)>.1:continue
            target=targets.get((n,t))
            if target is None:continue
            ends=sorted(1+(322.4389954-y)/113.1000061*9 for y in (a.y,b.y))
            # Triangle glyph centroids differ slightly from the plotted data center.
            if abs(sum(ends)/2-target['rg_nm'])>.025:continue
            results.append(dict(n=n,temperature_K=t,figure='7b',lower_nm=ends[0],upper_nm=ends[1],
                marker_nm=target['rg_nm'],half_width_nm=(ends[1]-ends[0])/2,digitization_bound_nm=.025))
    assert len({(r['n'],r['temperature_K']) for r in results})==len(results)==42
    report=dict(source='arXiv:1710.09191v1 Figure 7(b)',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        method='Vertical vector segments centered on independently digitized colored markers; axis scale verified against rendered page.',
        interpretation='Published plotted intervals. Error-bar type not specified in accessed preprint; do not treat these as SEM or confidence intervals.',
        intervals=sorted(results,key=lambda r:(r['n'],r['temperature_K'])))
    (root/'published_chain_intervals.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Extracted',len(results),'published intervals')
    for r in results:
        if r['n'] in (275,795) and r['temperature_K']==320:print(r)


if __name__=='__main__':main()
