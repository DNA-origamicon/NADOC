/**
 * Input + Select factories.
 *
 * Produces native form controls with `.input` / `.select` classes from
 * components.css.
 */

import { el } from './dom.js'

/**
 * @param {object} opts
 * @param {'text'|'number'|'search'|'email'|'password'} [opts.type='text']
 * @param {string} [opts.value]
 * @param {string} [opts.placeholder]
 * @param {'sm'|'md'|'lg'} [opts.size='md']
 * @param {boolean} [opts.data=false]   — apply monospace family
 * @param {string} [opts.id]
 * @param {string} [opts.name]
 * @param {boolean} [opts.disabled=false]
 * @param {boolean} [opts.required=false]
 * @param {number} [opts.min]
 * @param {number} [opts.max]
 * @param {number|string} [opts.step]
 * @param {string} [opts.className]
 * @param {(value: string, e: Event) => void} [opts.onInput]
 * @param {(value: string, e: Event) => void} [opts.onChange]
 * @param {(e: KeyboardEvent) => void} [opts.onKeydown]
 * @returns {HTMLInputElement}
 */
export function createInput(opts = {}) {
  const {
    type = 'text', value, placeholder,
    size = 'md', data = false,
    id, name, disabled = false, required = false,
    min, max, step,
    className,
    onInput, onChange, onKeydown,
  } = opts

  const classes = ['input']
  if (size !== 'md') classes.push(`input--${size}`)
  if (data)          classes.push('input--data')
  if (className)     classes.push(className)

  const input = el('input', {
    className: classes.join(' '),
    attrs: {
      type, id, name, placeholder,
      value: value != null ? String(value) : undefined,
      disabled: disabled || undefined,
      required: required || undefined,
      min, max, step,
    },
  })
  if (onInput)   input.addEventListener('input',   (e) => onInput(input.value, e))
  if (onChange)  input.addEventListener('change',  (e) => onChange(input.value, e))
  if (onKeydown) input.addEventListener('keydown', onKeydown)
  return input
}

/**
 * @param {object} opts
 * @param {Array<{ value: string, label: string, disabled?: boolean }>} opts.options
 * @param {string} [opts.value]
 * @param {'sm'|'md'|'lg'} [opts.size='md']
 * @param {string} [opts.id]
 * @param {string} [opts.name]
 * @param {boolean} [opts.disabled=false]
 * @param {string} [opts.className]
 * @param {(value: string, e: Event) => void} [opts.onChange]
 * @returns {HTMLSelectElement}
 */
export function createSelect(opts = {}) {
  const {
    options = [], value,
    size = 'md',
    id, name, disabled = false,
    className,
    onChange,
  } = opts

  const classes = ['select']
  if (size !== 'md') classes.push(`select--${size}`)
  if (className)     classes.push(className)

  const select = el('select', {
    className: classes.join(' '),
    attrs: { id, name, disabled: disabled || undefined },
    children: options.map(o => el('option', {
      attrs: { value: o.value, disabled: o.disabled || undefined, selected: o.value === value || undefined },
      text: o.label,
    })),
  })
  if (onChange) select.addEventListener('change', (e) => onChange(select.value, e))
  return select
}
