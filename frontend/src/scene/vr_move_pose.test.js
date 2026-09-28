import { describe, it, expect, vi } from 'vitest'
import { commitVRMovePose } from './vr_move_pose.js'
import { initialVRToolShellState, reduceVRToolShell } from './vr_tool_shell.js'
const matrix=[1,0,0,0,0,0,1,0,0,-1,0,0,2,3,4,1]
describe('VR release transaction',()=>{
  for(const kind of ['cluster','overhang','base'])it(`saves final ${kind} pose after asynchronous preview readiness`,async()=>{
    const ref={kind,id:'target',key:'base-key'}
    let ready=false,saved
    const adapter={
      beginVRPreview:vi.fn(async()=>{await Promise.resolve();ready=true;return {accepted:true}}),
      applyVRPreviewMatrix:vi.fn(value=>{expect(ready).toBe(true);saved=value;return true}),
      confirmVRPreview:vi.fn(async()=>({accepted:true,saved})),
    }
    expect(await commitVRMovePose(adapter,ref,matrix)).toEqual({accepted:true,saved:matrix})
    expect(adapter.beginVRPreview).toHaveBeenCalledWith(kind==='cluster'?'target':ref)
    expect(adapter.confirmVRPreview).toHaveBeenCalledTimes(1)
    const target={identity:'nuc:1',selectionKind:kind,ownerTokens:['exact'],selectedRef:ref}
    const intent={sequence:3,mode:'move_rotate',action:'confirm',transformMatrix:matrix}
    const result=reduceVRToolShell(initialVRToolShellState,intent,{toolTarget:target,targetSnapshotPresent:true,executorAttached:true})
    expect(result.effect.type).toBe('commit_requested') // Preview coalesced by polling
    expect(reduceVRToolShell(initialVRToolShellState,intent,{targetSnapshotPresent:true}).reason).toBe('stale_target')
  })
  it('does not commit when selection changes during preview startup',async()=>{
    const adapter={beginVRPreview:async()=>({accepted:true}),applyVRPreviewMatrix:()=>false,confirmVRPreview:vi.fn()}
    expect((await commitVRMovePose(adapter,{kind:'base'},matrix)).accepted).toBe(false)
    expect(adapter.confirmVRPreview).not.toHaveBeenCalled()
  })
})

it('rechecks exact selection after asynchronous cluster activation',async()=>{
 let current=true
 const adapter={beginVRPreview:async()=>{current=false;return {accepted:true}},
  cancelVRPreview:vi.fn(),applyVRPreviewMatrix:vi.fn(),confirmVRPreview:vi.fn()}
 const result=await commitVRMovePose(adapter,{kind:'cluster',id:'a'},matrix,()=>current)
 expect(result.reason).toBe('selection_changed')
 expect(adapter.cancelVRPreview).toHaveBeenCalledOnce()
 expect(adapter.applyVRPreviewMatrix).not.toHaveBeenCalled()
 expect(adapter.confirmVRPreview).not.toHaveBeenCalled()
})
