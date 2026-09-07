import { expect, it } from 'vitest'
import { initAnimationReadinessBar } from './animation_readiness_bar.js'
it('shows per-keyframe readiness, positions the playhead and ignores superseded callbacks', () => {
  document.body.innerHTML = '<input id="scrub" type="range">'
  const bar = initAnimationReadinessBar({ scrub: document.getElementById('scrub') })
  const animation = { keyframes: ['a', 'b'].map((id, i) => ({ id, trajectory_job_id: id, trajectory_scope: 'job', hold_duration_s: i + 1 })) }
  const old = bar.setAnimation(animation)
  old({ jobId: 'a', scope: 'job', phase: 'ready', trajectoryFrames: 3 })
  const els = document.querySelectorAll('[role="progressbar"]')
  expect(els[0].getAttribute('aria-valuenow')).toBe('100')
  expect(els[1].getAttribute('aria-valuenow')).toBe('0')
  expect(els[1].title).toContain('queued')
  expect(els[0].style.flexGrow).toBe('1')
  expect(els[1].style.flexGrow).toBe('2')
  bar.setTime(1.5)
  expect(document.querySelector('[aria-label="Trajectory readiness by keyframe"]').lastChild.style.left).toBe('50%')
  bar.refreshAnimation({ keyframes: animation.keyframes.map(kf => ({ ...kf, hold_duration_s: 3 })) })
  expect(els[0].style.flexGrow).toBe('3')
  expect(els[0].getAttribute('aria-valuenow')).toBe('100')
  bar.setAnimation(animation)
  old({ jobId: 'a', scope: 'job', phase: 'ready' })
  expect(document.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')).toBe('0')
  bar.destroy()
  expect(document.querySelector('[data-role="animation-readiness"]')).toBeNull()
})

it('updates live loading percentages and partial prepared frames before completion', () => {
  document.body.innerHTML = '<input id="scrub" type="range">'
  const bar = initAnimationReadinessBar({ scrub: document.getElementById('scrub') })
  const report = bar.setAnimation({ keyframes: [{ id: 'a', trajectory_job_id: 'a', trajectory_scope: 'job', hold_duration_s: 2 }] })
  const el = document.querySelector('[role="progressbar"]')
  for (const done of [25, 50, 75, 100]) {
    report({ jobId: 'a', scope: 'job', phase: 'load', done, total: 100 })
    expect(el.textContent).toContain(`${done}% loading`)
    expect(el.getAttribute('aria-valuenow')).toBe(String(done))
    expect(el.dataset.readyPercent).toBe('0')
    expect(el.firstChild.style.background).toContain(`${done}%`)
  }
  report({ jobId: 'a', scope: 'job', phase: 'frames', done: 2, total: 4, trajectoryFrames: 4, grid: [0, 1, 2, 3], readyIndices: [0, 1] })
  expect(el.textContent).toContain('50%')
  expect(el.textContent).not.toContain('loading')
  expect(el.dataset.readyPercent).toBe('50')
  report({ jobId: 'a', scope: 'job', phase: 'ready' })
  expect(el.getAttribute('aria-valuenow')).toBe('100')
  bar.destroy()
})
