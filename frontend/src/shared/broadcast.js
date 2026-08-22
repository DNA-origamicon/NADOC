/**
 * BroadcastChannel wrapper for cross-tab design sync.
 *
 * All NADOC tabs (3D window + any cadnano editor tabs) share the channel
 * "nadoc-design".  When a mutation completes, the mutating tab emits a
 * "design-changed" message.  All other tabs re-fetch the design from the
 * backend (which is the single source of truth).
 *
 * Message format:
 *   { type: "design-changed", source: <tab-uuid>, version: <optional int>,
 *     geometry_unchanged: <optional bool>, changed_helix_ids: <optional string[]>,
 *     metadata_only: <optional bool> }
 *
 * The `source` field is a UUID generated once per page load.  Recipients
 * ignore messages where source === ownId to prevent echo loops.
 *
 * Usage (emitter, e.g. after a successful API mutation):
 *   import { nadocBroadcast } from '../shared/broadcast.js'
 *   nadocBroadcast.emit('design-changed')
 *
 * Usage (receiver, e.g. in editor main.js):
 *   nadocBroadcast.onMessage(({ type }) => {
 *     if (type === 'design-changed') refetchDesign()
 *   })
 */

import { getDocId } from './doc_id.js'

const _id = crypto.randomUUID?.() ?? `${Date.now()}${Math.random().toString(16).slice(2)}`
const _channel = new BroadcastChannel('nadoc-design')

export const nadocBroadcast = {
  /** Emit a message to all OTHER tabs. Auto-stamps the sender's document id. */
  emit(type, extra = {}) {
    _channel.postMessage({ type, source: _id, docId: getDocId(), ...extra })
  },

  /**
   * Register a handler for messages from OTHER tabs.
   * Returns an unsubscribe function.
   */
  onMessage(handler) {
    function _listener(event) {
      if (event.data?.source === _id) return   // ignore own messages
      handler(event.data)
    }
    _channel.addEventListener('message', _listener)
    return () => _channel.removeEventListener('message', _listener)
  },

  /** True if a received message came from a tab editing THIS tab's document.
   * Use to scope same-document events (design-changed, selection-changed) so a
   * mutation in one document doesn't make another document's tab refetch. */
  isSameDoc(data) { return (data?.docId ?? null) === getDocId() },

  /** This tab's unique ID (for debugging). */
  get tabId() { return _id },
}
