/** Extension slabs inherit exactly their terminal domain's cluster scope. */
export function slabInCluster(nuc, helices, selected, terminalHelices, terminalDomains, domains, baseKeys, forceAxes) {
  if (!nuc.extension_id) return helices.has(nuc.helix_id) && selected(nuc)
  if (!helices.has(terminalHelices.get(nuc.extension_id))) return false
  if (baseKeys) return selected(nuc)
  return forceAxes || !domains || domains.has(terminalDomains.get(nuc.extension_id))
}
