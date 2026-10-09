import { docHeaders } from '../shared/doc_id.js'

/** One browser-owned decision at a time. Native replies only identify an option;
 * the original async handler remains the sole owner of the operation. */
export function createVRPrompts({ request = fetch, context = () => null, detailAllowed = () => true, onError = console.error } = {}) {
  let active = false, failed = false, version = Math.floor(Math.random() * 1e9), heartbeat = 0
  let queue = [], sending = false, dirty = true, lastPublish = 0, epoch = 0, lastDetailAllowed
  const sameContext = item => JSON.stringify(item.headers) === JSON.stringify(docHeaders()) && item.context === context()
  function finish(value) {
    const item = queue.shift()
    if (item) item.resolve(value)
    dirty = true
  }
  function reset() {
    epoch++;active = false;failed = false
    while (queue.length) finish(null)
    dirty = true;lastPublish = 0
  }
  async function publish() {
    if (!active || sending) return
    if (lastDetailAllowed !== detailAllowed()) dirty = true
    while (queue.length && !sameContext(queue[0])) finish(null)
    if (!dirty && (!queue.length || Date.now() - lastPublish < 1000)) return
    const item = queue[0], generation = epoch, allowed = detailAllowed()
    sending = true;dirty = false
    try {
      const response = await request('/api/vr/prompt', {
        method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: item?.version ?? ++version, heartbeat: ++heartbeat,
          detail_allowed: allowed, title: item?.title ?? '', message: item?.message ?? '', options: item?.options ?? [] }),
      })
      if (!response.ok) throw new Error('Could not display the VR prompt. The action was cancelled.')
      if (generation === epoch) { lastPublish = Date.now(); lastDetailAllowed = allowed }
    } catch (error) {
      if (generation === epoch) {
        while (queue.length) finish(null)
        active = false;failed = true // Never resume an operation after a transport failure.
        onError(error.message)
      }
    } finally {
      sending = false
      if (generation === epoch && dirty) void publish()
    }
  }
  return {
    setActive(value) { if (!value) reset();else { active = true;dirty = true;void publish() } },
    ask({ title, message, choices }) {
      if (failed) return Promise.resolve(null)
      if (!active) return null
      if (!choices.length || choices.length > 4) return null
      return new Promise(resolve => {
        queue.push({ version: ++version, title, message: typeof message === 'string' ? message : message?.textContent ?? '',
          options: choices.map((c, i) => ({ id: String(i), label: c.label })), choices, resolve,
          context: context(), headers: docHeaders() })
        dirty = true;void publish()
      })
    },
    activate(event) {
      const item = queue[0]
      if (!active || !item || event.version !== item.version) return
      if (!sameContext(item) || event.id === 'dismiss') finish(null)
      else {
        const index = item.options.findIndex(o => o.id === event.id)
        if (index < 0) return
        finish(item.choices[index].value)
      }
      void publish()
    },
    publish, reset,
  }
}
