/** EM panel layout and contextual controls; no solver or document state. */
export const EM_PANEL_HTML = `<header><strong>EM analysis</strong><button data-close aria-label="Close EM analysis">×</button></header>
      <div class="em-actions"><button data-run>Calculate 520 nm map</button><button data-cancel disabled>Cancel</button></div>
      <label>Wavelength (nm)<input data-wavelength type="number" min="187.9" max="1937" step="any" value="520"></label>
      <p>Plane wave in water (n = 1.333). Coupled, full-wave gold spheres. Wavelength range: 187.9–1937 nm, supported by the bundled Johnson–Christy optical constants.</p>
      <label>Solver<select data-solver><option value="multipole">Full multipole Maxwell · optimized</option><option value="multipole_reference">Full multipole Maxwell · reference evaluation</option></select></label>
      <label>Optical DNA coating<select data-shell><option value="ssdna_wlc">Full coverage · length-based ssDNA estimate</option><option value="manual">Full coverage · specified thickness</option><option value="none">Bare spheres · original model</option></select></label>
      <p>Optical coverage is independent of explicitly modeled conjugates. These common shell settings apply to every particle.</p>
      <label>Conjugated oligo length (nt)<input data-oligo-length type="number" min="1" max="200" step="1" value="20"></label>
      <label>ssDNA persistence length (nm)<input data-persistence type="number" min="0.1" max="10" step="0.1" value="2.5"></label>
      <label>Specified radial shell thickness (nm)<input data-thickness type="number" min="0" max="100" step="0.1" value="2.5"></label>
      <label>Effective shell refractive index<input data-shell-index type="number" min="1" max="2.5" step="0.01" value="1.7"></label>
      <p data-shell-estimate></p>
      <label>Electric-field polarization<select data-polarization><option value="parallel">Along first particle pair</option><option value="perpendicular">Across first particle pair</option></select></label>
      <label>Sampling<select data-sampling><option value="field_adaptive">Adaptive · field variation and hotspots</option><option value="adaptive">Adaptive · near particle surfaces</option><option value="uniform">Uniform grid</option></select></label>
      <label>Sampling quality / budget<select data-resolution><option value="25">Preview · 15,625 + adaptive refinement</option><option value="33" selected>Standard · 35,937 + adaptive refinement</option><option value="49">Fine · 117,649 + adaptive refinement</option></select></label>

      <button data-bare-retry hidden>Calculate without DNA coating</button>
      <p data-status role="status" aria-live="polite">Uses the current particle positions, including hidden gold. Calculate to begin.</p>
      <label>Display<select data-mode><option value="volume">3D field cloud</option><option value="smooth">Smooth 3D glow</option><option value="xy">XY slice</option><option value="xz">XZ slice</option><option value="yz">YZ slice</option></select></label>
      <label>Sampling dot size: <output data-dot-size-value>3 px</output><input data-dot-size type="range" min="1" max="12" step="0.5" value="3"></label>
      <label>EM lighting<select data-lighting><option value="off">Plain samples</option><option value="glow">Glowing samples · fast</option><option value="illuminate">Glow + nearby surface illumination</option></select></label>
      <p>Visible EM is included in Appearance image and video exports. Glow and surface illumination are illustrative, not emitted optical power. Illumination combines samples into at most eight lights per calculated field; no additional shadows.</p>
      <label>Slice position<input data-slice type="range" min="0" max="1" step="0.02" value="0.5"></label>
      <p class="muted">Smooth 3D glow interpolates between field samples into a continuous additive glow. Dot size applies to points and slices only.</p>
      <label>3D intensity cutoff<input data-minimum type="number" min="0" max="1000" step="0.5" value="3"></label>
      <p>Adjust intensity color bounds and colormap in the viewport legend. Color bounds do not change the intensity cutoff.</p>
      <p>Log color scale: |E<sub>total</sub>|² / |E<sub>incident</sub>|². Slice axes follow the particle pair; XY contains the pair and E. Adaptive slices show center samples from cells intersecting the selected plane. Point density indicates sampling effort, not field strength; use color for intensity.</p>
      <details><summary>Model scope and numerical limits</summary><p>Bulk Johnson–Christy gold in water. Optional full-coverage dielectric DNA shells include fields within the shell; origami bodies and substrates are excluded. The length-based model uses the worm-like-chain RMS size with 0.59 nm/nt as an effective radial-size proxy, not a calibrated optical thickness. Persistence length depends on salt and sequence; 2.5 nm is a poly-T pure-water literature value. Shell n=1.7 is an adjustable literature starting point, not universal for hydrated DNA. Overlapping shells are rejected; compression and interpenetration require another dielectric geometry model. This is a static snapshot, not a trajectory average or fluorescence prediction. Diameters 5–100 nm; metal gaps ≥2 nm. Metal interiors are masked. A 1% multipole probe check does not certify grid convergence; compare resolutions before interpreting a peak.</p></details>
      <div class="em-actions"><button data-download disabled>Download field + inputs</button></div><button data-clear>Clear field</button>`

export function prepareEMPanel(panel) {
  const paragraphs=[...panel.querySelectorAll(':scope > p:not([data-status]):not([data-shell-estimate])')]
  const keys=['wavelength','shell','lighting','mode','minimum','mode']
  for(const [i,p] of paragraphs.entries()){
    const label=panel.querySelector(`[data-${keys[i]}]`).closest('label')
    label.title=[label.title,p.textContent].filter(Boolean).join(' ');p.remove()
  }
  const tips={
    'oligo-length':'The length-based shell uses worm-like-chain RMS size with 0.59 nm per nucleotide as an effective radial-size proxy, not a calibrated optical thickness.',
    persistence:'Persistence length depends on salt and sequence; 2.5 nm is a poly-T pure-water literature value.',
    'shell-index':'Shell n=1.7 is an adjustable literature starting point, not universal for hydrated DNA.',
    thickness:'Radial dielectric shell thickness around every gold particle. Overlapping shells are rejected.',
    resolution:'A 1% multipole probe check does not certify grid convergence; compare sampling resolutions before interpreting a peak.'
  }
  for(const [key,tip] of Object.entries(tips))panel.querySelector(`[data-${key}]`).closest('label').title=tip
  const details=panel.querySelector('details')
  panel.querySelector('[data-solver]').closest('label').title=details.textContent;details.remove()
  panel.querySelector('[data-run]').title=panel.querySelector('[data-status]').textContent
  panel.querySelector('[data-status]').textContent='Ready to calculate.'
  panel.querySelector('[data-shell]').closest('label').append(panel.querySelector('[data-shell-estimate]'))
}

export function updateEMPanel(panel) {
  const model=panel.querySelector('[data-shell]').value, mode=panel.querySelector('[data-mode]').value
  for(const [key,visible] of Object.entries({'oligo-length':model==='ssdna_wlc',persistence:model==='ssdna_wlc',
    thickness:model==='manual','shell-index':model!=='none','dot-size':mode!=='smooth',slice:!['smooth','volume'].includes(mode)})){
    const input=panel.querySelector(`[data-${key}]`);input.disabled=!visible;input.closest('label').hidden=!visible
  }
  panel.querySelector('[data-shell-estimate]').hidden=model==='none'
  panel.querySelector('[data-run]').textContent=`Calculate ${panel.querySelector('[data-wavelength]').value} nm map`
}
