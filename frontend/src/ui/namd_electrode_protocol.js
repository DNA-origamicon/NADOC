export const ELECTRODE_PROTOCOL='electrode_equilibration_namd'
export function confirmElectrodeProtocol({enabled,job,confirm=message=>window.confirm(message)}) {
  if(!enabled || (job?.protocol || job?.prep_params?.protocol)===ELECTRODE_PROTOCOL)return true
  return confirm('Two electrodes are enabled, but this saved job uses another protocol. Use Electrode relaxation in the New job wizard to prepare the fixed compartment and slab electrostatics. Continuing runs the saved job unchanged: it will not acquire these electrodes and may fail or simulate a different system. Continue anyway?')
}
