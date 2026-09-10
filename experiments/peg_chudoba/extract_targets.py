"""Extract published marker centers from vector PDF, not fitted model outputs.

Requires pymupdf. Plot borders/tick scales were checked against rendered pages.
The conservative digitization bounds do not represent experimental error bars.
"""
import json
from pathlib import Path
import pymupdf


COLORS={(0.0,.551,.28):36,(.09,.35,.66):76,(.961,.49,.14):135,
        (.93,.18,.18):275,(.4,.17,.57):455,(.711,.22,.58):795}


def markers(page):
    seen=set()
    for drawing in page.get_drawings():
        color=drawing['fill'];r=drawing['rect']
        if color is None or not 2<r.width<6 or not 2<r.height<6:
            continue
        color=tuple(round(c,3) for c in color)
        if all(item[0]=='l' for item in drawing['items']):
            points=set(tuple(p) for item in drawing['items'] for p in item[1:])
            x=sum(p[0] for p in points)/len(points)
            y=sum(p[1] for p in points)/len(points)
        else:
            x,y=(r.x0+r.x1)/2,(r.y0+r.y1)/2
        key=(color,round(x,3),round(y,3))
        if key not in seen:
            seen.add(key);yield color,x,y


def main():
    root=Path(__file__).parent
    pdf=pymupdf.open(root/'reference/chudoba_2017_preprint.pdf')
    chain=[];eos=[]
    # Figure 6(a): N axis 5..80; Rg axis 0..2.2 nm.
    for color,x,y in markers(pdf[7]):
        if color==(.09,.35,.66) and x<287.7 and y>60 and not (x>190 and y>110) and not (104<x<110 and y<70):
            n=round(5+(x-91.2639923)/(287.6140137-91.2639923)*75)
            if n in [9,18,27,36,76]:
                chain.append(dict(figure='6a',n=n,temperature_K=294,
                    rg_nm=(205.7449951-y)/(205.7449951-55.394989)*2.2,digitization_bound_nm=.02))
    # Figure 7(b): linear axes 280..400 K, 1..10 nm.
    for color,x,y in markers(pdf[8]):
        if color in COLORS and 92<x<287 and 240<y<323:
            t=280+(x-92.4639969)/194*120
            temperature=min([294,320,347,361,371,381,396],key=lambda k:abs(k-t))
            if abs(t-temperature)<.1:
                chain.append(dict(figure='7b',n=COLORS[color],temperature_K=temperature,
                    rg_nm=1+(322.4389954-y)/113.1000061*9,digitization_bound_nm=.025))
        # Include high-Rg 795-mer markers above y=240; reject legend by x.
        if color==(.711,.22,.58) and 220<y<240 and (abs(x-115.114)<.1 or abs(x-157.114)<.1):
            chain.append(dict(figure='7b',n=795,temperature_K=294 if x<130 else 320,
                rg_nm=1+(322.4389954-y)/113.1000061*9,digitization_bound_nm=.025))
        # Figure 8: log axes c=1..1000 g/L, P=100..1e7 Pa.
        if color in [(.961,.49,.14),(.4,.17,.57),(.93,.18,.18)] and x>380 and 65<y<204:
            n=135 if color==(.961,.49,.14) else 455
            t=371 if color==(.93,.18,.18) else 294
            eos.append(dict(figure='8',n=n,temperature_K=t,
                concentration_g_per_l=10**((x-359.9859924)/189.2500305*3),
                pressure_kpa=10**(2+(203.1450043-y)/138.3000031*5)/1000,
                digitization_relative_bound=.03))
    result=dict(source='arXiv:1710.09191v1, pages 8–9',
        method='Vector marker centers; manually verified plot axes. Bounds are digitization uncertainty only.',
        chain_dimensions=sorted(chain,key=lambda x:(x['figure'],x['n'],x['temperature_K'])),
        osmotic_pressure=sorted(eos,key=lambda x:(x['temperature_K'],x['n'],x['pressure_kpa'])))
    (root/'reference/published_targets.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'Extracted {len(chain)} chain and {len(eos)} pressure markers')


if __name__=='__main__':main()
