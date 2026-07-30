/**
 * Reset form controls to their HTML-authored defaults.
 *
 * The MD + oxDNA job panels echo a *selected* job's run conditions into their
 * input fields, so after closing a design (or switching to a different one) the
 * controls would otherwise still show the last job's settings.  On a design
 * switch we reset them to the defaults declared in index.html (the `value` /
 * `selected` / `checked` attributes) rather than hard-coding the numbers here, so
 * the markup stays the single source of truth.
 *
 * Pure DOM helper (no app deps) → unit-tested in form_defaults.test.js.
 */

/** Reset one control to its HTML default.  Handles text/number inputs
 *  (defaultValue), checkboxes (defaultChecked), and selects (the option marked
 *  `selected`, falling back to the first option).  No-op for null/unknown. */
export function resetControlToDefault(el) {
  if (!el) return
  const tag = el.tagName
  if (tag === 'SELECT') {
    // A disabled option is never a legitimate reset target — it names a choice this
    // build/host cannot run.  Skip it, both as the marked default and in the
    // first-option fallback, so the control never comes back showing a greyed-out
    // value the panel would refuse to submit.
    const opts = [...el.options]
    const def = opts.findIndex((o) => o.defaultSelected && !o.disabled)
    const first = def >= 0 ? def : opts.findIndex((o) => !o.disabled)
    el.selectedIndex = first >= 0 ? first : 0
    return
  }
  if (el.type === 'checkbox' || el.type === 'radio') {
    el.checked = el.defaultChecked
    return
  }
  if ('defaultValue' in el) el.value = el.defaultValue
}

/** Reset a list of controls to their HTML defaults (skips nulls). */
export function resetControlsToDefaults(elements) {
  for (const el of elements || []) resetControlToDefault(el)
}
