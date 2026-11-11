import { expect, it, vi } from 'vitest'
import { appendAssemblyPresentationSelect } from './assembly_presentation_keyframe.js'

it('offers checkpoint indices independently of assembly configurations and sidebar filters', () => {
  const row = document.createElement('div'), save = vi.fn()
  appendAssemblyPresentationSelect(row, { document, assembly: { feature_log: [
    { op_kind: 'assembly-add-instance' }, { op_kind: 'annotations-state', label: 'Caption' },
    { op_kind: 'view-volumes-state' },
  ] }, keyframe: { configuration_id: 'pose', feature_log_index: 1 }, save })
  const select = row.querySelector('select')
  expect([...select.options].map(option => option.value)).toEqual(['', '-2', '1', '2'])
  expect(select.value).toBe('1')
  select.value = '2'; select.dispatchEvent(new Event('change'))
  expect(save).toHaveBeenCalledWith(2)
})
