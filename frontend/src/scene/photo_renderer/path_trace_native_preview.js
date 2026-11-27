/** Adapt asynchronous whole-image native renders to the synchronous viewport.
 * One request at a time; changed scenes never display the previous result.
 * Native sampling currently restarts at each larger count, rather than claiming
 * that Cycles has a resumable accumulation API. No browser main-thread waits. */
export async function createNativeTracePreviewEngine(options,{create}={}){
  create??=(await import('./path_trace_optix.js')).createOptixTraceEngine
  const native=await create(options)
  let pending=null,error=null,disposed=false,visible=false,revision=0
  const wait=async()=>{if(pending)await pending;if(error)throw error}
  return {
    get samples(){return visible?native.samples:0},get triangles(){return native.triangles},get emSamples(){return native.emSamples},
    get diagnostics(){return {...native.diagnostics,pending:!!pending}},
    ready(){if(error)throw error;return !pending},
    async update(next){visible=false;revision++;await wait();if(!disposed)await native.update(next)},
    reset(...args){visible=false;revision++;native.reset(...args)},
    advance(target){
      if(disposed||pending)return
      if(error)throw error
      const own=revision,count=Math.min(target,native.samples<1?1:target)
      pending=Promise.resolve().then(()=>native.advance(count,{quick:count<target})).then(()=>{if(!disposed&&own===revision)visible=true})
        .catch(e=>{if(!disposed)error=e}).finally(()=>{pending=null})
    },
    draw(...args){if(visible)native.draw(...args)},
    readPixels:()=>visible?native.readPixels():null,
    async dispose(){disposed=true;visible=false;revision++;await native.dispose();await pending},
  }
}
