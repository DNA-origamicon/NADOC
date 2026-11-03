// Smooth is a presentation clock, not simulated time. Eight existing interpolation
// fractions span at least 250 ms; exact endpoints and raw playback stay separate.
export function smoothSampleInterval(milliseconds) {
 return Math.max(250 / 8, Number.isFinite(milliseconds) && milliseconds > 0 ? milliseconds * 1.25 : 0)
}
export async function presentSmoothTransition({ prepare, active, delivery, wait, show }) {
 if (await prepare() === false || !active()) return
 for (let sample = 1; sample <= 8; sample++) {
  await wait(smoothSampleInterval(delivery()?.milliseconds))
  if (!active()) return
  // Do not overwrite a displayed sample while its snapshot is still publishing.
  // Short cancellable waits avoid catch-up bursts after a slow delivery.
  while (delivery()?.busy) {
   await wait(16)
   if (!active()) return
  }
  if (sample < 8) show(sample / 8)
 }
}
