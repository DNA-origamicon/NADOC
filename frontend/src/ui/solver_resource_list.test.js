// @vitest-environment jsdom
import { it, expect } from 'vitest'
import { solverResourceView, createSolverResourceList } from './solver_resource_list.js'

it('combines known Alpine wait with solver runtime, without using NAMD time-to-result', () => {
  const view = solverResourceView({ availability: { gpus_free: 1, gpus_total: 4, wait_min: 30, time_to_result_h: 99 } }, 'alpine', { seconds: 3600 })
  expect(view.availability).toContain('1 / 4 GPUs free')
  expect(view.wait).toBe('30 min')
  expect(view.completion).toBe('≈ 1.5 h')
})
it('keeps missing waits and RunPod startup unknown and reports unavailable capacity', () => {
  expect(solverResourceView({}, 'alpine', { seconds: 3600 })).toMatchObject({ availability: 'Unknown', wait: 'Unknown', completion: '≈ 1.0 h + wait' })
  expect(solverResourceView({ stock: 'Low' }, 'runpod', { seconds: 3600 })).toMatchObject({ availability: 'Low stock', wait: 'Startup unknown', completion: '≈ 1.0 h + startup' })
  expect(solverResourceView({ stock: 'None' }, 'runpod', {})).toMatchObject({ availability: 'Unavailable', completion: 'Unknown' })
  expect(solverResourceView({}, 'alpine', { seconds: 2 }).completion).not.toContain('0 min')
})
it('renders safe text and native selectable/disabled rows without losing keyboard focus', () => {
  const mount = document.createElement('div')
  document.body.append(mount)
  let chosen
  const list = createSolverResourceList({ mount, target: 'runpod', reason: row => row.id === 'small' ? 'Too small' : '', onChange: id => { chosen = id } })
  list.render([{ id: 'small', display: '<script>bad</script>' }, { id: 'large' }], '')
  expect(mount.querySelector('script')).toBeNull()
  expect(mount.querySelector('[value=small]').disabled).toBe(true)
  const radio = mount.querySelector('[value=large]')
  radio.focus(); radio.click()
  expect(chosen).toBe('large')
  expect(document.activeElement).toBe(radio)
  expect(radio.closest('label').dataset.selected).toBe('true')
  mount.remove()
})
