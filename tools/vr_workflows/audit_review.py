"""Small offline browser for the exported audit tables; no averaged FPS scores."""
import json


def write_review(path, data, target_hz, captures=()):
    payload=json.dumps({**{key:data.get(key,[]) for key in ('coverage','intervals','sessions','operations')},'captures':captures},separators=(',',':')).replace('<','\\u003c')
    page='''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Full-size 24HB VR audit</title>
<style>
body{font:15px system-ui,sans-serif;color:#172330;background:#f7f9fb;margin:24px}
h1{font-size:25px;margin-bottom:8px}p{max-width:1100px;line-height:1.5}
label{display:inline-block;margin:6px 14px 6px 0}select,button{font:inherit;padding:6px}
table{border-collapse:collapse;background:white;width:100%;font-size:13px}
th,td{padding:9px;text-align:left;border-bottom:1px solid #dbe2e8;vertical-align:top}
th{background:#e9eff5;position:sticky;top:0}td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.fail{color:#9b2530}.pass{color:#176942}.muted{color:#506070}.scroll{overflow:auto;max-height:65vh}
button{margin:8px 12px 8px 0}a{color:#174b86}#count{margin:12px 0}
#captures{display:flex;flex-wrap:wrap;gap:12px}figure{margin:12px 0}figure img{width:240px;max-width:100%;background:black}figcaption{font-size:13px}
</style>
<h1>Full-size 24HB VR audit</h1>
<p>24 helices · 76 strands · 6,720 nucleotides · <strong>__HZ__ Hz target</strong>.
Physical OpenXR sessions with synthetic controller profiles; not human wearer trials.
Failed workflows retain useful measurements. A passing workflow can still miss its frame budget.</p>
<p>Representation identifies the main native scene. View tools and MD results can replace it with their own display stream;
see override flags in the CSV and captured state. Earlier intervals lack boundary override flags.</p>
<p>Native tool is the tool-shell mode; auxiliary controls also require captured state.
Stationary setup windows can precede tool activation. A workflow label alone does not prove an edit occurred.</p>
<p>FPS is application submission cadence, not headset scanout. GPU duration is the compositor's m_flPreSubmitGpuMs span,
not isolated shader execution or GPU utilization. Scheduling can include other processes' work; do not add CPU and GPU values.
Compositor statistics cover the whole named interval, including any native style/tool transitions within it.
Work p95 subtracts named runtime waits from outer wall time; it is not pure CPU execution.
Intervals can overlap: do not sum their frames or compositor counters. Whole-session tables retain boundary stalls and capture overhead.</p>
<p><a href="index.json">Source, target budget and dataset index</a></p><p id="downloads"></p>
<details><summary>Representative baseline mirror captures</summary><p>Captured outside measured intervals. These show submitted images, not physical headset visibility. Original capture paths and hashes are in <a href="captures.json">captures.json</a>.</p><div id="captures"></div></details>
<label>Table <select id="table"><option value="intervals">Measured intervals</option><option value="coverage">Workflow coverage</option><option value="sessions">Whole sessions (includes captures)</option><option value="operations">Operation waits / failures</option></select></label>
<label>Representation <select id="rep"><option value="">All</option></select></label>
<label>Tool <select id="tool"><option value="">All</option></select></label>
<label>Profile <select id="profile"><option value="">All</option></select></label>
<label id="kind-label">Intervals <select id="kind"><option value="overview">Baseline + stationary</option><option value="">All measured intervals</option><option value="commits">Commit / feedback</option><option value="reach">Controller reaches</option></select></label>
<label id="attempt-label"><input id="attempts" type="checkbox">Include earlier attempts</label>
<div id="count" aria-live="polite"></div><div class="scroll"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<button id="previous">Previous 100</button><button id="next">Next 100</button>
<p class="muted">Missing values are shown as —. Coverage selects the latest chronological attempt, not the best result.
Earlier attempts can have different observation setup and runtime conditions; consult campaign paths and host counters before comparing them.
Raw log/capture paths in the CSVs refer to the retained host archive and are not bundled with this compact review.</p>
<script id="data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent);
const get=id=>document.getElementById(id),fmt=n=>n==null?'—':Number(n).toFixed(2);
const latest=new Set(data.coverage.map(r=>r.latest_campaign+'|'+r.latest_case));
let page=0,filtered=[];
for(const capture of data.captures){
 const figure=document.createElement('figure'),link=document.createElement('a'),img=document.createElement('img'),caption=document.createElement('figcaption');
 link.href=capture.file;img.src=capture.file;img.loading='lazy';img.alt='Full-size 24HB baseline: '+capture.representation;
 caption.textContent=capture.representation;link.append(img);figure.append(link,caption);get('captures').append(figure);
}
for(const file of ['runs','coverage','intervals','calculations','phases','operations','sessions','session_calculations','session_phases']){
 const a=document.createElement('a');a.href=file+'.csv';a.textContent=file+'.csv';get('downloads').append(a,' · ');
}
for(const [id,values] of [['rep',['full','stick','ballstick','surface']],['tool',[...new Set([...data.intervals,...data.coverage].map(r=>r.tool))].sort()],['profile',['steady_fast','steady_deliberate','variable_fast','variable_deliberate']]]){
 for(const value of values){const o=document.createElement('option');o.value=value;o.textContent=value;get(id).append(o);}
}
function render(){
 const mode=get('table').value,coverage=mode==='coverage',operations=mode==='operations';
 get('kind-label').hidden=mode!=='intervals';get('attempt-label').hidden=coverage;
 filtered=data[mode].filter(r=>{
  const rep=operations?r.requested_representation:r.representation;
  if(get('rep').value&&rep!==get('rep').value)return false;
  if(get('tool').value&&r.tool!==get('tool').value)return false;
  if(get('profile').value&&(r.case==='baseline'?!r.interval.includes('-'+get('profile').value+'-'):r.profile!==get('profile').value))return false;
  if(coverage)return true;
  if(!get('attempts').checked&&r.case!=='baseline'&&!latest.has(r.campaign+'|'+r.case))return false;
  if(mode!=='intervals')return true;
  const kind=get('kind').value,k=r.interval_kind||'';
  return !kind||(kind==='overview'&&(r.case==='baseline'||k.startsWith('stationary')))||(kind==='commits'&&(k.endsWith('-commit')||k.endsWith('-feedback')))||(kind==='reach'&&k==='reach');
 });
 const columns=coverage?['Tool','Representation','Profile','Attempts','Latest workflow','Latest audit','Trace valid','Frames in requested style¹','Reached commit intervals','Latest failure']:operations?
 ['Workflow / profile','Requested style','Observed main style','Operation','Span ms','Error','Workflow result','Span definition']:
 ['Workflow / profile','Native tool','Representation','Interval','Workflow result','Trace valid','Frames¹','Application FPS','Work p95 ms','GPU p95 ms','Work > target','Outer max ms'];
 get('head').replaceChildren();const tr=document.createElement('tr');
 for(const name of columns){const th=document.createElement('th');th.textContent=name;tr.append(th);}get('head').append(tr);
 get('body').replaceChildren();page=Math.min(page,Math.max(0,Math.ceil(filtered.length/100)-1));
 for(const r of filtered.slice(page*100,(page+1)*100)){
  const passed=coverage?r.latest_workflow_passed:r.workflow_passed;
  const cells=coverage?[r.tool,r.representation,r.profile,r.attempts,passed?'Passed':'Failed',r.latest_audit_passed,r.latest_trace_valid,r.latest_requested_representation_frame_rows,r.latest_reached_commit_intervals,r.latest_failure]:operations?
   [r.tool+' / '+r.profile,r.requested_representation,r.observed_representation,r.kind,fmt(r.latency_ms),r.error,passed?'Passed':'Failed',r.latency_definition]:
   [r.tool+' / '+r.profile,r.native_tool,r.representation,r.interval,passed?'Passed':'Failed',r.trace_valid,r.frames,fmt(r.application_submission_fps),fmt(r.non_runtime_wait_wall_ms_p95),fmt(r.gpu_ms_p95),r.non_runtime_wait_over_target_budget_frames,fmt(r.outer_wall_ms_maximum)];
  const row=document.createElement('tr');row.title=coverage?r.latest_campaign:r.campaign+(r.interval_error?' · '+r.interval_error:'');
  cells.forEach((value,i)=>{const td=document.createElement('td');td.textContent=value??'—';if(i===(operations?6:4))td.className=passed?'pass':'fail';else if(operations&&i===5&&r.error)td.className='fail';else if(!coverage&&!operations&&i>=6)td.className='num';row.append(td);});get('body').append(row);
 }
 get('count').textContent=filtered.length+' matching rows · page '+(page+1)+' of '+Math.max(1,Math.ceil(filtered.length/100))+(operations?' · Failed spans end at the error, not acknowledgement.':mode==='sessions'?' · Includes captures, setup and waits; not a clean FPS gate.':' · ¹ Interval frame rows may overlap.');
 get('previous').disabled=page===0;get('next').disabled=(page+1)*100>=filtered.length;
}
for(const id of ['table','rep','tool','profile','kind','attempts'])get(id).addEventListener('change',()=>{page=0;render();});
get('previous').onclick=()=>{page--;render();};get('next').onclick=()=>{page++;render();};render();
</script></html>'''
    path.write_text(page.replace('__HZ__',str(target_hz)).replace('__DATA__',payload))
