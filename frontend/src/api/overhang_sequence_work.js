import { store } from '../state/store.js'
import { getDocId } from '../shared/doc_id.js'
import { createDocumentRequestScope } from './document_request_scope.js'
import { createSequenceWork } from './sequence_work.js'
const scope = createDocumentRequestScope()
if (import.meta.hot) import.meta.hot.dispose(() => scope.dispose())
export const runSequenceWork = createSequenceWork(() => JSON.stringify([
  getDocId(), store.getState().currentDesign?.id, scope.capture(),
]))
