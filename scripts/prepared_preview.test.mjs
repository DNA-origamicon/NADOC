import {test} from 'node:test'
import assert from 'node:assert/strict'
import {EventEmitter} from 'node:events'
import {createPresentationState} from './prepared_room_state.mjs'
const matrix=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
const preview={trackingToSource:matrix,model:matrix,radius:.024,selected:0,nodes:[[0,0,0]],frames:[[1,0,0,0,1,0]],path:[[0,0,0],[0,0,2]],outline:[[0,0],[1,0],[0,1]],cells:[[0,0]]}
const response=()=>{const r=new EventEmitter();r.write=value=>{r.last=JSON.parse(value.split('data: ')[1]);return true};r.end=()=>r.emit('close');r.destroy=r.end;return r}
test('preview is bounded, revision-bound, deduplicated for 17 viewers, renewed, expired and cleared on scene replacement',()=>{
 let now=0;const room=createPresentationState({id:'room',revision:'one',now:()=>now})
 const guests=Array.from({length:17},response);for(const r of guests)assert.equal(room.subscribe(r),true)
 assert.throws(()=>room.publishPreview({revision:'other',preview}),/snapshot/)
 assert.throws(()=>room.publishPreview({revision:'one',preview:{...preview,cells:Array(257).fill([0,0])}}))
 room.publishPreview({revision:'one',preview});for(const r of guests)assert.deepEqual(r.last.preview.data,preview)
 now=1000;room.publishPreview({revision:'one',keep:true});for(const r of guests){assert.equal(r.last.preview.expiresAt,4000);assert.equal(r.last.preview.data,undefined)}
 const late=response();room.subscribe(late);assert.deepEqual(late.last.preview.data,preview)
 now=4001;room.expireAvatar();assert.equal(guests[0].last.preview,null)
 room.publishPreview({revision:'one',preview});room.replaceRevision('two');assert.equal(room.snapshot().preview,null)
 assert.throws(()=>room.publishPreview({revision:'two',keep:true}),/expired/)
 room.publishPreview({revision:'two',preview});room.publishPreview({revision:'two',preview:null});assert.equal(room.snapshot().preview,null);room.close()
})
test('preview publishing requires host authority and rejects oversized and stale requests',async t=>{
 const {mkdtemp,mkdir,writeFile,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path')
 const {createPreparedHost}=await import('./prepared_view_host.mjs')
 const root=await mkdtemp(join(tmpdir(),'nadoc-preview-'));t.after(()=>rm(root,{recursive:true,force:true}))
 await mkdir(join(root,'assets'));await writeFile(join(root,'viewer.html'),'viewer')
 const host=await createPreparedHost({dist:root});t.after(host.stop);await new Promise(ok=>host.server.listen(0,'127.0.0.1',ok))
 const base=`http://127.0.0.1:${host.server.address().port}`;host.setPublicBase(base)
 const room=host.createShare(Buffer.from('NADOCVW1preview')),url=base+`/host/shares/${room.id}/preview`,auth={Authorization:`Bearer ${host.controlToken}`}
 const body=JSON.stringify({revision:room.revision,preview})
 assert.equal((await fetch(url,{method:'POST',body})).status,403)
 assert.equal((await fetch(url,{method:'POST',headers:auth,body})).status,200)
 assert.equal((await fetch(url,{method:'POST',headers:auth,body:JSON.stringify({revision:'wrong',preview})})).status,409)
 assert.equal((await fetch(url,{method:'POST',headers:auth,body:' '.repeat(128*1024+1)})).status,413)
})
