"""Review Extrude profile outcomes and intended/observed paths."""
import html
import json
from pathlib import Path


def write_report(directory):
    report = json.loads((directory/'report.json').read_text())
    sections = []
    for trial in report['trials']:
        rows = []
        for name, stage in trial['stages'].items():
            failed = [key for key, ok in trial['checks'].items() if key.startswith(name+'_') and not ok]
            if name in ('paint','erase'):
                outcome = f"Cells {stage['after']}; missing {stage['missing']}; unexpected {stage['unexpected']}"
            else:
                outcome = f"Expected {stage['expected_delta_bp']:+} bp; observed {stage['actual_delta_bp']:+} bp"
            stem = trial['preset']+'-'+name
            rows.append(f'<tr><td>{name}</td><td>{html.escape(outcome)}</td><td>{html.escape(", ".join(failed)) or "PASS"}</td></tr>')
            # Independent world-space desired versus observed path projection.
            samples=stage['samples']; points=[r[k]['position'] for r in samples for k in ('intended','desired','actual')]
            low=[min(p[i] for p in points) for i in (0,1)];span=max(max(p[i] for p in points)-low[i] for i in (0,1)) or 1
            lines=[]
            for key,color,dash in [('intended','#ae8c16','5 4'),('desired','#57a3df',''),('actual','#f033b0','4 3')]:
                coords=' '.join(f'{10+260*(r[key]["position"][0]-low[0])/span:.2f},{280-260*(r[key]["position"][1]-low[1])/span:.2f}' for r in samples)
                lines.append(f'<polyline points="{coords}" stroke="{color}" fill="none" stroke-width="2" stroke-dasharray="{dash}"/>')
            sections.append(f'<details><summary>{stem}: {html.escape(outcome)}</summary><p>Eye images: wide gold intended contact route, narrow magenta actual ray contact on the panel; thin floating lines track controller bodies. Each stage also checks actual pixels after a four-second hold. Plot: gold ideal route, blue simulated input, magenta applied pose; world X/Y projection.</p><svg viewBox="0 0 300 300" width="300">{"".join(lines)}</svg><a href="{stem}/left.png"><img src="{stem}/left.png" width="400"></a><a href="{stem}/right.png"><img src="{stem}/right.png" width="400"></a><p><a href="{stem}/mirror.png">Actual desktop mirror backbuffer</a> · <a href="{stem}/visual-checks.json">Pixel/path/paint/mirror checks</a></p></details>')
        sections.append(f'<h2>{trial["preset"]}</h2><table><tr><th>Stage</th><th>Outcome</th><th>Checks</th></tr>{"".join(rows)}</table>')
    (directory/'report.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>Extrude interface validation</title><style>body{{font:16px system-ui;max-width:1100px;margin:30px auto}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}img{{max-width:45%;vertical-align:top}}details{{margin:14px 0}}summary{{cursor:pointer}}svg{{background:#f4f6fa}}</style><h1>Extrude paint and wheel — profile validation</h1><p>{html.escape(report['scope'])}</p><p>Initial testing: steady_fast. Final validation: all four presets, same seed and geometry. A failed profile is retained as a sensitivity finding; thresholds are not relaxed. One trial per preset is a smoke test, not a population success rate.</p>{''.join(sections)}<p><a href="report.json">Complete poses, timing, cell outcomes and wheel changes</a></p>''')


if __name__=='__main__':
    import sys
    write_report(Path(sys.argv[1]))
