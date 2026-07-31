/**
 * Flattening a FastAPI error body into a readable message (api/client.js).
 *
 * Regression: a 422 (pydantic rejecting the request body before the handler runs)
 * sends `detail` as an ARRAY of {loc, msg, type, input} objects, not a string. Every
 * error path in client.js stored it raw, so callers doing `new Error(lastErrorMessage())`
 * stringified the array to "[object Object]". Starting a NAMD production run longer
 * than the step cap showed exactly that — "Production failed: [object Object]" — while
 * the real reason ("steps: Input should be less than or equal to ...") was sitting in
 * the response the whole time.
 */
import { describe, it, expect } from 'vitest'
import { errorDetailToMessage } from './client.js'

describe('errorDetailToMessage', () => {
  it('passes a hand-raised HTTPException string straight through', () => {
    expect(errorDetailToMessage('Production requires a completed relaxation.'))
      .toBe('Production requires a completed relaxation.')
  })

  it('flattens a pydantic 422 array instead of stringifying it', () => {
    // Verbatim shape from POST /md/jobs/{id}/production-run with steps=250_000_000.
    const detail = [{
      type: 'less_than_equal',
      loc: ['body', 'steps'],
      msg: 'Input should be less than or equal to 50000000',
      input: 250000000,
      ctx: { le: 50000000 },
    }]
    const msg = errorDetailToMessage(detail)
    expect(msg).toBe('steps: Input should be less than or equal to 50000000')
    expect(msg).not.toContain('[object Object]')
  })

  it('joins several validation errors', () => {
    const msg = errorDetailToMessage([
      { loc: ['body', 'steps'], msg: 'too big' },
      { loc: ['body', 'dcd_freq'], msg: 'too small' },
    ])
    expect(msg).toBe('steps: too big; dcd_freq: too small')
  })

  it('summarises the tail rather than dumping every entry', () => {
    const many = Array.from({ length: 6 }, (_, i) => ({ loc: ['body', `f${i}`], msg: 'bad' }))
    const msg = errorDetailToMessage(many)
    expect(msg).toContain('f0: bad')
    expect(msg).toContain('f2: bad')
    expect(msg).not.toContain('f3: bad')
    expect(msg).toContain('and 3 more validation errors')
  })

  it('uses the singular for exactly one omitted entry', () => {
    const four = Array.from({ length: 4 }, (_, i) => ({ loc: ['body', `f${i}`], msg: 'bad' }))
    expect(errorDetailToMessage(four)).toContain('and 1 more validation error')
    expect(errorDetailToMessage(four)).not.toContain('errors')
  })

  it('drops the request-part frame but keeps nested field paths', () => {
    expect(errorDetailToMessage([{ loc: ['body', 'segments', 0, 'steps'], msg: 'bad' }]))
      .toBe('segments.0.steps: bad')
    expect(errorDetailToMessage([{ loc: ['query', 'doc'], msg: 'required' }]))
      .toBe('doc: required')
  })

  it('falls back to the type when an entry has no msg', () => {
    expect(errorDetailToMessage([{ loc: ['body', 'steps'], type: 'int_parsing' }]))
      .toBe('steps: int_parsing')
  })

  it('handles a bare message with no loc', () => {
    expect(errorDetailToMessage([{ msg: 'Field required' }])).toBe('Field required')
  })

  it('uses the fallback for absent, empty, or unusable detail', () => {
    expect(errorDetailToMessage(undefined, 'Bad Gateway')).toBe('Bad Gateway')
    expect(errorDetailToMessage(null, 'Bad Gateway')).toBe('Bad Gateway')
    expect(errorDetailToMessage('', 'Bad Gateway')).toBe('Bad Gateway')
    expect(errorDetailToMessage([], 'Bad Gateway')).toBe('Bad Gateway')
    expect(errorDetailToMessage({}, 'Bad Gateway')).toBe('Bad Gateway')
  })

  it('defaults the fallback when none is given', () => {
    expect(errorDetailToMessage(null)).toBe('Server error')
  })

  it('reads msg off a single object detail', () => {
    expect(errorDetailToMessage({ msg: 'nope' })).toBe('nope')
  })

  it('serialises an unrecognised object rather than losing it', () => {
    expect(errorDetailToMessage({ code: 'E_NOPE' })).toBe('{"code":"E_NOPE"}')
  })

  it('never returns "[object Object]" for a circular detail', () => {
    const circular = { code: 'x' }
    circular.self = circular
    expect(errorDetailToMessage(circular, 'Server error')).toBe('Server error')
  })
})
