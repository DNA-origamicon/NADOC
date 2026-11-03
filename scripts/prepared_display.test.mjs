import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createDesignLinks } from './prepared_design_links.mjs'
import { createPreparedHost } from './prepared_view_host.mjs'

test('upgrading a saved invitation adds only the display secret and preserves every printed QR credential across restart', async t => {
 const root=await mkdtemp(join(tmpdir(),'nadoc-display-'));t.after(()=>rm(root,{recursive:true,force:true}))
 const file=join(root,'links.json'),legacy={key:'part:printed',id:'a'.repeat(32),invite:'b'.repeat(64),qrToken:'c'.repeat(64),password:'original-password'}
 await writeFile(file,JSON.stringify([legacy]));const links=await createDesignLinks(file)
 const upgraded=await links.ensure(legacy.key)
 const {displayPassword,...preserved}=upgraded
 assert.deepEqual(preserved,legacy);assert.ok(displayPassword.length>=24)
 assert.deepEqual(await (await createDesignLinks(file)).ensure(legacy.key),upgraded)
 assert.deepEqual(JSON.parse(await readFile(file,'utf8')),[upgraded])
})

test('one authenticated display has a protected place beyond 16 guests and no presenter authority', async t => {
 const root=await mkdtemp(join(tmpdir(),'nadoc-display-'));t.after(()=>rm(root,{recursive:true,force:true}))
 await mkdir(join(root,'assets'));await writeFile(join(root,'viewer.html'),'viewer')
 let clock=Date.now()
 const host=await createPreparedHost({dist:root,persistent:true,now:()=>clock});t.after(host.stop)
 await new Promise(ok=>host.server.listen(0,'127.0.0.1',ok))
 const origin=`http://127.0.0.1:${host.server.address().port}`,auth={Authorization:`Bearer ${host.controlToken}`}
 host.setPublicBase(origin)
 const room=host.createShare(Buffer.from('NADOCVW1display'))
 const qr=new URL(room.qrUrl || 'http://unused');const token=new URLSearchParams(qr.hash.slice(1)).get('invite'),endpoint=origin+`/meeting/${room.id}`
 const joinGuest=async(extra={},cookie)=>{const r=await fetch(endpoint+'/join',{method:'POST',headers:{Origin:origin,...(cookie?{Cookie:cookie}:{})},body:JSON.stringify({token,entry:'qr',name:'Visitor',...extra})});return {status:r.status,cookie:r.headers.get('set-cookie')?.split(';')[0],value:await r.json()}}
 assert.equal((await joinGuest({role:'display'})).status,403)
 assert.equal((await joinGuest({role:'display',password:'wrong'})).status,403)
 for(let i=0;i<16;i++)assert.equal((await joinGuest()).status,200)
 assert.equal((await joinGuest()).status,202)
 const display=await joinGuest({role:'display',password:room.displayPassword,name:'Demo screen'})
 assert.equal(display.status,200);assert.equal(display.value.role,'display');assert.equal(display.value.admission,undefined)
 assert.equal((await joinGuest({role:'display',password:room.displayPassword})).status,409)
 const roster=await (await fetch(origin+`/host/shares/${room.id}/admission`,{headers:auth})).json()
 assert.equal(roster.active,16);assert.equal(roster.displays,1);assert.equal(roster.guests.some(g=>g.name==='Demo screen'),false)
 await fetch(origin+`/host/shares/${room.id}/admission`,{method:'POST',headers:auth})
 clock+=600000
 const headers={Origin:origin,Cookie:display.cookie}
 assert.equal((await fetch(endpoint+'/scene',{headers})).status,200)
 const state=await(await fetch(endpoint+'/status',{headers})).json()
 assert.equal(state.role,'display');assert.equal(JSON.stringify(state).includes(room.displayPassword),false)
 assert.equal((await fetch(endpoint+'/camera',{method:'POST',headers,body:'{}'})).status,403)
 assert.equal((await fetch(endpoint+'/share-view',{method:'POST',headers,body:'{}'})).status,403)
 assert.equal((await joinGuest({role:'display',resume:true},display.cookie)).status,200)
 assert.equal((await fetch(endpoint+'/leave',{method:'POST',headers})).status,200)
 assert.equal((await fetch(endpoint+'/scene',{headers})).status,401)
 assert.equal((await joinGuest({role:'display',password:room.displayPassword})).status,200)
})
