import { hashRecipeFile, hashRecipeText, recipeFileUpgrade, requireRecipeFile,
  RECIPE_RESPONSE_LIMIT } from '../api/part_recipe_file_endpoints.js'
import { cloneRepairInput, repairIssues } from './part_repair_model.js'

const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const identity = value => typeof value === 'string' && value.length > 0 && value.length <= 256
const fail = () => { throw new Error('The recovery response does not match the inspected original file') }

function sourceReceipt(value, file, digest) {
  if (!value || !sha(digest) || value.source_sha256 !== digest || value.source_size_bytes !== file.size
      || !identity(value.source_design_id) || value.old_state_verified !== false || value.basis !== 'saved_recipe_inputs'
      || !Number.isSafeInteger(value.stripped_recovery_field_count) || value.stripped_recovery_field_count < 0
      || !Array.isArray(value.excluded_fields) || value.excluded_fields.length > 256
      || !value.excluded_fields.every(identity) || new Set(value.excluded_fields).size !== value.excluded_fields.length) fail()
  return Object.freeze({ source_sha256: digest, source_size_bytes: file.size, source_design_id: value.source_design_id,
    old_state_verified: false, basis: 'saved_recipe_inputs', stripped_recovery_field_count: value.stripped_recovery_field_count,
    excluded_fields: Object.freeze([...value.excluded_fields]) })
}

function inspected(response, file, digest) {
  if (response?.status !== 'review' || Object.hasOwn(response, 'candidate') || Object.hasOwn(response, 'recovered_file')
      || !Array.isArray(response.upgrades) || !response.upgrades.length || response.upgrades.length > 2000) fail()
  const recovery = sourceReceipt(response.recovery, file, digest), seen = new Set()
  // Each offer has a fixed small grammar. The operation budget applies to the
  // selected <=64 actions, not to a valid inspected catalog of <=2000 rows.
  const upgrades = response.upgrades.map(offer => {
    if (typeof offer?.label !== 'string' || !offer.label.length || offer.label.length > 256) fail()
    const action = recipeFileUpgrade(offer)
    if (seen.has(action.feature_id)) fail()
    seen.add(action.feature_id)
    return Object.freeze({ label: offer.label, action: Object.freeze(action) })
  })
  return Object.freeze({ status: 'review', recovery, upgrades: Object.freeze(upgrades) })
}

async function recovered(response, review, file, digest, hashText) {
  const receipt = sourceReceipt(response.recovery, file, digest)
  if (JSON.stringify(receipt) !== JSON.stringify(review.recovery) || Object.hasOwn(response, 'candidate')
      || response.validation?.passed !== true || !['verified', 'reproduced_import'].includes(response.proof?.status)
      || !identity(response.recovery.recovered_design_id) || response.recovery.recovered_design_id === receipt.source_design_id) fail()
  const artifact = response.recovered_file
  if (!artifact || Object.keys(artifact).length !== 3 || typeof artifact.json_text !== 'string'
      || !Number.isSafeInteger(artifact.size_bytes) || artifact.size_bytes < 1 || artifact.size_bytes > RECIPE_RESPONSE_LIMIT
      || !sha(artifact.sha256) || artifact.json_text.length !== artifact.size_bytes
      || /[^\x00-\x7f]/.test(artifact.json_text)) fail()
  // Server ASCII encoding makes character and UTF-8 byte counts identical. Hash
  // that exact text; JSON.parse/stringify would alter large integers/floats.
  if (await hashText(artifact.json_text) !== artifact.sha256) fail()
  return Object.freeze({ text: artifact.json_text, id: response.recovery.recovered_design_id })
}

/** File-local proposal only: no store, document publication, autosave or opener. */
export function createRecipeFileRecoveryController({ api, download, hashFile = hashRecipeFile, hashText = hashRecipeText }) {
  let state = { file: null, review: null, actions: [], acknowledged: false, ready: false, busy: null, error: null, issues: [] }
  let epoch = 0, disposed = false, flight = null, digest = null, artifact = null
  const listeners = new Set()
  const getState = () => ({ ...state, actions: state.actions.map(action => ({ ...action })), issues: [...state.issues] })
  function emit() { if (!disposed) for (const listener of listeners) listener(getState()) }
  function invalidate() { epoch++; flight?.abort(); flight = null; artifact = null; state = { ...state, busy: null, ready: false } }
  const current = token => !disposed && token === epoch
  function begin(operation) {
    invalidate(); flight = new AbortController()
    state = { ...state, busy: operation, error: null, issues: [] }; emit()
    return { token: epoch, signal: flight.signal, file: state.file }
  }
  function failure(error, token) {
    if (!current(token)) return
    state = { ...state, error: error?.message ?? 'Recovery failed', issues: repairIssues(error), ready: false }
  }
  function finish(token) { if (current(token)) { flight = null; state = { ...state, busy: null }; emit() } }
  function failedResponse(response) {
    if (!['failed', 'unverified'].includes(response?.status) || !Array.isArray(response.issues)
        || Object.hasOwn(response, 'candidate') || Object.hasOwn(response, 'recovered_file')) fail()
    state = { ...state, error: 'The recipe could not be recovered. Review the reported issues.', issues: response.issues }
  }
  return {
    getState,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    chooseFile(file) {
      if (disposed) return
      invalidate(); digest = null
      state = { file: null, review: null, actions: [], acknowledged: false, ready: false, busy: null, error: null, issues: [] }
      try { if (file != null) { requireRecipeFile(file); state.file = file } }
      catch (error) { state.error = error.message }
      emit()
    },
    async inspect() {
      if (disposed || !state.file || state.busy) return
      state = { ...state, review: null, actions: [], acknowledged: false }
      const { token, signal, file } = begin('inspect')
      try {
        const checkedDigest = digest ?? await hashFile(file, { signal })
        if (!current(token)) return
        digest = checkedDigest
        const response = await api.inspect(file, { signal })
        if (!current(token)) return
        if (response?.status !== 'review') failedResponse(response)
        else state = { ...state, review: inspected(response, file, digest) }
      } catch (error) { failure(error, token) }
      finally { finish(token) }
    },
    selectUpgrade(offer, selected) {
      if (disposed) return
      if (!state.review?.upgrades.includes(offer) || typeof selected !== 'boolean') throw new Error('Inspect this repair before selecting it')
      const actions = state.actions.filter(action => action.feature_id !== offer.action.feature_id)
      if (selected) actions.push(recipeFileUpgrade(offer))
      if (actions.length > 64) throw new Error('Select at most 64 structural repairs')
      const detached = cloneRepairInput(actions)
      invalidate(); state = { ...state, actions: detached, error: null, issues: [] }; emit()
    },
    acknowledgeExclusions(value) {
      if (disposed) return
      invalidate(); state = { ...state, acknowledged: value === true, error: null, issues: [] }; emit()
    },
    async evaluate() {
      if (disposed || state.busy || !state.review || !state.actions.length || !state.acknowledged) return
      const request = cloneRepairInput({ version: 1, expected_source_sha256: digest, actions: state.actions })
      const review = state.review, { token, signal, file } = begin('recover')
      try {
        const response = await api.recover(file, request, { signal })
        if (!current(token)) return
        if (response?.status !== 'ready') failedResponse(response)
        else {
          const checked = await recovered(response, review, file, digest, hashText)
          if (!current(token)) return
          artifact = checked; state = { ...state, ready: true }
        }
      } catch (error) { failure(error, token) }
      finally { finish(token) }
    },
    download() {
      if (disposed || !state.ready || !artifact) return
      const stem = state.file.name.replace(/\.nadoc$/i, '').replace(/[\/\\\x00-\x1f\x7f]/g, '_').slice(0, 160) || 'design'
      download(artifact.text, `${stem}-recovered.nadoc`)
    },
    cancel() { if (!disposed) { invalidate(); emit() } },
    dispose() { invalidate(); disposed = true; digest = null; state = { ...state, file: null, review: null, actions: [] }; listeners.clear() },
  }
}
