import { afterEach, expect, it, vi } from 'vitest'
import { webcrypto } from 'node:crypto'
import { presentationSourceHash, readPresentationPackage } from './presentation_package.js'
import { presentationHTML } from './compiled_presentation.js'
const clips = [{ name: 'A', video: 'data:video/webm;base64,AA==', first: 'data:image/jpeg;base64,AA==', last: 'data:image/jpeg;base64,AA==', duration: 1 }]
afterEach(() => vi.unstubAllGlobals())
it('recognizes the same source after reload but rejects changed model or camera definitions', async () => {
  vi.stubGlobal('crypto', webcrypto)
  const source = { id: 'part', helices: [{ id: 'h', n: 10 }], camera_poses: [{ id: 'c', position: [0, 0, 1] }] }
  const hash = await presentationSourceHash(source)
  expect(hash).toHaveLength(64)
  expect(await presentationSourceHash({ camera_poses: source.camera_poses, helices: source.helices, id: 'part', metadata: { name: 'renamed' } })).toBe(hash)
  expect(await presentationSourceHash({ ...source, helices: [{ id: 'h', n: 11 }] })).not.toBe(hash)
})
it('reads only embedded data and never evaluates imported scripts', () => {
  const html = presentationHTML('Talk', clips) + '<script>window.unsafeImported = true</script>'
  expect(readPresentationPackage(html).clips).toEqual(clips)
  expect(window.unsafeImported).toBeUndefined()
})
it('rejects external media and malformed timeline ranges', () => {
  expect(() => readPresentationPackage(presentationHTML('Talk', [{ ...clips[0], video: 'https://example.com/x.webm' }]))).toThrow('Invalid')
  expect(() => readPresentationPackage(presentationHTML('Talk', clips, { animation: { keyframes: [{}] }, ranges: [{ start: 10, end: 11 }] }))).toThrow('timing')
})

it('reopens a selected clip with its original timeline offset and preceding context', () => {
  const info = { animation: { keyframes: [{ id: 'before' }, { id: 'trajectory' }] }, clipKeyframeIds: ['trajectory'], ranges: [{ start: 10, end: 11 }] }
  expect(readPresentationPackage(presentationHTML('Clip', clips, info)).inspection).toEqual(info)
  expect(() => readPresentationPackage(presentationHTML('Clip', clips, { ...info, clipKeyframeIds: ['missing'] }))).toThrow('timeline')
})
