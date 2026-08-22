/**
 * strand_menu_items.js — the ONE definition of the strand right-click items that
 * the 3D viewport and the cadnano editor share.
 *
 * Both editors used to build their strand menu independently — `_showColorMenu`
 * in `scene/selection_manager.js` and `_showStrandCtxMenu` in
 * `cadnano-editor/main.js` — so every shared item (Make Reference, Convert to OH
 * binder, Edit extensions…, Edit sequence…) existed twice, with labels and
 * visibility rules that could and did drift. This module owns the shared set;
 * each editor appends its own extras and renders the result through
 * `ui/primitives/context_menu.js`.
 *
 * PURE: takes a plain description of what was right-clicked plus a handlers bag,
 * returns a declarative item array for `createContextMenu`. No DOM, no store.
 * Items are `{label, onClick, title?}` or `{type:'separator'}`; a handler that is
 * absent hides its item, so an editor opts in only to what it implements.
 */

/**
 * @param {object} ctx
 * @param {string[]} ctx.strandIds      — the strands the menu acts on (≥1)
 * @param {string}  [ctx.strandType]    — 'scaffold' | 'staple' | 'oh_binder' | 'linker'
 * @param {boolean} [ctx.allReference]  — every selected strand is reference geometry
 * @param {boolean} [ctx.anyReference]  — at least one selected strand is reference geometry
 * @param {object}  handlers            — omit one to hide its item
 * @param {(ids: string[], makeReference: boolean) => void} [handlers.onSetReference]
 * @param {(id: string) => void} [handlers.onConvertToBinder]
 * @param {(id: string) => void} [handlers.onConvertToScaffold]
 * @param {(id: string) => void} [handlers.onEditSequence]        — non-scaffold strands
 * @param {(id: string) => void} [handlers.onAssignScaffoldSequence] — scaffold strands
 * @param {(ids: string[]) => void} [handlers.onEditExtensions]
 * @returns {Array<{label: string, onClick: Function, title?: string} | {type: 'separator'}>}
 */
export function buildStrandMenuItems(ctx = {}, handlers = {}) {
  const ids        = ctx.strandIds ?? []
  const single     = ids.length === 1 ? ids[0] : null
  const type       = ctx.strandType ?? 'staple'
  const isScaffold = type === 'scaffold'
  const isBinder   = type === 'oh_binder'
  const items = []

  if (!ids.length) return items

  if (handlers.onSetReference) {
    const referenceItem = (makeReference) => ({
      label: makeReference ? 'Make Reference' : 'Make Active',
      title: 'Reference geometry is an inactive backdrop: ignored by all automatic '
           + 'features (bend/twist, sequence assignment, scaffold routing, autostaple, '
           + 'crossovers) and excluded from exports/validation, but still visible '
           + '(translucent) and manually editable. Use it to build off an existing part.',
      onClick: () => handlers.onSetReference(ids, makeReference),
    })
    if (ctx.anyReference && !ctx.allReference) {
      items.push(referenceItem(true), referenceItem(false))
    } else {
      items.push(referenceItem(!ctx.allReference))
    }
  }

  // Scaffold ⇄ OH-binder conversions are single-strand only: each relinks ONE
  // strand's domains against the overhangs it pairs with.
  if (single && isScaffold && handlers.onConvertToBinder) {
    items.push({
      label: 'Convert to OH binding strand',
      title: 'Re-designate this strand as an overhang-binding oligo: link each domain to '
           + 'the overhang it antiparallel-pairs with (tagging the partner as an overhang '
           + 'if needed) and recolor it. Add a fluorophore afterward via "Edit extensions".',
      onClick: () => handlers.onConvertToBinder(single),
    })
  }
  if (single && isBinder && handlers.onConvertToScaffold) {
    items.push({
      label: 'Convert to scaffold',
      title: 'Revert this overhang-binding oligo back to a scaffold strand: clear its '
           + 'binder links and remove any overhang the original conversion auto-created '
           + '(once nothing else binds it).',
      onClick: () => handlers.onConvertToScaffold(single),
    })
  }

  // "Edit sequence…" means two different things by strand type, and both editors
  // must agree on the label — a scaffold opens the preset/custom scaffold modal,
  // anything else opens the hand-edit dialog. Single strand only either way.
  if (single && isScaffold && !ctx.allReference && handlers.onAssignScaffoldSequence) {
    items.push({
      label: 'Edit sequence…',
      title: 'Assign a scaffold sequence (M13mp18 / p7560 / p8064 / custom) to this '
           + 'scaffold strand only, leaving other scaffold strands untouched.',
      onClick: () => handlers.onAssignScaffoldSequence(single),
    })
  }
  if (single && !isScaffold && handlers.onEditSequence) {
    items.push({
      label: 'Edit sequence…',
      title: "Type this strand's bases 5'→3'. When the scaffold is sequenced the paired "
           + 'scaffold bases are shown above the field and mismatches are highlighted '
           + '— any bases are still allowed.',
      onClick: () => handlers.onEditSequence(single),
    })
  }

  if (handlers.onEditExtensions) {
    items.push({ type: 'separator' })
    items.push({
      label: 'Edit extensions…',
      title: "Add or edit a 5'/3' terminal extension (extra bases and/or a modification "
           + 'such as a fluorophore or biotin).',
      onClick: () => handlers.onEditExtensions(ids),
    })
  }

  return dropEdgeSeparators(items)
}

/** Strip leading/trailing/duplicate separators left by hidden items. */
export function dropEdgeSeparators(items) {
  const out = []
  for (const it of items ?? []) {
    if (it?.type === 'separator') {
      if (!out.length || out[out.length - 1]?.type === 'separator') continue
    }
    out.push(it)
  }
  while (out.length && out[out.length - 1]?.type === 'separator') out.pop()
  return out
}
