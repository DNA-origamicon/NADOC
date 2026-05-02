/**
 * Tiny DOM helpers used by primitives. Keep this file dependency-free.
 */

/**
 * Create an HTMLElement with className, attributes, and children.
 *
 * @param {string} tag
 * @param {object} [opts]
 * @param {string} [opts.className]
 * @param {string} [opts.id]
 * @param {string} [opts.text]
 * @param {string} [opts.html]
 * @param {object} [opts.attrs]
 * @param {object} [opts.dataset]
 * @param {(HTMLElement|string|null)[]} [opts.children]
 * @param {object} [opts.on] — { eventName: handler } event listeners
 * @returns {HTMLElement}
 */
export function el(tag, opts = {}) {
  const node = document.createElement(tag)
  if (opts.className) node.className = opts.className
  if (opts.id)        node.id        = opts.id
  if (opts.text != null) node.textContent = opts.text
  if (opts.html != null) node.innerHTML   = opts.html
  if (opts.attrs) {
    for (const [k, v] of Object.entries(opts.attrs)) {
      if (v != null && v !== false) node.setAttribute(k, v === true ? '' : String(v))
    }
  }
  if (opts.dataset) {
    for (const [k, v] of Object.entries(opts.dataset)) {
      if (v != null) node.dataset[k] = String(v)
    }
  }
  if (opts.on) {
    for (const [evt, handler] of Object.entries(opts.on)) {
      node.addEventListener(evt, handler)
    }
  }
  if (opts.children) {
    for (const child of opts.children) {
      if (child == null) continue
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child)
    }
  }
  return node
}

/** Toggle a className on an element. */
export function toggleClass(node, name, force) {
  if (!node) return
  node.classList.toggle(name, force)
}

/** Remove a node from the DOM safely. */
export function detach(node) {
  if (node && node.parentNode) node.parentNode.removeChild(node)
}
