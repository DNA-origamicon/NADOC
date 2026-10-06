/** Build the native sidebar inventory from the desktop DOM and actual right-tab wiring.
 * No browser/server/workspace writes. --check detects drift in checked-in outputs.
 */
import { COLORING_SUPPORT } from '../src/scene/coloring_modes.js'
import { VR_REPRESENTATIONS } from '../src/scene/vr_representations.js'
import { standardizeSimulationCardOrder } from '../src/ui/simulation_card_order.js'
import { sidebarSections } from './vr-sidebar-sections.mjs'
import fs from 'node:fs'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { JSDOM } from 'jsdom'
const root = path.resolve(import.meta.dirname, '../..')
const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8')
const dom = new JSDOM(html)
const document = dom.window.document
// Execute the desktop's section relocation and representation construction, with
// only its stack/observer shell stubbed (no cloned views or persisted UI state).
const source = fs.readFileSync(path.join(root, 'frontend/src/ui/right_sidebar_tabs.js'), 'utf8')
const init = new Function('MutationObserver', 'initSidebarStack', source.replace(/^import .*$/gm, '').replace('export function', 'function') + '\nreturn initRightSidebarTabs;')
init(dom.window.MutationObserver, () => ({ dispose() {} }))({ document, storage: null })
// Use the desktop's canonical engine-card order as well as its right-tab relocation.
globalThis.document = document
for (const id of ['oxdna-jobs-body','mrdna-jobs-body','cando-jobs-body','snupi-jobs-body','blade-jobs-body','md-jobs-panel-body']) standardizeSimulationCardOrder(document.getElementById(id))
delete globalThis.document
const clean = s => String(s || '').replace(/\s+/g, ' ').trim()
const ownText = el => { if (!el) return ''; const copy=el.cloneNode(true); copy.querySelectorAll('select,input,textarea,button').forEach(n=>n.remove()); return clean(copy.textContent) }
const ascii = s => clean(s).replace(/σ/g,'sigma').replace(/η/g,'eta').replace(/→/g,' to ').replace(/↓/g,' down ').replace(/…/g,'...').normalize('NFKD').replace(/×/g, 'x').replace(/[′’]/g, "'").replace(/[−–—]/g, '-').replace(/°/g, ' deg').replace(/µ/g, 'u').replace(/[^\x20-\x7e]/g, '')
const supported = {
  'dimensions-record': 'dimension:new', 'dimensions-clear': 'dimension:clear',
  'menu-view-detail-beads': 'repr:4', 'menu-view-atomistic-vdw': 'repr:5',
  'menu-view-hull-prism': 'repr:6', 'menu-view-surface': 'repr:7', 'menu-view-surface-detail': 'repr:11',
  'menu-view-mrdna-coarse': 'repr:8', 'menu-view-mrdna-fine': 'repr:9', 'menu-view-oxdna': 'repr:10',
  'menu-view-detail-cylinders': 'repr:0', 'menu-view-detail-full': 'repr:1',
  'menu-view-atomistic-ballstick': 'repr:2', 'menu-view-atomistic-stick': 'repr:3',
  'repr-color-strand': 'color:0', 'repr-color-base': 'color:1',
  'repr-color-cluster': 'color:2', 'repr-color-cpk': 'color:3',
  'reset-btn': 'recenter',
}
const tabs = []
for (const side of ['left', 'right']) {
  for (const button of document.querySelectorAll(`#${side}-tab-strip [data-tab]`)) {
    const key = button.dataset.tab
    const pane = document.getElementById(`${side === 'left' ? '' : 'right-'}tab-content-${key}`)
    const tab = { side, key, label: clean(button.textContent), rows: [] }
    const seen = new Set()
    const sections = sidebarSections(pane, key, clean)
    const controls = [...(pane?.querySelectorAll('button, input:not([type="hidden"]), select, textarea') || [])]
    for (const el of pane?.querySelectorAll('*') || []) {
      if (sections.headings.has(el)) { tab.rows.push(sections.headings.get(el)); continue }
      const index = controls.indexOf(el)
      if (index < 0) continue
      const id = el.id || el.dataset.target || `${key}:control:${index}`
      if (seen.has(id)) throw Error(`Duplicate desktop control: ${id}`)
      seen.add(id)
      const section = el.closest('.panel-section, fieldset')
      const heading = section?.querySelector('h2, h3, legend')
      const context = clean(heading?.textContent) || tab.label
      const labelled = el.labels?.[0] || el.closest('label') || el.parentElement.querySelector('label')
      const buttonLabel = clean(el.textContent)
      const label = clean(el.getAttribute('aria-label')) || (el.tagName === 'BUTTON' ? (/[A-Za-z0-9]/.test(buttonLabel) ? buttonLabel : clean(el.title)) : ownText(labelled)) || clean(el.title) || clean(el.placeholder) || id
      const options = el.tagName === 'SELECT' ? [...el.options].map(o => ({ value: o.value, label: clean(o.textContent) })) : []
      tab.rows.push({ id, parents: sections.parents(el), label: label.length < 3 ? `${context}: ${label}` : label, section: context, kind: el.tagName.toLowerCase(), options,
        action: supported[id] || '', source: 'frontend/index.html',
        reason: supported[id] ? '' : 'Not supported in VR yet' })
    }
    tabs.push(tab)
  }
}
// Data-driven desktop widgets: represent the control template, not one user's
// jobs/annotations/plate contents. Explicit source links keep the mapping reviewable.
const add = (side, key, section, source, rows) => {
  const tab = tabs.find(t => t.side === side && t.key === key)
  const desktopTitle = {'Feature Log / Configurations':'Feature Log', Simulations:'Simulate', 'Cluster entries':'Movable Clusters', 'Connection entries':'Overhang Connections'}[section] || section
  let header = tab.rows.find(r => r.kind === 'section' && r.label.toLowerCase() === desktopTitle.toLowerCase())
  if (!header) {
    const id = `section:${key}:template:${section.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
    const parent = tab.rows.find(r => r.kind === 'section' && r.label === (key === 'assembly' ? 'Assembly' : key === 'dynamics' ? 'Simulate' : ''))
    header = {id, label:section, section:'', kind:'section', options:[], action:id, parents:parent?[...parent.parents,parent.id]:[], source, reason:''}
    let at = parent ? tab.rows.findIndex(r => r.id === parent.id) + 1 : tab.rows.length
    if (parent) while (at < tab.rows.length && tab.rows[at].parents?.includes(parent.id)) ++at
    tab.rows.splice(at, 0, header)
  }
  let at = tab.rows.findIndex(r => r.id === header.id) + 1
  while (at < tab.rows.length && tab.rows[at].parents?.includes(header.id)) ++at
  const added = rows.filter(([id]) => !tab.rows.some(r => r.id === id)).map(([id,label,action='']) =>
    ({id,label,section,kind:'button',options:[],action,parents:[...header.parents,header.id],source,reason:action?'':'Not supported in VR yet'}))
  tab.rows.splice(at, 0, ...added)
}
add('right','assembly','Parts and groups','frontend/src/ui/assembly_panel.js', [
  ['assembly-add-part','+ Add Part'],['assembly-select-part','Select part'],['assembly-visible-part','Show / hide part'],['assembly-edit-part','Edit part in new tab'],['assembly-duplicate-part','Duplicate part'],['assembly-remove-part','Remove part'],['assembly-part-repr','Part representation'],
  ['assembly-connectors','Expand connectors'],['assembly-delete-connector','Delete connector'],['assembly-select-connector','Select connector'],
  ['assembly-expand-group','Expand / collapse group'],['assembly-select-group','Select group'],['assembly-visible-group','Show / hide group'],['assembly-duplicate-group','Duplicate group'],['assembly-move-group','Move group'],['assembly-rename-group','Rename group'],['assembly-ungroup','Ungroup'],['assembly-delete-group','Delete group and member parts'],['assembly-group-repr','Group representation'],['assembly-external-connectors','Expand external connectors'],
])
add('right','assembly','Mates','frontend/src/ui/assembly_panel.js', [
  ['assembly-mates-expand','Expand / collapse mates'],['assembly-mates-resolve','Resolve'],['assembly-mate-edit','Edit mate'],['assembly-mate-debug','Debug connector positions'],['assembly-mate-refresh','Refresh mate transform'],['assembly-mate-delete','Delete mate'],['assembly-mate-name','Mate name'],['assembly-mate-type','Mate type: Revolute / Prismatic / Rigid / Spherical'],['assembly-mate-value','Mate value (degrees / nm)'],['assembly-mate-limits','Use rotation limits'],['assembly-mate-min','Minimum limit'],['assembly-mate-max','Maximum limit'],['assembly-mate-rpm','RPM'],['assembly-mate-pause','Pause this motor'],['assembly-mate-cancel','Cancel mate edit'],['assembly-mate-save','Save mate'],
])
add('right','assembly','Gear relations','frontend/src/ui/assembly_panel.js', [
  ['assembly-gear-edit','Edit gear relation'],['assembly-gear-delete','Delete gear relation'],['assembly-gear-ratio','Ratio'],['assembly-gear-reverse','Reverse direction'],['assembly-gear-cancel','Cancel gear edit'],['assembly-gear-save','Save gear relation'],
])
add('right','assembly','Belt paths','frontend/src/ui/assembly_panel.js', [
  ['assembly-belt-visible','Show / hide belt path'],['assembly-belt-attach','Attach part to belt'],['assembly-belt-edit','Edit belt path'],['assembly-belt-delete','Delete belt path'],['assembly-belt-parts','Expand parts on path'],['assembly-belt-detach','Detach part from belt'],
])
for (const target of ['part', 'group']) add('right','assembly',`${target} representation`,'frontend/src/ui/assembly_panel.js',
  ['Full (CG)','Beads','Cylinders','Hull Prism','VDW (atomistic)','Ball+Stick (atomistic)','Stick (atomistic)'].map((label,i)=>[`assembly-${target}-repr-${i}`,label]))
add('left','dynamics','Job entries','frontend/src/ui/jobs_panel_base.js', [
  ['job-select','Select job'],['job-expand','Expand / collapse job tree'],['job-edit','Edit / View settings'],['job-copy','Copy job (new seed)'],['job-rename','Rename job'],['job-delete','Delete job'],['job-archive','Archive / restore job'],['job-run','Run / pause / resume / stop job'],
])
add('left', 'dynamics', 'Simulations', 'frontend/src/ui/engine_selector.js', [
  ['engine-cando','CanDo FEM'],['engine-oxdna','oxDNA'],['engine-mrdna','mrDNA'],['engine-blade','BLaDE'],['engine-snupi','SNUPI'],['engine-namd','NAMD'],
  ['vr-jobs','VR job list','jobs'],['vr-trajectory','Trajectory playback','trajectory'],
])
add('left','plates','Plates & tubes','frontend/src/ui/plate_view.js', [
  ['plates-auto-fill','Auto-fill'],['plates-orientation','8x12 / 12x8'],['plates-mode','Mode: Staple / Color / Group'],['plates-reset','Reset view'],
  ['plates-well','Select / move well'],['plates-tubes','Send to tubes / plates'],['plates-copy-all','Copy all (TSV)'],['plates-copy','Copy sequence'],['plates-warning','Hairpin / dimer structure'],
])
add('right','annotations','Annotations','frontend/src/ui/annotation_panel.js', [
  ['anno-add','+ Add'],['anno-enabled','Show annotations in the viewport'],['anno-text','Text'],['anno-icon','Icon'],['anno-calloutType','Callout type'],
  ['anno-color','Color'],['anno-transparency','Transparency'],['anno-size','Size'],['anno-manual','Manual position'],['anno-useSelection','Use selection'],['anno-remove','Remove annotation'],
])
add('left','feature-log','Feature Log / Configurations','frontend/src/ui/feature_log_panel.js', [
  ['fl-target','Target: Assembly / Part / Configurations'],['fl-loadout','Select loadout'],['fl-loadout-add','Create loadout'],['fl-loadout-rename','Rename loadout'],['fl-loadout-delete','Delete loadout'],
  ['fl-capture','+ Capture Configuration'],['fl-initial','F0 - initial'],['fl-select','Select feature'],['fl-reorder','Reorder feature'],['fl-revert','Revert to before feature'],['fl-edit','Edit feature'],['fl-save','Save edit'],['fl-delete','Delete feature'],
  ['fl-restore','Restore configuration'],['fl-animate','Animate to configuration'],['fl-overwrite','Overwrite configuration'],['fl-rename','Rename configuration'],['fl-save-name','Save name'],['fl-delete-config','Delete configuration'],['fl-pin','Pin keyframe to feature'],['fl-cancel','Cancel'],
])
add('right','visualization','View Volumes','frontend/src/scene/view_volumes.js', [])
add('right','visualization','Multi-view','frontend/src/ui/multi_view.js', [
  ['multi-view-2','Split into 2 synchronized panels'],['multi-view-3','Split into 3 synchronized panels'],['multi-view-4','Split into 4 synchronized panels'],['multi-view-repr','Panel representation'],['multi-view-color','Panel coloring'],
])
add('right','visualization','Multi-overlay','frontend/src/ui/multi_overlay.js', [
  ['multi-overlay-2','Overlay 2 representations'],['multi-overlay-3','Overlay 3 representations'],['multi-overlay-4','Overlay 4 representations'],['multi-overlay-separation','Separation'],['multi-overlay-repr','Layer representation'],['multi-overlay-color','Layer coloring'],['multi-overlay-opacity','Layer opacity'],
])
add('right','clustering','Cluster entries','frontend/src/ui/cluster_panel.js', [
  ['cluster-select','Select cluster'],['cluster-active','Activate cluster'],['cluster-rename','Rename cluster'],['cluster-save','Save name'],['cluster-delete','Delete cluster'],['cluster-expand','Expand cluster members'],
])
add('right','overhangs','Connection entries','frontend/src/ui/overhang_connections_panel.js', [
  ['oconn-mode','Overhang / Nanoparticle connection'],['oconn-a','Overhang A / Nanoparticle ssDNA handle'],['oconn-b','Overhang B / Target overhang'],['oconn-type','Connection type'],['oconn-length','Length'],['oconn-sequence','Sequence'],['oconn-connect','Connect / Add version'],['oconn-apply','Apply / Unapply'],['oconn-relax','Relax'],['oconn-driver','Driver'],['oconn-delete','Delete version'],['oconn-name','Version name'],
])
tabs.push({side:'right',key:'tools',label:'Tools',rows:[
  ['tool-inspect','Inspect','tool:inspect'],['tool-move','Move / Rotate','tool:move_rotate'],['tool-extrude','Extrude','tool:extrude'],
  ['tool-twist','Twist','tool:twist'],['tool-bend','Bend','tool:bend'],
].map(([id,label,action])=>({id,label,action,section:'Tools',kind:'button',options:[],source:'frontend/scripts/generate-vr-sidebar-catalog.mjs',reason:''}))})
add('right','tools','Selection','frontend/scripts/generate-vr-sidebar-catalog.mjs', [
  ['select:default','Auto / Drill','select:default'],['select:cluster','Cluster','select:cluster'],
  ['select:strand','Strand','select:strand'],['select:domain','Domain','select:domain'],
  ['select:end','End','select:end'],['select:xover','Crossover','select:xover'],
  ['select:base','Base','select:base'],
])
tabs.push({side:'left',key:'vr',label:'VR',rows:[
  ['vr-desktop','View desktop','desktop'],
  ['vr-head-light','Head-following lighting: Off','vr:head-light'],
  ['qr-cube-calibrate','Calibrate cube','qr:cube'],
  ['qr-cube-status','Keep cube fixed; scan all five faces','qr:cube-status'],
  ['vr-exit','Exit VR','vr:exit'],
].map(([id,label,action])=>({id,label,action,section:'VR',kind:'button',options:[],source:'frontend/scripts/generate-vr-sidebar-catalog.mjs',reason:''}))})
tabs.push({side:'left',key:'share',label:'Share',rows:[
  ['share-avatar','Show VR model','share:avatar'],
  ['qr-calibrate','Calibrate QR code','qr:calibrate'],
  ['qr-status','QR not calibrated','qr:status'],
  ['share-desktop','Start sharing and manage links on desktop',''],
  ['share-source','Perspective source: desktop camera',''],
  ['share-active','Presentation active','share:status'],
  ['share-pause','Pause perspective','share:pause'],
  ['share-resume','Resume perspective','share:resume'],
  ['share-end','End presentation (all links)','share:end'],
].map(([id,label,action])=>({id,label,action,section:'Share',kind:'button',options:[],source:'frontend/src/scene/vr_share.js',reason:action?'':'Desktop only'}))})
// Select options are separate discoverable disabled choices, preserving all values.
for (const tab of tabs) tab.rows = tab.rows.flatMap(row => [row, ...row.options.map(o => ({...row,id:`${row.id}:option:${o.value}`,label:`${row.label}: ${o.label}`,kind:'option',options:[],action:'',reason:'Not supported in VR yet'}))])
for (const tab of tabs) {
  const seen = new Set()
  for (const row of tab.rows) {
    if (seen.has(row.id)) throw Error(`Duplicate row: ${row.id}`)
    for (const parent of row.parents || []) if (!seen.has(parent)) throw Error(`Missing preceding card ${parent}: ${row.id}`)
    seen.add(row.id)
  }
}
const sources = [...new Set(['frontend/src/scene/coloring_modes.js', 'frontend/src/scene/vr_representations.js', 'frontend/index.html', 'frontend/src/ui/right_sidebar_tabs.js', 'frontend/scripts/vr-sidebar-sections.mjs', 'frontend/src/ui/simulation_card_order.js', ...tabs.flatMap(t=>t.rows.map(r=>r.source))])].sort()
const sourceHashes = Object.fromEntries(sources.map(file=>[file,createHash('sha256').update(fs.readFileSync(path.join(root,file))).digest('hex')]))
const coloringMasks = VR_REPRESENTATIONS.map(rep => ['strand','base','cluster','cpk'].reduce((mask,mode,i) => mask | (COLORING_SUPPORT[rep]?.has(mode) ? 1<<i : 0), 0))
const report = JSON.stringify({ version:2, sourceHashes, coloringMasks, tabs }, null, 2) + '\n'
const q = s => JSON.stringify(ascii(s))
let header = '// Generated by frontend/scripts/generate-vr-sidebar-catalog.mjs. Do not edit.\n#pragma once\n#include <vector>\n#include <string>\nnamespace nadoc_vr {\nstruct SidebarRow { std::string id, label, section, action; std::vector<std::string> parents; };\nstruct SidebarTab { int hand; std::string key, label; std::vector<SidebarRow> rows; };\ninline const std::vector<SidebarTab> kSidebarTabs = {\n'
for (const tab of tabs) header += `  {${tab.side==='left'?0:1}, ${q(tab.key)}, ${q(tab.label)}, {\n` + tab.rows.map(r=>`    {${q(r.id)}, ${q(r.label)}, ${q(r.section)}, ${q(r.action)}, {${(r.parents || []).map(q).join(", ")}}},\n`).join('') + '  }},\n'
header += `};\ninline const std::vector<unsigned> kSidebarColoringMasks = {${coloringMasks.join(',')}};\n}\n`
for (const [file, text] of [['native/vr_viewer/sidebar_catalog.json', report], ['native/vr_viewer/src/sidebar_catalog.hpp',header]]) {
  const target = path.join(root,file)
  if (process.argv.includes('--check')) { if(fs.readFileSync(target,'utf8')!==text) throw Error(`Stale sidebar mapping: ${file}`) }
  else fs.writeFileSync(target,text)
}
console.log(tabs.map(t=>`${t.side}/${t.key}: ${t.rows.length}`).join('\n'))
dom.window.close()
