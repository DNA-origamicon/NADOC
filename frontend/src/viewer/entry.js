import { mountViewerShortcuts } from './viewer_shortcuts.js'
import { mountPreparedViewer } from './prepared_viewer.js'
import { mountViewerPerformancePanel } from '../ui/viewer_performance_panel.js'
import { mountMeetingInvites } from './meeting_join.js'
const el = id => document.getElementById(id)
try {
  const viewer = mountPreparedViewer({ canvas: el('canvas'), status: el('status'), title: el('title'),
    fileInput: el('file'), resetButton: el('reset'), modeInput: el('mode') })
  const unmountJoin = mountMeetingInvites({ viewer })
  const panel = el('performance')
  const unmountPanel = mountViewerPerformancePanel(panel, () => panel.close())
  const unmountShortcuts = mountViewerShortcuts({ performancePanel: panel })
  el('close-metrics').onclick = () => panel.close()
  window.addEventListener('pagehide', event => {
    viewer.performanceApi.stop()
    if (!event.persisted) { unmountJoin(); unmountPanel(); unmountShortcuts(); viewer.dispose() }
  })
  if (import.meta.env.DEV && new URLSearchParams(location.search).has('test')) window.__preparedViewer = viewer
} catch (error) { el('status').textContent = `Viewer could not start: ${error.message}` }
