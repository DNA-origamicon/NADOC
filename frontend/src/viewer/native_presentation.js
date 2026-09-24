/** Called after the job panel's Off action has cancelled playback and restored poses. */
export async function restoreNativePresentation({ stopLive, setRepresentation, clearSimulationVisuals }) {
  stopLive()
  await setRepresentation('full')
  // Off deliberately resumes setup previews (including PEG). Clear them after
  // representation listeners have finished, before the native snapshot is exported.
  clearSimulationVisuals()
}
