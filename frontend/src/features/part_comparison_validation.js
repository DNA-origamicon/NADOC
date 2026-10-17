/** Shared closed display DTO guards; no model construction or store effects. */
export const fail = message => { throw new Error(`Comparison unavailable: ${message}`) }
export const finite = value => typeof value === 'number' && Number.isFinite(value)
export const integer = value => Number.isSafeInteger(value) && value >= 0
export function text(value, limit = 256, empty = false) {
  if (typeof value !== 'string' || value.length > limit || (!empty && !value.length)) fail('invalid display identity or label')
}
export function shape(value, keys) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype || Object.keys(value).length !== keys.length
      || keys.some(key => !Object.hasOwn(value, key))) fail('incomplete or unsupported display fields')
}
export function vector(value, count) {
  if (!Array.isArray(value) || value.length !== count || !value.every(finite)) fail('nonfinite display coordinates')
}
export function list(value, maximum) {
  if (!Array.isArray(value) || value.length > maximum) fail('display allowance exceeded')
}
export function unique(items, key = value => value.id) {
  const seen = new Set()
  for (const item of items) {
    const id = key(item); text(id)
    if (seen.has(id)) fail('ambiguous resource identity')
    seen.add(id)
  }
}
