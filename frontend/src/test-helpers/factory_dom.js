/**
 * Shared jsdom helper for factory-extraction tests.
 *
 * A factory like `initX({ ... })` finds its DOM purely via `document.getElementById`,
 * which does not care about nesting — so a flat set of by-id elements is enough to
 * exercise the wiring. Each test previously hand-wrote a `mountDom()` with a literal
 * HTML template; `mountIds` replaces that with the id→tag list the factory actually
 * queries.
 *
 * NOT a `.test.js` file → ignored by vitest's test glob; imported by the real specs.
 *
 * @example
 *   mountIds(['menu-view-fret', 'menu-view-fluorescence'])           // all <div>… wait, buttons:
 *   mountIds({ 'menu-view-fret': 'button', 'overhang-list': 'div',
 *              'overhang-label-size': 'input' })
 *
 * @param {string[] | Object<string,string>} spec
 *   Array of ids (each created as `defaultTag`), or an object mapping id → tagName.
 * @param {object} [opts]
 * @param {string} [opts.defaultTag='div'] — tag for array-form ids
 * @returns {Object<string, HTMLElement>} id → element, for convenient assertions
 */
export function mountIds(spec, { defaultTag = 'div' } = {}) {
  document.body.innerHTML = ''
  const entries = Array.isArray(spec)
    ? spec.map(id => [id, defaultTag])
    : Object.entries(spec)
  const els = {}
  for (const [id, tag] of entries) {
    const el = document.createElement(tag)
    el.id = id
    document.body.appendChild(el)
    els[id] = el
  }
  return els
}

/**
 * Reset jsdom between tests (mirrors the per-spec `beforeEach(() => { body = '' })`).
 */
export function clearDom() {
  document.body.innerHTML = ''
}
