/**
 * Button factory.
 *
 * Produces a <button> with the right `.btn` classes from components.css.
 * Replaces scattered `el.style.cssText = 'padding:6px 14px;...'` patterns.
 *
 * Variant matrix:
 *   variant: 'default' | 'primary' | 'ghost' | 'danger' | 'success'
 *   size:    'sm' | 'md' | 'lg'
 *   block:   true → full-width
 *   icon:    true → square icon button (use with `iconEl`)
 */

import { el } from './dom.js'

/**
 * @param {object} opts
 * @param {string} [opts.label]
 * @param {HTMLElement|null} [opts.iconEl]   — optional SVG/icon element prepended to label
 * @param {'default'|'primary'|'ghost'|'danger'|'success'} [opts.variant='default']
 * @param {'sm'|'md'|'lg'} [opts.size='md']
 * @param {boolean} [opts.block=false]
 * @param {boolean} [opts.icon=false]        — square icon-only button
 * @param {boolean} [opts.disabled=false]
 * @param {string} [opts.title]              — hover tooltip
 * @param {string} [opts.type='button']
 * @param {() => void} [opts.onClick]
 * @param {string} [opts.className]          — extra classes
 * @returns {HTMLButtonElement}
 */
export function createButton(opts = {}) {
  const {
    label = '',
    iconEl = null,
    variant = 'default',
    size = 'md',
    block = false,
    icon = false,
    disabled = false,
    title,
    type = 'button',
    onClick,
    className,
  } = opts

  const classes = ['btn']
  if (variant !== 'default') classes.push(`btn--${variant}`)
  if (size !== 'md')         classes.push(`btn--${size}`)
  if (block)                 classes.push('btn--block')
  if (icon)                  classes.push('btn--icon')
  if (className)             classes.push(className)

  const children = []
  if (iconEl) children.push(iconEl)
  if (label)  children.push(el('span', { text: label }))

  const btn = el('button', {
    className: classes.join(' '),
    attrs: { type, title, disabled: disabled || undefined },
    children: children.length ? children : (label ? [label] : undefined),
  })
  if (onClick) btn.addEventListener('click', onClick)
  return btn
}
