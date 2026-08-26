import { createModal } from './primitives/modal.js'
import { el } from './primitives/dom.js'
import { EXAMPLES, interpretTextIntent, renderHighlightedText } from './text_to_intent.js'

function statusLabel(status) {
  return {
    incomplete: 'Waiting for a supported request',
    ready_with_questions: 'Interpreted — missing parameters remain',
    needs_external_reasoning: 'Blocked — external scientific reasoning required',
    unsupported: 'Unsupported by the v1 interpreter',
  }[status] || status
}

function makeList(items, emptyText) {
  if (!items.length) return el('div', { className: 'tti-muted', text: emptyText })
  return el('ul', { children: items.map(text => el('li', { text })) })
}

function caretOffsetWithin(element) {
  const selection = window.getSelection?.()
  if (!selection?.rangeCount || !element.contains(selection.anchorNode)) return null
  const range = selection.getRangeAt(0).cloneRange()
  range.selectNodeContents(element)
  range.setEnd(selection.anchorNode, selection.anchorOffset)
  return range.toString().length
}

function restoreCaretOffset(element, requestedOffset) {
  if (requestedOffset == null) return
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  let remaining = requestedOffset
  let node = walker.nextNode()
  while (node) {
    if (remaining <= node.textContent.length) {
      const range = document.createRange()
      range.setStart(node, remaining)
      range.collapse(true)
      const selection = window.getSelection?.()
      selection?.removeAllRanges()
      selection?.addRange(range)
      return
    }
    remaining -= node.textContent.length
    node = walker.nextNode()
  }
}

/** Debug-menu test UI for the local text-to-intent interpreter. */
export function initTextToIntentModal() {
  const menuItem = document.getElementById('menu-debug-text-to-intent')
  if (!menuItem) return null

  const input = el('div', {
    className: 'tti-input',
    attrs: {
      contenteditable: 'true',
      spellcheck: 'false',
      'data-placeholder': 'Describe what the origami should do…',
      'aria-label': 'Text-to-intent request',
      role: 'textbox',
      'aria-multiline': 'true',
    },
  })
  const examples = el('div', { className: 'tti-examples' })
  const status = el('div', { className: 'tti-status' })
  const proposal = el('div', { className: 'tti-proposal' })
  const mapping = el('div', { className: 'tti-mapping' })
  const unknowns = el('div')
  const assumptions = el('div')

  EXAMPLES.forEach((example, index) => {
    const button = el('button', {
      className: 'btn btn--sm',
      text: `Example ${index + 1}`,
      attrs: { type: 'button', title: example },
      on: { click: () => { input.textContent = example; update({ moveCaretToEnd: true }) } },
    })
    examples.appendChild(button)
  })

  function update({ preserveCaret = false, moveCaretToEnd = false } = {}) {
    const caret = preserveCaret ? caretOffsetWithin(input) : null
    const result = interpretTextIntent(input.textContent)
    input.innerHTML = result.text ? renderHighlightedText(result) : ''
    restoreCaretOffset(input, moveCaretToEnd ? result.text.length : caret)
    status.className = `tti-status tti-status--${result.status}`
    status.textContent = statusLabel(result.status)
    proposal.textContent = result.proposal || 'No component proposal yet.'
    mapping.replaceChildren(...result.fields.map(([name, value, note, provenance]) => {
      const actualProvenance = provenance || note || 'provided'
      const actualNote = provenance ? note : ''
      return el('div', { className: 'tti-field', children: [
        el('div', { className: 'tti-field__name', text: name }),
        el('div', { className: 'tti-field__value', text: value }),
        el('div', { className: `tti-field__source tti-field__source--${actualProvenance}`, text: actualNote || actualProvenance }),
      ] })
    }))
    unknowns.replaceChildren(makeList(result.unknowns, 'No unresolved requirements.'))
    assumptions.replaceChildren(makeList(result.assumptions, 'No assumptions made.'))
  }

  const body = el('div', { className: 'tti', children: [
    el('p', { className: 'tti-intro', text: 'Local rule-based prototype. Highlighted phrases are recognized; derived fields and blockers remain visibly separate.' }),
    examples,
    input,
    status,
    el('h3', { text: 'Proposed interpretation' }), proposal,
    mapping,
    el('div', { className: 'tti-two-col', children: [
      el('section', { children: [el('h3', { text: 'Missing / blocked' }), unknowns] }),
      el('section', { children: [el('h3', { text: 'Assumptions' }), assumptions] }),
    ] }),
  ] })
  const modal = createModal({ title: 'Text to Intent', size: 'xl', body })
  input.addEventListener('input', () => update({ preserveCaret: true }))
  menuItem.addEventListener('click', () => { modal.open(); input.focus(); update() })
  update()
  return { open: modal.open, close: modal.close, interpret: interpretTextIntent }
}
