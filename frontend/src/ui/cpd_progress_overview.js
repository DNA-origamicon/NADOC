import { el } from './primitives/dom.js'

export function evidenceSources(keys, sources) {
  const entries = (keys ?? []).map(key => sources[key]).filter(Boolean)
  return el('details', { className: 'cpd-progress__sources', children: [
    el('summary', { text: 'Evidence sources' }),
    ...entries.flatMap(src => [el('code', { text: src.file }), el('code', { text: `SHA-256 ${src.sha256}` })]),
  ] })
}

export function renderProgressOverview(node, data) {
  node.replaceChildren()
  if (!data.progress) return
  const { progress, sources } = data
  const cards = items => items.map(item => el('li', { children: [
    el('strong', { text: item.label }), el('p', { text: item.detail }), evidenceSources(item.evidence, sources),
  ] }))
  node.append(el('p', { text: progress.summary }), el('div', { className: 'cpd-progress__overview-columns', children: [
    el('section', { children: [el('h3', { text: 'Completed' }), el('ul', { children: cards(progress.completed) })] }),
    el('section', { children: [el('h3', { text: 'Remaining' }), el('ul', { children: cards(progress.remaining) })] }),
  ] }), el('details', { className: 'cpd-progress__history', children: [
    el('summary', { text: 'Earlier campaign and limitations' }), el('ul', { children: cards(progress.history) }),
  ] }))
}
