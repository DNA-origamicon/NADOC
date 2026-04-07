/**
 * BroadcastChannel wrapper for cross-tab design sync.
 *
 * All NADOC tabs (3D window + any cadnano editor tabs) share the channel
 * "nadoc-design".  When a mutation completes, the mutating tab emits a
 * "design-changed" message.  All other tabs re-fetch the design from the
 * backend (which is the single source of truth).
 *
 * Message format:
 *   { type: "design-changed", source: <tab-uuid>, version: <optional int> }
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

const _id = crypto.randomUUID()
const _channel = new BroadcastChannel('nadoc-design')

export const nadocBroadcast = {
  /** Emit a message to all OTHER tabs. */
  emit(type, extra = {}) {
    _channel.postMessage({ type, source: _id, ...extra })
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

  /** This tab's unique ID (for debugging). */
  get tabId() { return _id },
}
