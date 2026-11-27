/** Adapt asynchronous whole-image native renders to the synchronous viewport.
 * One request at a time; changed scenes never display the previous result.
 * Disjoint native sample subsets accumulate without retracing completed work.
 * Keep the last completed image visible while the next chunk is in flight. */
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
      // Dense procedural fields have a large fixed per-render cost.
      // Spend that first setup on a useful 16-sample image, then amortize setup
      // across larger chunks. Small scenes retain the immediate 1-sample image.
      const dense=(native.emVolumeCells??native.diagnostics?.em_volume_cells??0)>100000
      const next=dense?native.samples+64:native.samples+Math.min(16,Math.max(3,native.samples))
      const own=revision,count=Math.min(target,native.samples<1?(dense?16:1):next)
      pending=Promise.resolve().then(()=>native.advance(count,{quick:native.samples===0&&count<target,sampleTarget:target})).then(()=>{if(!disposed&&own===revision)visible=true})
        .catch(e=>{if(!disposed)error=e}).finally(()=>{pending=null})
    },
    draw(...args){if(visible)native.draw(...args)},
    readPixels:()=>visible?native.readPixels():null,
    async dispose(){disposed=true;visible=false;revision++;await native.dispose();await pending},
  }
}
