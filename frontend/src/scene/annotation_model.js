/**
 * Pure annotation entry model: defaults, normalisation, renderability and
 * persistence shape. No DOM / THREE / store imports.
 *
 * An annotation is VIEW metadata attached to stable selection refs (see
 * selection_ref.js). It never touches topology or geometry.
 */
import { dedupeSelectionRefs } from './selection_ref.js'
import { isAnnotationIcon } from './annotation_icons.js'

export const CALLOUT_TYPES = Object.freeze([
  { key: 'elbow', label: 'Box · elbow leader' },
  { key: 'line', label: 'Box · straight leader' },
  { key: 'rounded', label: 'Rounded · straight leader' },
  { key: 'shelf', label: 'Underline shelf' },
])
const CALLOUT_KEYS = new Set(CALLOUT_TYPES.map(type => type.key))

export const ANNOTATION_COLORS = Object.freeze([
  '#f0883e', '#58a6ff', '#3fb950', '#f778ba', '#d2a8ff', '#e3b341', '#ff7b72', '#39c5cf',
])

export const SIZE_RANGE = Object.freeze({ min: 0.7, max: 2.5, step: 0.05, default: 1 })
export const TRANSPARENCY_RANGE = Object.freeze({ min: 0, max: 0.8, step: 0.05, default: 0 })
export const MAX_TEXT_LENGTH = 500

const HEX = /^#[0-9a-f]{6}$/i
const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value))
const finiteOr = (value, fallback) => (typeof value === 'number' && Number.isFinite(value) ? value : fallback)

let _serial = 0
export function newAnnotationId() {
  _serial += 1
  return `anno-${Date.now().toString(36)}-${_serial.toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}

/** Coerce arbitrary input (user edit, stored JSON) into a valid entry. */
export function normalizeAnnotation(input = {}, { index = 0 } = {}) {
  const color = typeof input.color === 'string' && HEX.test(input.color)
    ? input.color.toLowerCase()
    : ANNOTATION_COLORS[index % ANNOTATION_COLORS.length]
  const pos = input.screenPos
  const screenPos = pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)
    ? { x: clamp(pos.x, 0, 1), y: clamp(pos.y, 0, 1) }
    : null
  return {
    id: typeof input.id === 'string' && input.id ? input.id : newAnnotationId(),
    text: typeof input.text === 'string' ? input.text.slice(0, MAX_TEXT_LENGTH) : '',
    icon: isAnnotationIcon(input.icon) ? input.icon : null,
    calloutType: CALLOUT_KEYS.has(input.calloutType) ? input.calloutType : 'elbow',
    color,
    transparency: clamp(finiteOr(input.transparency, TRANSPARENCY_RANGE.default), TRANSPARENCY_RANGE.min, TRANSPARENCY_RANGE.max),
    size: clamp(finiteOr(input.size, SIZE_RANGE.default), SIZE_RANGE.min, SIZE_RANGE.max),
    manual: input.manual === true,
    screenPos,
    visible: input.visible !== false,
    refs: dedupeSelectionRefs(input.refs ?? []),
  }
}

export const annotationHasContent = entry =>
  !!entry && (String(entry.text ?? '').trim().length > 0 || isAnnotationIcon(entry.icon))

/** A callout appears only when it has text or an icon (and isn't switched off). */
export const annotationIsRenderable = entry => !!entry && entry.visible !== false && annotationHasContent(entry)

/** Browser-storage key used before annotations moved into the .nadoc file (read once, for migration). */
export const legacyStorageKeyFor = designId => `nadoc.annotations.v1:${designId}`

/** Entry → the snake_case shape stored in the .nadoc (`Design.annotations`). */
export function annotationToWire(entry) {
  return {
    id: entry.id, text: entry.text, icon: entry.icon, callout_type: entry.calloutType, color: entry.color,
    transparency: entry.transparency, size: entry.size, manual: entry.manual,
    screen_pos: entry.screenPos ? [entry.screenPos.x, entry.screenPos.y] : null,
    visible: entry.visible, refs: entry.refs,
  }
}

/** Inverse of annotationToWire; tolerant of missing/foreign fields. */
export function annotationFromWire(wire, { index = 0 } = {}) {
  const pos = Array.isArray(wire?.screen_pos) ? { x: wire.screen_pos[0], y: wire.screen_pos[1] } : null
  return normalizeAnnotation({
    id: wire?.id, text: wire?.text, icon: wire?.icon, calloutType: wire?.callout_type, color: wire?.color,
    transparency: wire?.transparency, size: wire?.size, manual: wire?.manual, screenPos: pos,
    visible: wire?.visible, refs: wire?.refs,
  }, { index })
}

/** Legacy browser-storage payload → entries. Corrupt / foreign payloads become an empty list, never a throw. */
export function deserializeAnnotations(raw) {
  try {
    const value = typeof raw === 'string' ? JSON.parse(raw) : raw
    const list = Array.isArray(value?.entries) ? value.entries : []
    const seen = new Set()
    const out = []
    for (const item of list) {
      if (!item || typeof item !== 'object') continue
      const entry = normalizeAnnotation(item, { index: out.length })
      if (seen.has(entry.id)) continue
      seen.add(entry.id)
      out.push(entry)
    }
    return out
  } catch {
    return []
  }
}
