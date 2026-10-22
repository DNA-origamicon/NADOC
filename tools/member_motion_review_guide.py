"""Add a narrated, offline review to an existing sequence audit; never alter geometry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def write_guide(root: Path) -> Path:
    cases = []
    for path in sorted(root.glob('phase-*.json')):
        data = json.loads(path.read_text())
        case = data['case']
        if not case.get('sequence') or not case.get('partial'):
            raise ValueError('This guide describes partial-domain sequence audits only')
        trace = data['event_trace']
        keys = trace[0]['material_keys']
        junctions = [j for j in data['junctions'] if max(j['endpoint_displacement_nm']) > 1e-6]
        cases.append(dict(
            name=path.stem, case=case, keys=keys, trace=trace,
            displacement=data['displacement']['max_nm'], junctions=junctions,
            history=[dict(id=e['id'], kind=e.get('feature_type'), op=e.get('op_kind'))
                     for e in data['current_design']['feature_log']],
        ))
    if not cases:
        raise ValueError('No sequence audit cases found')
    payload = json.dumps(cases).replace('<', '\\u003c')
    output = root / 'guided-review.html'
    output.write_text(PAGE.replace('__CASES__', payload))
    return output


PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Move/Rotate — guided feature-order review</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101722;color:#e4ebf5;font:15px/1.45 system-ui}
main{display:grid;grid-template-columns:440px 1fr;height:100vh}aside{overflow:auto;padding:22px;border-right:1px solid #516179}
h1{font-size:23px;margin:0 0 12px}h2{font-size:17px;margin:20px 0 8px}p{margin:8px 0 12px}
select,button{font:inherit;background:#26364d;color:white;border:1px solid #8092ac;padding:8px;width:100%;margin:4px 0}
li{margin:9px 0}ol,ul{padding-left:24px}.focus{background:#25394b;padding:12px;border-left:4px solid #7bcaff}
small{color:#b6c8dd}iframe{border:0;width:100%;height:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
table{border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #516179;padding:6px;text-align:left}
@media(max-width:900px){main{grid-template-columns:1fr;height:auto}aside{max-height:55vh}iframe{height:90vh}}
</style><main><aside>
<h1>Move/Rotate: what should the feature order mean?</h1>
<p><b>Current</b> uses existing native placement owners and residue transforms.
<b>Candidate</b> uses an isolated program that applies group moves in event order.
These are final states after the same intended operations, not before/after a single drag.</p>
<div class="focus"><b>Decision to review:</b> Should resetting/replacing a base's own pose
preserve the independent group moves, with the second group move acting on the base's
already-replaced position? Look at the one displaced base and its connection to its neighbor.
The other material should stay coincident.</div>
<label for="case"><h2>Choose evidence case</h2></label><select id="case"></select>
<button id="control">Compare with / without the earlier base pose</button>
<p id="selection"></p>
<h2>How this model was built</h2>
<p>This is a synthetic two-helix honeycomb fixture, 8 base pairs long, with no adjacent
ligation. Roll the first helix by the selected phase, then nick the selected strand at
base-pair index 3. Two overlapping candidate groups select the same nicked domain;
the union moves each selected residue once. The current path targets that domain through native owners.</p>
<h2>Feature sequence → both final states</h2>
<small>Coordinates and translations below are in nm. Base-pair indices are zero-based.</small>
<ol>
<li id="prior"></li>
<li><b>First group move:</b> rotate Z +90° around (2, −1, 0.5), then translate (−0.5, 1, 2).
Current: placement owner. Candidate: independent world-space move of the selected members.</li>
<li><b>Move base 3:</b> add translation (3, −2, 1) to its saved pose.</li>
<li><b>Reset base 3:</b> delete its saved residue pose, including the earlier base-only edits.
Candidate retains both independent group operations in the final replay.</li>
<li><b>Replace base 3 pose:</b> rotate Y +37° around (−2, 3, 0.7), translate (1, 2, −0.5).</li>
<li><b>Second group move:</b> rotate X −25° around (1, −0.5, 0.3), translate (0.4, −0.2, 0.6).
Current adds another owner. Candidate moves the members as positioned after the replacement.</li>
<li><b>Move base 3 again:</b> add translation (3, −2, 1).</li>
</ol>
<h2>What to look at</h2>
<p>Current and Candidate share world coordinates. Difference shows the displaced atoms;
Defects provides local inspection. Use the Full / Ball and Stick controls in each panel.
The guide stays visible while you rotate or zoom the models.</p>
<p id="delta"></p><table><thead><tr><th>Bond (chain/residue)</th><th>Current nm</th><th>Candidate nm</th></tr></thead><tbody id="bonds"></tbody></table>
<p>The long connection is deliberately stressed by large moves in this ordering probe.
A shorter bond does not make the candidate physically acceptable. The question is whether
the operation sequence produces the intended placement.</p>
<h2>Scope of a decision</h2>
<p>144 cases: 36 actual source rolls (0–350°, step 10°), both strand directions, and with/without
the earlier base pose. Reset should make those last two variants converge. Atom/bond identities
and all unselected material are verified unchanged between each pair.</p>
<p>This can authorize the demonstrated ordering rule only. Construction of new material,
shared construction frames, tails and constrained companions remain unresolved; this is
not approval to declare Move/Rotate complete. No production geometry is changed.</p>
<details><summary>Exact native feature IDs and candidate event trace</summary>
<p>The candidate is a detached diagnostic program, not a saved native feature history.
The nick is fixture preparation; the native log below does not list it as an authored feature.</p><pre id="trace"></pre></details>
</aside><iframe id="viewer" title="Current, Candidate, Difference and Defects"></iframe></main>
<script>
const cases=__CASES__, select=document.querySelector('#case');
for(const c of cases){const o=document.createElement('option');o.value=c.name;o.textContent=c.name;select.append(o)}
function show(){const c=cases.find(c=>c.name===select.value);
 document.querySelector('#viewer').src=c.name+'.html';
 document.querySelector('#selection').textContent=`Selected: ${c.case.direction.toLowerCase()} strand of ${c.case.selected_helix_id}, base-pair indices ${c.keys.map(k=>k[1]).join(', ')}. Phase ${c.case.phase_deg}°.`;
 document.querySelector('#prior').textContent=c.case.prior_pose?'Earlier base-only pose: rotate base 3 about X +90° around (1, 2, 3), then translate (0.25, −0.5, 0.75).':'Control: skip the earlier base-only pose.';
 document.querySelector('#delta').textContent=`Largest atom displacement: ${c.displacement.toFixed(3)} nm. Changed inter-residue connections:`;
 const body=document.querySelector('#bonds');body.replaceChildren();
 for(const j of c.junctions){const tr=document.createElement('tr');for(const text of [j.residues.map(r=>r.join('')).join(' → '),j.current_length_nm.toFixed(3),j.candidate_length_nm.toFixed(3)]){const td=document.createElement('td');td.textContent=text;tr.append(td)}body.append(tr)}
 document.querySelector('#trace').textContent=JSON.stringify({native_feature_log:c.history,candidate_events:c.trace},null,2);
}
select.onchange=show;document.querySelector('#control').onclick=()=>{select.value=select.value.endsWith('-N')?select.value.slice(0,-2)+'-control':select.value.slice(0,-8)+'-N';show()};show();
</script></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_directory', type=Path)
    args = parser.parse_args()
    print(write_guide(args.review_directory.resolve()))
