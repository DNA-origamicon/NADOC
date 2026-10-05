import { el } from './primitives/dom.js'
import './tool_sections.css'

export function toolSection(title, children = []) {
  return el('fieldset', { className: 'tool-section', children: [el('legend', { text: title }), ...children] })
}
