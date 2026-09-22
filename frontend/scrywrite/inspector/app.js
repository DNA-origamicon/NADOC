import {project,corners,rotate,targets} from './geometry.js'
const $=id=>document.getElementById(id)
let token='',status=null,evidence=null,capture=null,selected='',busy=false,lastAuto=0,polling=false,lastPreview=''
async function api(path,data) {
  const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Inspector-Token':token},body:JSON.stringify(data)})
  const value=await response.json()
  if(!response.ok) throw Error(value.error||response.statusText)
  return value
}
function error(value){$('error').textContent=value?String(value):''}
function element(name,attrs){const e=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e}
function showTarget(key) {
  selected=key;$('target').value=key
  const target=targets(evidence?.state||{}).find(t=>t.key===key)
  const liveTarget=status?.targets.find(t=>t.key===key)
  $('details').textContent=target?JSON.stringify({captured_frame:evidence.state.frame,target,captured_geometry:target.cell?{hit_radius_m:evidence.state.extrude.lattice_hit_radius_m}:{width_m:Math.hypot(...(target.hit_half_right||[0]))*2,height_m:Math.hypot(...(target.hit_half_up||[0]))*2,eye_distance_m:Math.hypot(...target.position.map((v,i)=>v-evidence.eyes.find(e=>e.eye===$('eye').value).position[i]))},live_right_hand_metrics:liveTarget?.ray_metrics||null,metrics_source:'live state; may differ from captured frame'},null,2):'Select a target or click a design pixel.'
  draw()
}
function draw() {
  const svg=$('overlay');svg.replaceChildren()
  if(!evidence)return
  const eye=evidence.eyes.find(e=>e.eye===$('eye').value)
  svg.setAttribute('viewBox',`0 0 ${eye.width} ${eye.height}`)
  svg.setAttribute('preserveAspectRatio','xMidYMid meet')
  for(const target of targets(evidence.state)) {
    if(!$('bounds').checked)break
    const projected=corners(target).map(p=>project(p,eye))
    let shape
    if(projected.length===4 && projected.every(Boolean))shape=element('polygon',{points:projected.map(p=>p.join(',')).join(' ')})
    else if(target.cell){const p=project(target.position,eye);if(p)shape=element('circle',{cx:p[0],cy:p[1],r:9})}
    if(!shape)continue
    shape.setAttribute('fill',target.key===selected?'#ffdc5028':'transparent')
    shape.setAttribute('stroke',target.key===selected?'#ffdb58':'#69d9ee')
    shape.setAttribute('stroke-width',target.key===selected?5:2)
    shape.onclick=e=>{e.stopPropagation();showTarget(target.key)}
    const title=element('title',{});title.textContent=target.label;shape.append(title);svg.append(shape)
  }
  if($('rays').checked)for(const [i,h] of (evidence.state.hands||[]).entries()){
    if(!h.valid)continue
    const d=rotate(h.orientation_xyzw,[0,0,-.6]),a=project(h.position,eye),b=project(h.position.map((v,j)=>v+d[j]),eye)
    if(a&&b)svg.append(element('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:i?'#ffae6b':'#68d4ff','stroke-width':3,'pointer-events':'none'}))
  }
}
async function loadCapture(name){
  const response=await fetch(`/artifacts/${name}/evidence.json`)
  const frame=await response.json()
  if(!response.ok)throw Error(frame.error||'Capture unavailable')
  capture=name;evidence=frame
  $('empty').hidden=true;$('eyeImage').hidden=false
  $('eyeImage').src=`/artifacts/${name}/${$('eye').value}.png`
  $('frameInfo').textContent=`Captured frame ${evidence.state.frame} · session ${evidence.state.session} · scene ${evidence.state.scene_visibility||'normal'} · submitted ${evidence.xr_end_frame_succeeded?'yes':'NO'}`
  $('target').replaceChildren(new Option('Select a target',''),...targets(evidence.state).map(t=>new Option(t.label,t.key)))
  showTarget(targets(evidence.state).some(t=>t.key===selected)?selected:'')
}
async function takeCapture(){if(busy)return;busy=true;try{error('');const c=await api('capture',{});await poll();$('history').value=c.name;await loadCapture(c.name)}catch(e){error(e.message)}finally{busy=false;void poll()}}
async function poll(){
  if(polling)return
  polling=true
  try{
    status=await api('status')
    const s=status.state,j=status.job,running=j.status==='running'
    if(s.error)throw Error(s.error)
    $('connection').textContent=`${s.focused?'Focused':'Unfocused'} · ${s.mode}`
    $('live').textContent=[`Frame ${s.frame} · ${s.scene_visibility||'normal'} scene`,`Menu ${s.menu} · hover ${s.hover}`,`Layout ${s.layout}: ${s.layout_detail||''}`,...(s.hands||[]).map((h,i)=>`${i?'Right':'Left'}: ${h.valid?'valid':'inactive'} · ${h.input_owner||'ownership unavailable'} · trigger ${h.trigger}`),`Extrude: ${s.extrude?.cells.length||0} cells · ${s.extrude?.length_bp||0} bp`,`Wheel: ${s.extrude?.wheel_dragging?'dragging':s.extrude?.wheel_hovered?'hovered':'idle'}`,`Commit supported: ${s.extrude?.commit_supported===true?'yes':'no'}`].join('\n')
    $('visibility').value=s.scene_visibility||'normal'
    for(const id of ['initial','final','review','capture','visibility'])$(id).disabled=running||busy
    $('initial').disabled ||= s.mode!=='control';$('review').disabled ||= s.mode!=='control';$('final').disabled ||= s.mode!=='control'||!status.initial_ready
    $('stop').disabled=!running
    $('job').textContent=`${j.status}${j.phase?' · '+j.phase:''}${j.stage?' · '+j.stage+(running?' (review hold)':''):''}${j.error?' · '+j.error:''}`
    $('job').className=j.status==='failed'||j.status==='error'?'fail':j.status==='passed'?'pass':''
    $('outcomes').replaceChildren(...(j.outcomes||[]).map(t=>{const e=document.createElement('div');const fails=Object.entries(t.checks).filter(([,ok])=>!ok).map(([k])=>k);e.className=fails.length?'fail':'pass';e.textContent=t.preset+': '+(fails.length?fails.join(', '):'PASS');return e}))
    $('report').hidden=!j.report;if(j.report)$('report').href=j.report
    const old=capture||$('history').value
    $('history').replaceChildren(new Option('Select captured frame',''),...status.history.map(c=>new Option(`Frame ${c.frame} · ${c.scene_visibility}`,c.name)))
    if(status.history.some(c=>c.name===old))$('history').value=old
    if(j.preview&&j.preview!==lastPreview&&!busy){await loadCapture(j.preview);lastPreview=j.preview}
    if(evidence && evidence.state.session!==s.session)$('frameInfo').textContent='STALE SESSION — capture again. '+$('frameInfo').textContent.replace(/^STALE SESSION — capture again\. /,'')
    if($('auto').checked&&!running&&!busy&&Date.now()-lastAuto>2000){lastAuto=Date.now();void takeCapture()}
  }catch(e){$('connection').textContent='Viewer unavailable';error(e.message)}finally{polling=false}
}
$('zoom').onchange=()=>{$('imageStage').style.transform=`scale(${$('zoom').value})`}
$('capture').onclick=takeCapture
$('history').onchange=()=>{if($('history').value)loadCapture($('history').value).catch(e=>error(e.message))}
$('eye').onchange=()=>{if(capture)loadCapture(capture).catch(e=>error(e.message))}
$('target').onchange=()=>showTarget($('target').value)
for(const id of ['bounds','rays'])$(id).onchange=draw
$('visibility').onchange=async()=>{try{await api('visibility',{visibility:$('visibility').value});await takeCapture()}catch(e){error(e.message)}}
for(const [id,final] of [['initial',false],['final',true]])$(id).onclick=async()=>{try{error('');await api('run',{final});await poll()}catch(e){error(e.message)}}
$('review').onclick=async()=>{try{error('');await api('run',{review:true});await poll()}catch(e){error(e.message)}}
$('stop').onclick=async()=>{await api('stop',{});await poll()}
$('overlay').onclick=async e=>{
  if(!evidence||!capture)return
  const box=$('overlay').getBoundingClientRect(),eye=evidence.eyes.find(v=>v.eye===$('eye').value)
  const scale=Math.min(box.width/eye.width,box.height/eye.height),w=eye.width*scale,h=eye.height*scale
  const x=(e.clientX-box.left-(box.width-w)/2)/w,y=(e.clientY-box.top-(box.height-h)/2)/h
  if(x<0||y<0||x>=1||y>=1)return
  try{$('details').textContent=JSON.stringify(await api('pick',{capture,eye:$('eye').value,x,y}),null,2)}catch(err){error(err.message)}
}
token=(await api('config')).token
await poll();setInterval(poll,750)
