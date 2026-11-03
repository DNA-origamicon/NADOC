import test from 'node:test'
import assert from 'node:assert/strict'
import { createAdmission } from './prepared_admission.mjs'
import { screenGuestName } from './prepared_guest_names.mjs'
function setup(capacity=16) {
  let time=1000, serial=0, closed=0
  const room={sessions:new Map()}, other={sessions:new Map()}, rooms=new Map([['a',room],['b',other]])
  const api=createAdmission({rooms,maxGuests:capacity,now:()=>time,disconnect:()=>closed++})
  const guest=(r=room)=>{const id=String(++serial),s={role:'guest',participantId:id,name:'Guest '+id};api.enroll(s);r.sessions.set(id,s);return s}
  return {api,room,other,guest,advance:ms=>time+=ms,closed:()=>closed}
}
test('16 host-wide slots, FIFO offers, reserved capacity and explicit acceptance',()=>{
  const x=setup(),active=Array.from({length:16},()=>x.guest()),a=x.guest(x.other),b=x.guest()
  assert.equal(x.api.summary(x.room).occupied,16); assert.equal(x.api.status(a).position,1)
  x.api.release(active[0],'left');x.api.sweep()
  assert.equal(a.admission,'offered'); assert.equal(b.admission,'waiting')
  assert.equal(x.guest().admission,'waiting')
  x.api.pulse(a,{visible:true,active:true,action:'accept'})
  assert.equal(a.admission,'active');assert.equal(x.api.summary(x.room).occupied,16)
})
test('rotation replaces only enough oldest guests, admits queue atomically, preserves newcomers',()=>{
  const x=setup(3),a=x.guest();x.advance(1);const b=x.guest();x.advance(1);const c=x.guest();const d=x.guest(),e=x.guest()
  const result=x.api.rotate(x.room)
  assert.equal(result.removed,2);assert.equal(result.admitted,2)
  assert.equal(a.admission,'released');assert.equal(b.admission,'released');assert.equal(c.admission,'active')
  assert.equal(d.admission,'active');assert.equal(e.admission,'active');assert.equal(x.guest().admission,'waiting')
})
test('rotation uses free/reserved slots before evicting and frees one oldest slot without a queue',()=>{
  const x=setup(2),a=x.guest(),b=x.guest(),c=x.guest();x.api.release(b,'left');x.api.sweep()
  assert.equal(c.admission,'offered');assert.equal(x.api.rotate(x.room).removed,0)
  x.advance(1);assert.equal(x.api.rotate(x.room).removed,1);assert.equal(a.admission,'released')
})
test('hidden clients release after two minutes despite pulses; disconnected clients expire without joins',()=>{
  const x=setup(2),a=x.guest(),b=x.guest()
  x.api.pulse(a,{visible:false,active:false})
  for(let i=0;i<24;i++){x.advance(5000);x.api.pulse(a,{visible:false,active:false})}
  assert.equal(a.admission,'released');assert.equal(a.reason,'background')
  x.advance(1);x.api.sweep();assert.equal(b.reason,'disconnected');assert.ok(x.closed()>=2)
})
test('passive visible viewers are prompted only under queue pressure, acknowledgement cancels prompt',()=>{
  const x=setup(1),a=x.guest()
  for(let i=0;i<61;i++){x.advance(5000);x.api.pulse(a,{visible:true,active:false})}
  assert.equal(a.promptAt,null)
  const b=x.guest();x.api.sweep();assert.ok(a.promptAt)
  x.api.pulse(a,{visible:true,active:true});assert.equal(a.promptAt,null)
  for(let i=0;i<60;i++){x.advance(5000);x.api.pulse(a,{visible:true,active:false});x.api.pulse(b,{visible:true,active:false})}
  assert.ok(a.promptAt);x.advance(30000);x.api.sweep();assert.equal(a.reason,'inactive');assert.equal(b.admission,'offered')
})
test('unclaimed offers expire and absent queue entries cannot consume new slots',()=>{
  const x=setup(1),a=x.guest(),b=x.guest(),c=x.guest()
  x.api.release(a,'left');x.api.sweep();assert.equal(b.admission,'offered')
  x.advance(30000);x.api.pulse(c,{visible:true,active:false});assert.equal(b.reason,'offer-expired');assert.equal(c.admission,'offered')
  x.advance(120001);x.api.sweep();assert.equal(c.admission,'released')
})
test('same session does not reset admission age or queue position',()=>{
 const x=setup(1),a=x.guest(),b=x.guest(),age=a.admittedAt,order=b.order
 x.advance(5000);x.api.enroll(a);x.api.enroll(b);assert.equal(a.admittedAt,age);assert.equal(b.order,order)
})
test('bounded waiting list and no presenter eviction',()=>{
 const x=setup(1);x.room.sessions.set('presenter',{role:'presenter'});x.guest()
 for(let i=0;i<256;i++)x.guest()
 assert.throws(()=>x.guest(),/waiting list is full/)
 x.api.rotate(x.room);assert.equal(x.room.sessions.get('presenter').role,'presenter')
})
test('screening catches explicit names and common disguises without rejecting ordinary international names',()=>{
 for(const name of ['fuck','FUCK','f.u.c.k','fuuuuuck','fück','ｆｕｃｋ','sh1t','bitch','nigger','Guest\u202eabc'])assert.throws(()=>screenGuestName(name),undefined,name)
 for(const name of ['Alice','Scunthorpe','Dick','Dickinson','Cassidy','Penistone','José','李明','محمد','Ольга',"O’Connor",'Guest 123'])assert.equal(screenGuestName(name),name)
})

test('HTTP: 16 guests plus a 100-guest burst, no queued scene access, oldest replacement and protected controls', async t=>{
 const {createPreparedHost}=await import('./prepared_view_host.mjs')
 const {mkdtemp,mkdir,writeFile,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path')
 const root=await mkdtemp(join(tmpdir(),'nadoc-admission-'));t.after(()=>rm(root,{recursive:true,force:true}))
 await mkdir(join(root,'assets'));await writeFile(join(root,'viewer.html'),'viewer')
 const host=await createPreparedHost({dist:root});t.after(host.stop)
 await new Promise(ok=>host.server.listen(0,'127.0.0.1',ok));const base=`http://127.0.0.1:${host.server.address().port}`;host.setPublicBase(base)
 const room=host.createShare(Buffer.from('NADOCVW1scene')),endpoint=base+`/meeting/${room.id}`,token=new URLSearchParams(new URL(room.qrUrl).hash.slice(1)).get('invite')
 const enter=async(name,cookie)=>{const res=await fetch(endpoint+'/join',{method:'POST',headers:{Origin:base,...(cookie?{Cookie:cookie}:{})},body:JSON.stringify({token,name,entry:'qr'})});return {code:res.status,cookie:res.headers.get('set-cookie')?.split(';')[0],data:await res.json()}}
 const first=await Promise.all(Array.from({length:32},(_,i)=>enter('Visitor '+i)))
 const guests=[...first.filter(g=>g.code===200),...first.filter(g=>g.code===202).sort((a,b)=>a.data.admission.position-b.data.admission.position)]
 for(let i=32;i<116;i++)guests.push(await enter('Visitor '+i))
 assert.equal(guests.filter(g=>g.code===200).length,16);assert.equal(guests.filter(g=>g.code===202).length,100)
 const queued=guests[16]
 for(const route of ['scene','events','frame','live-frame'])assert.equal((await fetch(endpoint+'/'+route,{headers:{Cookie:queued.cookie}})).status,409)
 const action=base+`/host/shares/${room.id}/admission`,auth={Authorization:`Bearer ${host.controlToken}`}
 assert.equal((await fetch(action,{method:'POST',headers:{Cookie:guests[0].cookie}})).status,403)
 assert.equal((await fetch(action,{method:'POST',headers:{...auth,Origin:'https://elsewhere'}})).status,403)
 const swapped=await(await fetch(action,{method:'POST',headers:auth})).json();assert.equal(swapped.removed,16);assert.equal(swapped.admitted,16)
 assert.equal((await fetch(endpoint+'/scene',{headers:{Cookie:guests[0].cookie}})).status,409)
 assert.equal(await(await fetch(endpoint+'/scene',{headers:{Cookie:queued.cookie}})).text(),'NADOCVW1scene')
 const again=await enter('Visitor 0',guests[0].cookie);assert.equal(again.code,202);assert.equal(again.data.admission.position,85)
 const same=await enter('Visitor 0',again.cookie);assert.equal(same.data.admission.position,85)
 const leave=await fetch(endpoint+'/admission',{method:'POST',headers:{Origin:base,Cookie:queued.cookie},body:JSON.stringify({action:'leave',visible:true,active:false})})
 assert.equal((await leave.json()).admission.reason,'left')
 const offer=await fetch(endpoint+'/admission',{method:'POST',headers:{Origin:base,Cookie:guests[32].cookie},body:JSON.stringify({visible:true,active:false})})
 assert.equal((await offer.json()).admission.state,'offered')
 assert.equal((await enter('f.u.c.k')).code,400)
})
