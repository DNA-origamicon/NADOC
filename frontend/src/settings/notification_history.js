import { preference } from './preferences.js'
const history = []
export function notificationHistory() { return history.map(entry => ({ ...entry })) }
export function clearNotificationHistory() { history.length = 0 }
export function recordNotification(message, severity = 'info') {
  history.push({ time: new Date().toISOString(), severity, message: String(message) })
  if (history.length > 200) history.shift()
  if (!['success', 'error'].includes(severity)) return
  if (preference('desktopNotifications') && document.hidden && globalThis.Notification?.permission === 'granted') {
    try { new Notification('NADOC', { body: String(message), tag: 'nadoc-activity' }) } catch { /* Browser may prohibit desktop notifications. */ }
  }
  if (preference('notificationSound')) {
    const Audio = globalThis.AudioContext || globalThis.webkitAudioContext
    if (!Audio) return
    try {
      const context = new Audio()
      if (context.state === 'suspended') { void context.close(); return }
      const tone = context.createOscillator(), gain = context.createGain()
      tone.frequency.value = severity === 'error' ? 330 : 660
      gain.gain.value = .025; tone.connect(gain); gain.connect(context.destination)
      tone.start(); tone.stop(context.currentTime + .12); tone.onended = () => { void context.close() }
    } catch { /* Autoplay rules can suppress sounds until a user gesture. */ }
  }
}
