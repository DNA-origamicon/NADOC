/** Serialize saves per job so a late response cannot overwrite a newer edit. */
export function createOxdnaJobSettings({ save, onSaved, onError, delayMs = 250 }) {
  const entries = new Map()
  function entry(id) {
    if (!entries.has(id)) entries.set(id, { pending: null, latest: null, timer: null, active: null })
    return entries.get(id)
  }
  async function flush(id) {
    const state = entry(id)
    clearTimeout(state.timer)
    if (state.active) return state.active
    state.active = (async () => {
      while (state.pending) {
        const patch = state.pending
        state.pending = null
        try {
          const saved = await save(id, patch)
          if (!saved?.job_id) throw new Error('Could not save oxDNA surface and anchor settings.')
          if (!state.pending) state.latest = null
          onSaved?.(saved, !state.pending)
        } catch (error) {
          state.pending ||= patch
          throw error
        }
      }
    })()
    try { await state.active } finally { state.active = null }
  }
  return {
    change(job, patch) {
      const state = entry(job.job_id)
      state.pending = state.latest = structuredClone(patch)
      clearTimeout(state.timer)
      state.timer = setTimeout(() => { void flush(job.job_id).catch(error => onError?.(error, job.job_id)) }, delayMs)
    },
    overlay(job) {
      const patch = entries.get(job?.job_id)?.latest
      return patch ? { ...job, run_config: { ...job.run_config, ...patch } } : job
    },
    hasPending: id => !!entries.get(id)?.latest,
    flush,
  }
}

export function relaxationElementsSettings(elements = {}) {
  return {
    surface: elements.surface?.enabled ? {
      dir: elements.surface.dir, offset_nm: elements.surface.offsetNm,
      position_nm: elements.surface.positionNm, stiff: elements.surface.stiff,
    } : null,
    anchors: elements.anchors || [],
    surface_anchors: elements.surface?.enabled ? (elements.surfaceAnchors || []) : [],
    surface_strands: elements.surface?.enabled && elements.surfaceStrands?.enabled
      ? elements.surfaceStrands : null,
  }
}

/** Continuations can apply a field; relaxation deliberately remains field-free. */
export function continuationElementsSettings(elements = {}) {
  return {
    ...relaxationElementsSettings(elements),
    field: elements.field?.enabled && elements.field.field_pN > 0
      ? { field_pN: elements.field.field_pN, dir: elements.field.dir } : null,
  }
}

export function relaxationElementsSignature(settings = {}) {
  const surface = settings.surface
  const strands = settings.surface_strands ? { ...settings.surface_strands } : null
  if (strands) delete strands.built
  return JSON.stringify({
    surface: surface ? { dir: surface.dir, stiff: surface.stiff,
      ...(surface.position_nm != null ? { position_nm: surface.position_nm } : { offset_nm: surface.offset_nm }) } : null,
    anchors: settings.anchors || [], surface_anchors: settings.surface_anchors || [],
    surface_strands: strands,
    field: settings.field || null,
  })
}
