"""Write an inspectable cluster report with hoverable recording-level points."""
import argparse
import html
import json
from pathlib import Path

COLORS = ['#2271b3', '#d14900', '#12815a', '#904ab0']


def write_report(directory):
    summary = json.loads((directory/'clusters.json').read_text())
    rows = json.loads((directory/'assignments.json').read_text())
    good = [r for r in rows if r['cluster'] is not None]
    xmax = max(r['features']['speed_median_m_s'] for r in good)*1.05
    ymax = max(r['features']['acceleration_median_m_s2'] for r in good)*1.05
    points = []
    for r in good:
        f = r['features']; c = r['cluster']
        x = 70+700*f['speed_median_m_s']/xmax
        y = 440-380*f['acceleration_median_m_s2']/ymax
        title = html.escape(f"{r['id']} | cluster {c} | speed {f['speed_median_m_s']:.3f} m/s | acceleration {f['acceleration_median_m_s2']:.2f} m/s² | tracked {r['quality']['tracked_fraction']:.1%}")
        points.append(f'<circle data-cluster="{c}" cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{COLORS[c%4]}" opacity=".55"><title>{title}</title></circle>')
    table = []
    for c in summary['clusters']:
        f = c['median_raw_features']
        table.append(f'<tr><td>{c["cluster"]}</td><td>{c["recording_hands"]}</td><td>{f["speed_median_m_s"]:.3f}</td><td>{f["pause_fraction"]:.1%}</td><td>{f["acceleration_median_m_s2"]:.2f}</td><td>{f["turning_median_deg"]:.1f}</td></tr>')
    controls = ''.join(f'<label style="color:{COLORS[c%4]}"><input type="checkbox" checked onchange="document.querySelectorAll(\'[data-cluster=&quot;{c}&quot;]\').forEach(p=>p.style.display=this.checked?\'\':\'none\')">Cluster {c}</label> ' for c in range(summary['k']))
    text = html.escape(summary['scope'])
    (directory/'report.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>Controller motion clusters</title>
<style>body{{font:16px system-ui;max-width:1050px;margin:32px auto;color:#182530;background:#fafbfd}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}svg{{background:white;max-width:100%}}pre{{white-space:pre-wrap}}circle:hover{{r:8;opacity:1}}</style>
<h1>Exploratory controller motion profiles</h1><p>{text}</p>
<p>{summary['recordings']} recordings × two hands; {summary['eligible']} qualified, {summary['excluded']} excluded. Fixed four-cluster exploration, not evidence that four natural populations exist. Silhouette: {summary['silhouette']:.3f}. Seed agreement (adjusted Rand): {min(summary['seed_stability_adjusted_rand']):.3f}–{max(summary['seed_stability_adjusted_rand']):.3f}.</p>
<p>{controls}</p><svg viewBox="0 0 820 500" width="820"><path d="M70 55 V440 H780" fill="none" stroke="#333"/>{''.join(points)}<text x="250" y="485">Median head-relative speed (m/s; 0 to {xmax:.2f})</text><text x="15" y="30">Median acceleration (m/s²; 0 to {ymax:.1f})</text></svg>
<p>Hover a point for its source recording. Plot uses raw measurements; clustering adjusts for task and hand. Acceleration also contains head-motion, timing and sensor effects: lower is not automatically better.</p>
<table><tr><th>Cluster</th><th>Recording-hands</th><th>Speed m/s</th><th>Paused &lt;0.05m/s</th><th>Acceleration m/s²</th><th>Turning °</th></tr>{''.join(table)}</table>
<p>Quality gate: ≥95% tracked, ≥90% valid intervals, ≤1% position jumps over 25cm, ≥100 valid intervals and enough moving pairs. Valid intervals require consecutive frame numbers and 0&lt;dt≤100ms. No derivatives bridge rejected intervals. Subtract head translation to remove shared locomotion. No known intended path means these data do not establish aiming accuracy or corrective intent.</p>
<p>Normalization: {html.escape(summary['normalization'])}. {summary['small_task_hand_groups']} task/hand groups have fewer than three qualified examples; comparisons there are particularly weak. Participants are not independent recordings; no held-out-person generalization has been established.</p>
<p><a href="clusters.json">Centers and representative recordings</a> · <a href="assignments.json">All measurements and quality flags</a> · <a href="https://stanfordvl.github.io/behavior/vr_demos.html">Dataset collection details (five participants)</a></p>''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    write_report(parser.parse_args().directory)


if __name__ == '__main__':
    main()
