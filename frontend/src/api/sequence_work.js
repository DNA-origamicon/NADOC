import { sequenceActivity, afterSequencePaint } from '../ui/sequence_activity.js'
import { createSequenceEditQueue } from './sequence_edit_queue.js'
/** Each editor supplies its own document identity; no shared editor state. */
export function createSequenceWork(getContext) {
  const enqueue = createSequenceEditQueue()
  return async (key, work) => {
    const context = getContext(), done = sequenceActivity.begin()
    try {
      return await enqueue(JSON.stringify([context, key]), work, () => getContext() === context)
    } finally { await afterSequencePaint(); done() }
  }
}
