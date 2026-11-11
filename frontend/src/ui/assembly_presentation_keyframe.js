import { isPresentationCheckpoint } from '../scene/presentation_checkpoint_animation.js'
import { featureLabels } from '../features/feature_labels.js'

/** Assembly configuration and presentation checkpoints are independent channels. */
export function appendAssemblyPresentationSelect(row, { document, assembly, keyframe, save }) {
  const select = document.createElement('select')
  row.style.flexWrap = 'wrap'
  select.style.cssText = 'flex:1 1 100%;min-width:0;font-size:var(--text-xs)'
  select.setAttribute('aria-label', 'Annotation and view volume state')
  select.title = 'Saved annotation and view volume state'
  const add = (value, text) => {
    const option = document.createElement('option')
    option.value = value; option.textContent = text; select.append(option)
  }
  add('', '— keep annotations / view volumes —')
  add('-2', 'Initial presentation state')
  const log = assembly?.feature_log ?? [], labels = featureLabels(log)
  log.forEach((entry, index) => { if (isPresentationCheckpoint(entry)) add(String(index), labels[index]) })
  select.value = keyframe.feature_log_index == null ? '' : String(keyframe.feature_log_index)
  select.addEventListener('keydown', event => event.stopPropagation())
  select.addEventListener('change', () => save(select.value === '' ? null : Number(select.value)))
  row.append(select)
}
