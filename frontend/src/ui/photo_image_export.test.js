import {it,expect,vi} from 'vitest'
vi.mock('./op_progress.js',()=>({showOpProgress:vi.fn(()=>42),updateOpProgress:vi.fn(),hideOpProgress:vi.fn()}))
import {showOpProgress,updateOpProgress,hideOpProgress} from './op_progress.js'
import {exportPhotoImage} from './photo_image_export.js'
it('reports real sample progress and closes the owned popup on renderer failure',async()=>{
  const mode={renderToBlob:vi.fn(async(w,h,{onProgress})=>{
    onProgress({label:'Path tracing · 32/64 samples',fraction:.5})
    throw new Error('GPU lost')
  })}
  await expect(exportPhotoImage(mode,64,64)).rejects.toThrow('GPU lost')
  expect(updateOpProgress).toHaveBeenCalledWith(42,{label:'Path tracing · 32/64 samples',fraction:.5})
  expect(hideOpProgress).toHaveBeenCalledWith(42)
})
it('passes cancellation into the renderer and never downloads an aborted result',async()=>{
  const mode={renderToBlob:vi.fn(async(w,h,{signal})=>{
    showOpProgress.mock.calls.at(-1)[2].onCancel()
    signal.throwIfAborted()
  })}
  await expect(exportPhotoImage(mode,64,64)).rejects.toMatchObject({name:'AbortError'})
  expect(hideOpProgress).toHaveBeenCalledWith(42)
})
