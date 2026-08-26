const EXAMPLES = [
  'I want a nanorod covered in 70% CD-48 and 30% CD-4',
  'Make a platfom with a track of overhangs in an S shape',
  'Design a polymer origami with the same rigid as cell microtubuls',
]

const RULES = [
  { label: 'component', concept: 'nanorod', re: /\bnano[ -]?rod\b/gi },
  { label: 'component', concept: 'platform', re: /\bplat(?:form|fom)\b/gi },
  { label: 'component', concept: 'polymer origami', re: /\bpolymer origami\b/gi },
  { label: 'interface', concept: 'overhang track', re: /\btrack of overhangs?\b/gi },
  { label: 'layout', concept: 'S-shaped path', re: /\bS[ -]shape(?:d)?\b/gi },
  { label: 'mechanics', concept: 'rigidity target', re: /\b(?:rigid|rigidity)\b/gi },
  { label: 'reference', concept: 'cellular microtubule', re: /\b(?:cell(?:ular)?\s+)?microtub(?:ule|ules|ul|uls)\b/gi },
]

function collectMatches(text) {
  const spans = []
  for (const rule of RULES) {
    for (const match of text.matchAll(rule.re)) {
      spans.push({
        start: match.index,
        end: match.index + match[0].length,
        text: match[0],
        label: rule.label,
        concept: rule.concept,
      })
    }
  }

  const compositionRe = /\b(\d{1,3}(?:\.\d+)?)\s*%\s+([A-Za-z][A-Za-z0-9-]*)/g
  for (const match of text.matchAll(compositionRe)) {
    spans.push({
      start: match.index,
      end: match.index + match[0].length,
      text: match[0],
      label: 'composition',
      concept: `${Number(match[1])}% ${match[2]}`,
      percentage: Number(match[1]),
      species: match[2],
    })
  }
  return spans.sort((a, b) => a.start - b.start || b.end - a.end)
}

/** Pure, deliberately conservative v1 interpreter for the Debug prototype. */
export function interpretTextIntent(rawText) {
  const text = String(rawText || '')
  const spans = collectMatches(text)
  const has = concept => spans.some(span => span.concept === concept)
  const compositions = spans.filter(span => span.label === 'composition')
  const unknowns = []
  const assumptions = []
  const fields = []
  let proposal = null
  let status = 'incomplete'

  if (has('nanorod')) {
    proposal = '1D nanorod with surface-distributed conjugation sites'
    fields.push(['Component', 'Nanorod', 'provided'])
    if (compositions.length) {
      fields.push([
        'Surface composition',
        compositions.map(item => item.concept).join(' / '),
        'provided',
      ])
      const total = compositions.reduce((sum, item) => sum + item.percentage, 0)
      if (Math.abs(total - 100) > 0.01) unknowns.push(`Surface percentages total ${total}%, not 100%.`)
    }
    unknowns.push('Rod length and attachment-site density are not specified.')
    assumptions.push('“Covered in” is interpreted as a mixed surface presentation, not encapsulation.')
    status = 'ready_with_questions'
  } else if (has('platform')) {
    proposal = '2D platform with an S-shaped track of overhang attachment sites'
    fields.push(['Component', 'Platform', 'normalized from “platfom” if misspelled', 'derived'])
    if (has('overhang track')) fields.push(['Interface', 'Track of overhangs', 'provided'])
    if (has('S-shaped path')) fields.push(['Layout', 'S-shaped path', 'provided'])
    unknowns.push('Platform dimensions, track spacing, and overhang count are not specified.')
    assumptions.push('“S shape” modifies the overhang track, not the platform outline.')
    status = 'ready_with_questions'
  } else if (has('polymer origami')) {
    proposal = 'Repeating polymer-origami assembly; mechanical target unresolved'
    fields.push(['Component', 'Polymer origami', 'provided'])
    if (has('rigidity target')) fields.push(['Mechanical objective', 'Match a reference rigidity', 'derived'])
    if (has('cellular microtubule')) fields.push(['Reference', 'Cellular microtubule', 'normalized from “microtubuls” if misspelled', 'derived'])
    unknowns.push('The target rigidity needs an external value, definition, and environmental context.')
    unknowns.push('“Rigidity” could mean bending persistence length, axial stiffness, or torsional stiffness.')
    status = 'needs_external_reasoning'
  }

  if (!proposal && text.trim()) {
    unknowns.push('No supported v1 component family was recognized.')
    status = 'unsupported'
  }

  return { text, spans, fields, proposal, status, unknowns, assumptions }
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  })[char])
}

export function renderHighlightedText(result) {
  if (!result.text) return '<span class="tti-muted">Relevant phrases will be highlighted here.</span>'
  let cursor = 0
  let html = ''
  for (const span of result.spans) {
    if (span.start < cursor) continue
    html += escapeHtml(result.text.slice(cursor, span.start))
    html += `<mark class="tti-mark tti-mark--${span.label}" title="${escapeHtml(span.concept)}">${escapeHtml(span.text)}</mark>`
    cursor = span.end
  }
  return html + escapeHtml(result.text.slice(cursor))
}

export { EXAMPLES }
