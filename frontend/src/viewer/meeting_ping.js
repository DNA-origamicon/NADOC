/** A quiet local chime, unlocked by the existing join/editor gesture. */
export function createMeetingPing({ document: doc = document, AudioContext = globalThis.AudioContext ?? globalThis.webkitAudioContext } = {}) {
  let audio = null, disposed = false
  const unlock = () => {
    if (disposed || !AudioContext) return
    try { audio ??= new AudioContext(); if (audio.state === 'suspended') void audio.resume().catch(() => {}) } catch { /* Sound availability never blocks sharing. */ }
  }
  doc.addEventListener('pointerdown', unlock, true); doc.addEventListener('keydown', unlock, true)
  return {
    play() {
      if (disposed || audio?.state !== 'running') return
      const oscillator = audio.createOscillator(), gain = audio.createGain(), time = audio.currentTime
      oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(880, time); oscillator.frequency.exponentialRampToValueAtTime(660, time + .22)
      gain.gain.setValueAtTime(0, time); gain.gain.linearRampToValueAtTime(.07, time + .015); gain.gain.exponentialRampToValueAtTime(.001, time + .3)
      oscillator.connect(gain); gain.connect(audio.destination); oscillator.start(time); oscillator.stop(time + .32)
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect() }
    },
    dispose() { disposed = true; doc.removeEventListener('pointerdown', unlock, true); doc.removeEventListener('keydown', unlock, true); void audio?.close().catch(() => {}) },
  }
}
