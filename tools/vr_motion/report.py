"""Standalone, dependency-free review page for retained live VR measurements."""
import html
import json


def write_report(directory, report):
    escape = html.escape
    checks = ''.join(f'<tr><td>{escape(name)}</td><td>{"PASS" if ok else "FAIL"}</td></tr>'
                     for name, ok in report['checks'].items())
    rows = report.get('path', {}).get('samples', [])
    plots = []
    for hand in ('left', 'right'):
        samples = [r for r in rows if r['hand'] == hand]
        if not samples:
            continue
        points = [r[k]['position'] for r in samples for k in ('desired', 'actual')]
        low = [min(p[i] for p in points) for i in (0, 1)]
        span = max(max(p[i] for p in points)-low[i] for i in (0, 1)) or 1
        lines = []
        for key, color, dash in [('desired', '#008cba', ''), ('actual', '#ef7800', '5 4')]:
            coords = ' '.join(f'{20+260*(r[key]["position"][0]-low[0])/span:.3f},{280-260*(r[key]["position"][1]-low[1])/span:.3f}' for r in samples)
            lines.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}"/>')
        plots.append(f'<figure><figcaption>{hand}: world X/Y projection</figcaption><svg viewBox="0 0 300 300" width="300">{"".join(lines)}</svg></figure>')
    pictures = ''.join(f'<figure><figcaption>{name}, {eye} eye</figcaption><img src="{name}/{eye}.png" width="440"></figure>'
        for name in ('controllers-visible', 'controllers-offscreen', 'menu-target', 'menu-result')
        if (directory/name).exists() for eye in ('left', 'right'))
    summary = {k: v for k, v in report.items() if k != 'path'}
    summary['path_summary'] = {k: v for k, v in report.get('path', {}).items() if k != 'samples'}
    (directory/'report.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>VR interface validation</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:32px auto;background:#f6f7fa;color:#17202a}}figure{{display:inline-block;margin:12px}}td{{padding:6px 16px;border-bottom:1px solid #ccc}}pre{{white-space:pre-wrap}}img{{max-width:100%}}</style>
<h1>VR interface validation: {"PASS" if report['passed'] else "FAIL"}</h1>
<p>{escape(report['scope'])}</p><table>{checks}</table>
<h2>Requested and observed paths</h2><p>Blue solid: requested. Orange dashed: observed after a frame barrier. Overlap indicates agreement. These are frame-paced samples, not a latency benchmark.</p>{''.join(plots)}
<h2>Submitted eye evidence</h2>{pictures}<h2>Measurements</h2><pre>{escape(json.dumps(summary, indent=2))}</pre>
<p><a href="report.json">Complete measurements and per-sample paths</a></p>''')
