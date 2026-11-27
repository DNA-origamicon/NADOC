/** Release only this fixture's native worker even when page.evaluate times out. */
export function guardNativeLease(test){
 let id=null
 test.beforeEach(async({page})=>{
  id=null
  page.on('response',async response=>{
   if(response.url().endsWith('/api/render/optix/session')&&response.request().method()==='POST'&&response.ok()){
    try{id=(await response.json()).id}catch{/* Startup failure owns no acknowledged lease. */}
   }
  })
 })
 test.afterEach(async({request})=>{
  if(id)await request.delete(`/api/render/optix/${id}`,{timeout:30000})
  id=null
 })
}
