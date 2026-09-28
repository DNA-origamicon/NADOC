import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPresentationState } from './prepared_room_state.mjs'
const pose={schema:1,trackingToSource:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],head:{position:[0,1.6,0],orientation:[0,0,0,1]},hands:[null,null]}
test('avatar is independent of camera sharing, revision-bound, bounded, and expires',()=>{
  let now=0;const room=createPresentationState({id:'room',revision:'one',now:()=>now})
  room.publishAvatar({revision:'one',avatar:pose})
  assert.deepEqual(room.snapshot().avatar.pose,pose);assert.equal(room.snapshot().presenting,false)
  assert.throws(()=>room.publishAvatar({revision:'other',avatar:pose}))
  assert.throws(()=>room.publishAvatar({revision:'one',avatar:{...pose,hands:[]}}))
  room.pause();assert.ok(room.snapshot().avatar)
  now=1501;room.expireAvatar();assert.equal(room.snapshot().avatar,null)
  room.publishAvatar({revision:'one',avatar:pose});room.replaceRevision('two');assert.equal(room.snapshot().avatar,null)
  room.publishAvatar({revision:'two',avatar:pose});room.close();assert.equal(room.snapshot().avatar,null)
  assert.throws(()=>room.publishAvatar({revision:'two',avatar:pose}))
})

test('only local host authority can write poses; guests receive them through room state',async t=>{
  const {mkdtemp,mkdir,writeFile,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path')
  const {createPreparedHost}=await import('./prepared_view_host.mjs')
  const root=await mkdtemp(join(tmpdir(),'nadoc-avatar-host-'));t.after(()=>rm(root,{recursive:true,force:true}))
  await mkdir(join(root,'assets'));await writeFile(join(root,'viewer.html'),'viewer')
  const host=await createPreparedHost({dist:root});t.after(host.stop)
  await new Promise(ok=>host.server.listen(0,'127.0.0.1',ok))
  const base=`http://127.0.0.1:${host.server.address().port}`;host.setPublicBase(base)
  const share=host.createShare(Buffer.from('NADOCVW1test')),url=`${base}/host/shares/${share.id}/avatar`
  const body=JSON.stringify({revision:share.revision,avatar:pose}),headers={Authorization:`Bearer ${host.controlToken}`}
  assert.equal((await fetch(url,{method:'POST',body})).status,403)
  assert.equal((await fetch(url,{method:'POST',body,headers})).status,200)
  assert.equal((await fetch(url,{method:'POST',body:JSON.stringify({revision:'wrong',avatar:pose}),headers})).status,409)
  assert.equal((await fetch(url,{method:'POST',body:'x'.repeat(4*1024*1024+1),headers})).status,413)
  const token=new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite')
  const joined=await fetch(`${base}/meeting/${share.id}/join`,{method:'POST',headers:{Origin:base},body:JSON.stringify({name:'Guest',token})})
  const cookie=joined.headers.get('set-cookie').split(';')[0]
  const state=await(await fetch(`${base}/meeting/${share.id}/status`,{headers:{Cookie:cookie}})).json()
  assert.deepEqual(state.presentation.avatar.pose,pose)
  assert.equal((await fetch(url,{method:'POST',body:JSON.stringify({revision:share.revision,avatar:null}),headers})).status,200)
})

 test('native menus and guides survive room snapshots and expire with presence',()=>{
  let now=0;const room=createPresentationState({id:'room',revision:'one',now:()=>now})
  const ui={lines:[0,0,0,1,1,1,0,1,0,1,1,1],panels:[]}
  room.publishAvatar({revision:'one',avatar:{...pose,ui}})
  assert.deepEqual(room.snapshot().avatar.pose.ui,ui)
  room.publishAvatar({revision:'one',avatar:{...pose,ui:{lines:[],panels:[]}}})
  assert.equal(room.snapshot().avatar.pose.ui.lines.length,0)
  now=1501;room.expireAvatar();assert.equal(room.snapshot().avatar,null)
})

test('menu-sized SSE packets wait for drain and coalesce pending poses',async()=>{
  const {EventEmitter}=await import('node:events')
  const response=new EventEmitter(),messages=[];let destroyed=false
  response.write=message=>{messages.push(message);return false};response.destroy=()=>{destroyed=true;response.emit('close')};response.end=()=>response.emit('close')
  const room=createPresentationState({id:'room',revision:'one'})
  room.subscribe(response)
  room.publishAvatar({revision:'one',avatar:pose});room.publishAvatar({revision:'one',avatar:null})
  assert.equal(destroyed,false);assert.equal(messages.length,1)
  response.write=message=>{messages.push(message);return true};response.emit('drain')
  assert.equal(messages.length,2);assert.equal(JSON.parse(messages[1].split('data: ')[1]).avatar,null)
  room.close()
})

test('coalescing does not discard the image needed by a delayed guest',async()=>{
  const {EventEmitter}=await import('node:events'),{decodeVRUIState}=await import('../frontend/src/viewer/vr_ui_stream.js')
  const response=new EventEmitter(),messages=[],images=new Map()
  response.write=m=>{messages.push(m);return false};response.destroy=()=>response.emit('close');response.end=()=>response.emit('close')
  const room=createPresentationState({id:'room',revision:'one'});room.subscribe(response)
  const panel={id:'left-menu',corners:[0,1,0,0,0,0,1,1,0,1,0,0],png:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=='}
  room.publishAvatar({revision:'one',avatar:{...pose,ui:{lines:[],panels:[panel]}}})
  room.publishAvatar({revision:'one',avatar:{...pose,ui:{lines:[],panels:[{...panel,corners:panel.corners.map(x=>x+1)}]}}})
  response.write=m=>{messages.push(m);return true};response.emit('drain')
  const state=decodeVRUIState(JSON.parse(messages.at(-1).split('data: ')[1]),images)
  assert.equal(state.avatar.pose.ui.panels[0].png,panel.png);assert.equal(state.avatar.pose.ui.panels[0].corners[0],1)
  room.close()
})
