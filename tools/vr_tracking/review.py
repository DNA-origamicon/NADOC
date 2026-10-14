"""Standalone original-frame review; overlays never modify exported pixels."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


def write_review(output_dir: str | Path, report: Mapping[str, Any]) -> Path:
    """Write index.html beside parent-owned results.json/manifest.json/images.

    Each frame uses image_file relative to output_dir, source metadata, groups
    of per-eye track_landmarks results, and optional expected entries keyed by
    landmark ID. Coordinates are full-source pixel centers. Rejected candidate
    matches are listed but never drawn as measured positions. This function
    does not write, resize, blend, or recolor any original image.
    """
    output = Path(output_dir).resolve()
    frames = report.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= 10_000:
        raise ValueError("review requires a bounded nonempty frame list")
    for frame in frames:
        name = frame.get("image_file")
        if not isinstance(name, str) or "\\" in name:
            raise ValueError("image_file must be a relative PNG path")
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or ":" in name
                or relative.suffix.lower() != ".png"):
            raise ValueError("image_file must be a relative PNG path inside the review")
        actual = (output / name).resolve()
        if not actual.is_relative_to(output) or not actual.is_file():
            raise ValueError("review image is missing or outside output_dir")
    data = json.dumps(dict(report), sort_keys=True, allow_nan=False, separators=(",", ":"))
    if len(data.encode("utf-8")) > 100 * 1024 * 1024:
        raise ValueError("review metadata exceeds bounded size")
    # Script data is not HTML; escaping '<' prevents an embedded closing script
    # tag even when a file/landmark label came from untrusted provenance.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    page = _PAGE.replace("__REPORT_JSON__", data)
    target = output / "index.html"
    target.write_text(page, encoding="utf-8")
    return target


_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Original-pixel landmark review</title><style>
body{font:15px system-ui,sans-serif;background:#11151c;color:#edf1f7;margin:20px;line-height:1.45}
h1{font-size:23px;margin-bottom:6px}a{color:#9cd1ff}button,select,input{font:inherit}
button,select{background:#263241;color:inherit;border:1px solid #65768d;border-radius:4px;padding:5px 9px}
button:disabled{opacity:.4}.controls{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:13px 0}
#frame-range{flex:1;min-width:220px}.note{color:#c2cbd8}#stage-scroll{overflow:auto;max-height:70vh;border:1px solid #617087;background:black}
#stage{position:relative;overflow:hidden}#original{position:absolute;max-width:none;display:block}#overlay{position:absolute;pointer-events:none;overflow:visible}
table{border-collapse:collapse;width:100%;font-size:13px;margin:14px 0}th,td{text-align:left;border-bottom:1px solid #465264;padding:7px;vertical-align:top;overflow-wrap:anywhere}
th:nth-child(2),td:nth-child(2){min-width:8.5em;white-space:nowrap;overflow-wrap:normal;word-break:normal}
summary{cursor:pointer}#limits{padding-left:24px;max-width:1100px}#limits li{margin:7px 0}
.measured{color:#51f3c0}.expected{color:#ffbb54}.residual{color:#e87aff}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
#error{color:#ffa7a7;font-weight:bold}.legend{display:flex;gap:18px;flex-wrap:wrap}
</style></head><body>
<h1>Original-pixel landmark review</h1>
<p class="note">Each step displays one unchanged source PNG. No image blending or temporal averaging.
Overlays are derived annotations; correlation scores are not probabilities, and pixel tracking is not optical headset evidence.</p>
<p><a href="results.json">Tracking results</a> · <a href="manifest.json">Selection manifest</a> · <a id="original-link">Open this original PNG</a></p>
<p id="space"></p><details class="note"><summary>Interpretation limits</summary><ul id="limits"></ul></details>
<div class="controls"><button id="previous">Previous</button><input id="frame-range" type="range" min="0" step="1" value="0" aria-label="Frame"><button id="next">Next</button><span id="frame-label"></span></div>
<div class="controls"><label>View <select id="eye"><option value="all">Full source</option><option value="left">Left eye</option><option value="right">Right eye</option></select></label>
<label>Scale <select id="scale"><option value="native">Native pixels (1:1)</option><option value="fit">Fit width (display scaling)</option></select></label>
<label class="measured"><input id="show-measured" type="checkbox" checked> Measured</label>
<label class="expected"><input id="show-expected" type="checkbox" checked> Expected</label>
<label class="residual"><input id="show-residual" type="checkbox" checked> Residual vectors</label></div>
<p class="legend"><span class="measured">+ accepted measured anchor</span><span class="expected">○ expected anchor</span><span class="residual">line: expected → measured</span></p>
<p id="error" role="status"></p><div id="stage-scroll"><div id="stage"><img id="original" alt="Original source frame"><svg id="overlay" xmlns="http://www.w3.org/2000/svg"></svg></div></div>
<p id="geometry" class="note"></p><table><thead><tr><th>Eye / landmark</th><th>Status</th><th>Measured source (x, y)</th><th>NCC / second / gap / matching filter</th><th>Expected / residual (px)</th><th>Reason</th></tr></thead><tbody id="matches"></tbody></table>
<details><summary>Current frame provenance and groups</summary><pre id="source"></pre></details>
<script id="report" type="application/json">__REPORT_JSON__</script><script>
'use strict';
const report=JSON.parse(document.getElementById('report').textContent),frames=report.frames;
const byId=id=>document.getElementById(id),image=byId('original'),svg=byId('overlay');
let index=0,loadedIndex=-1;
const text=(id,value)=>{byId(id).textContent=value;};
const point=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
const pair=p=>point(p)?p.map(x=>x.toFixed(2)).join(', '):'—';
const numeric=x=>Number.isFinite(x)?x.toFixed(4):'—';
const localUrl=path=>path.split('/').map(encodeURIComponent).join('/');
const sourceMatches=frame=>Object.entries(frame.groups||{}).flatMap(([eye,group])=>(group.matches||[]).map(match=>({eye,match})));
function create(tag,attrs){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);svg.appendChild(node);return node;}
function contrastStroke(tag,geometry,color,scale){
 for(const [stroke,width] of [['#05080d',8],['#ffffff',5],[color,2.5]])create(tag,{...geometry,stroke,'stroke-width':width/scale,'stroke-linecap':'round','stroke-linejoin':'round',fill:'none'});
}
function renderGeometry(){
 if(loadedIndex!==index||!image.naturalWidth)return;
 const frame=frames[index],w=image.naturalWidth,h=image.naturalHeight,eye=byId('eye').value;
 const entries=sourceMatches(frame),meta=frame.source||{},layout=meta.eye_rectangles||entries[0]?.match.source?.eye_rectangles||{};
 const rect=eye==='all'?[0,0,w,h]:layout[eye];
 svg.replaceChildren();
 if(!Array.isArray(rect)||rect.length!==4||rect.some(x=>!Number.isFinite(x))||rect[0]<0||rect[1]<0||rect[2]>w||rect[3]>h||rect[2]<=rect[0]||rect[3]<=rect[1]){
  text('error','Requested eye crop is unavailable in explicit source metadata.');byId('stage').style.display='none';return;
 }
 text('error','');byId('stage').style.display='block';
 const rw=rect[2]-rect[0],rh=rect[3]-rect[1],scale=byId('scale').value==='fit'?Math.min(1,(byId('stage-scroll').clientWidth-2)/rw):1;
 Object.assign(byId('stage').style,{width:(rw*scale)+'px',height:(rh*scale)+'px'});
 for(const element of [image,svg])Object.assign(element.style,{left:(-rect[0]*scale)+'px',top:(-rect[1]*scale)+'px',width:(w*scale)+'px',height:(h*scale)+'px'});
 svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
 text('geometry',`${w} × ${h} original pixels; ${eye} view; display scale ${(100*scale).toFixed(1)}%. Pixel-center coordinates remain in the full original source. Integer translation sampling carries at least ±0.5 px quantization uncertainty; total error is not calibrated.`);
 for(const {eye:matchEye,match} of entries){
  if(eye!=='all'&&eye!==matchEye)continue;
  const measured=match.status==='tracked'&&point(match.position_xy)?match.position_xy:null;
  const prediction=frame.expected?.[match.landmark_id],expected=point(prediction?.position_xy)?prediction.position_xy:null;
  // SVG geometry is edge-based: +0.5 maps array pixel centers correctly.
  if(byId('show-residual').checked&&measured&&expected)contrastStroke('line',{x1:expected[0]+.5,y1:expected[1]+.5,x2:measured[0]+.5,y2:measured[1]+.5},'#e87aff',scale);
  if(byId('show-expected').checked&&expected)contrastStroke('circle',{cx:expected[0]+.5,cy:expected[1]+.5,r:10/scale},'#ffbb54',scale);
  if(byId('show-measured').checked&&measured){
   const x=measured[0]+.5,y=measured[1]+.5,arm=9/scale;
   contrastStroke('path',{d:`M ${x-arm} ${y} H ${x+arm} M ${x} ${y-arm} V ${y+arm}`},'#51f3c0',scale);
   const label=create('text',{x:x+15/scale,y:y-15/scale,fill:'#ffffff','font-size':14/scale,'font-weight':700});label.textContent=match.landmark_id;
   let box=label.getBBox();
   if(box.x+box.width+5/scale>rect[2])label.setAttribute('x',x-15/scale-box.width);
   if(box.y-4/scale<rect[1])label.setAttribute('y',y+26/scale);
   box=label.getBBox();
   const backing=create('rect',{x:box.x-5/scale,y:box.y-3/scale,width:box.width+10/scale,height:box.height+6/scale,rx:3/scale,fill:'#090d13','fill-opacity':.95,stroke:'#ffffff','stroke-width':1/scale});
   svg.insertBefore(backing,label);
  }
 }
}
function render(){
 const frame=frames[index];byId('frame-range').value=index;byId('previous').disabled=index===0;byId('next').disabled=index===frames.length-1;
 text('frame-label',`${index+1} / ${frames.length} · ${String(frame.id??index)}`);
 const link=byId('original-link');link.href=localUrl(frame.image_file);link.textContent=`Open original PNG · ${frame.image_file}`;
 const rows=byId('matches');rows.replaceChildren();
 for(const {eye,match} of sourceMatches(frame)){
  const expected=frame.expected?.[match.landmark_id]||{},tr=document.createElement('tr');
  const cells=[`${eye} / ${match.landmark_id}`,match.status,pair(match.status==='tracked'?match.position_xy:null),
   `${numeric(match.score)} / ${numeric(match.second_peak_score)} / ${numeric(match.peak_gap)} · ${match.matching_filter?.sigma_px?'spatial σ='+match.matching_filter.sigma_px+' px (matching only)':'raw RGB'}`,
   `${pair(expected.position_xy)} / ${pair(expected.residual_xy)}${expected.status?' · '+expected.status:''}`,
   [match.reason,expected.reason].filter(Boolean).join('; ')];
  for(const value of cells){const td=document.createElement('td');td.textContent=String(value??'');tr.appendChild(td);}rows.appendChild(tr);
 }
 text('source',JSON.stringify({source:frame.source,groups:frame.groups,expected:frame.expected},null,2));
 loadedIndex=-1;svg.replaceChildren();image.onload=()=>{loadedIndex=index;renderGeometry();};image.onerror=()=>text('error','Original PNG could not be loaded.');image.src=localUrl(frame.image_file);
}
byId('frame-range').max=frames.length-1;
byId('frame-range').oninput=event=>{index=Number(event.target.value);render();};
byId('previous').onclick=()=>{if(index>0){--index;render();}};
byId('next').onclick=()=>{if(index<frames.length-1){++index;render();}};
for(const id of ['eye','scale','show-measured','show-expected','show-residual'])byId(id).onchange=renderGeometry;
window.addEventListener('resize',renderGeometry);
document.addEventListener('keydown',event=>{if(event.target instanceof HTMLInputElement||event.target instanceof HTMLSelectElement)return;if(event.key==='ArrowLeft'){event.preventDefault();byId('previous').click();}if(event.key==='ArrowRight'){event.preventDefault();byId('next').click();}});
text('space',`Coordinate space: ${report.coordinate_space??'unspecified'}. Expected geometry is comparable only when it uses the same calibrated coordinate space.`);
const limits=typeof report.limits==='string'?[report.limits]:Array.isArray(report.limits)?report.limits:Object.entries(report.limits??{}).map(([key,value])=>`${key.replaceAll('_',' ')}: ${String(value)}`);
for(const limit of limits){const item=document.createElement('li');item.textContent=String(limit);byId('limits').appendChild(item);}render();
</script></body></html>'''
