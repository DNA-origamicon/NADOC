import { describe, expect, it } from 'vitest'
import { interpretTextIntent, renderHighlightedText } from './text_to_intent.js'
import { initTextToIntentModal } from './text_to_intent_modal.js'

describe('text-to-intent v1', () => {
  it('maps a mixed nanorod surface and preserves literal cargo labels', () => {
    const result = interpretTextIntent('I want a nanorod covered in 70% CD-48 and 30% CD-4')
    expect(result.status).toBe('ready_with_questions')
    expect(result.proposal).toContain('1D nanorod')
    expect(result.fields).toContainEqual(['Surface composition', '70% CD-48 / 30% CD-4', 'provided'])
    expect(result.spans.map(span => span.text)).toEqual(['nanorod', '70% CD-48', '30% CD-4'])
  })

  it('normalizes platfom and attaches the S shape to the overhang track', () => {
    const result = interpretTextIntent('Make a platfom with a track of overhangs in an S shape')
    expect(result.status).toBe('ready_with_questions')
    expect(result.proposal).toBe('2D platform with an S-shaped track of overhang attachment sites')
    expect(result.fields.map(field => field[0])).toEqual(['Component', 'Interface', 'Layout'])
    expect(renderHighlightedText(result)).toContain('tti-mark--component')
  })

  it('refuses to invent a microtubule-equivalent rigidity', () => {
    const result = interpretTextIntent('Design a polymer origami with the same rigid as cell microtubuls')
    expect(result.status).toBe('needs_external_reasoning')
    expect(result.proposal).toContain('mechanical target unresolved')
    expect(result.unknowns.join(' ')).toMatch(/persistence length.*axial stiffness.*torsional stiffness/)
    expect(result.spans.some(span => span.concept === 'cellular microtubule')).toBe(true)
  })
})

describe('text-to-intent modal', () => {
  it('opens from the Debug menu and updates from a sample request', () => {
    document.body.innerHTML = '<button id="menu-debug-text-to-intent">Text to Intent</button>'
    const modal = initTextToIntentModal()
    document.getElementById('menu-debug-text-to-intent').click()
    expect(modal).not.toBeNull()
    expect(document.querySelector('.tti')).not.toBeNull()

    const input = document.querySelector('.tti-input')
    input.textContent = 'Make a platfom with a track of overhangs in an S shape'
    input.dispatchEvent(new Event('input'))
    expect(document.querySelector('.tti-proposal').textContent).toContain('S-shaped track')
    expect(input.querySelectorAll('.tti-mark').length).toBe(3)
    modal.close()
    expect(document.querySelector('.modal__overlay')).toBeNull()
  })
})
