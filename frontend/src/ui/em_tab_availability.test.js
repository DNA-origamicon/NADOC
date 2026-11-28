// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { initEMTabAvailability } from './em_tab_availability.js'
import { createMockStore } from '../test-helpers/mock_store.js'

let feature
const particle = { id: 'np', kind: 'quantum_dot', visible: false }
const part = nanoparticles => ({ id: 'part', nanoparticles })
const inline = nanoparticles => ({ id: 'instance', source: { type: 'inline', design: part(nanoparticles) } })
afterEach(() => { feature?.dispose(); document.body.innerHTML = ''; localStorage.clear() })
function setup(state, api = {}) {
 document.body.innerHTML = '<div id="right-tab-strip"><button data-tab="em" hidden>EM Analysis</button></div>'
 const store = createMockStore(state), rightSidebar = { setEMAvailable: vi.fn(value => { document.querySelector('[data-tab="em"]').hidden = !value }) }
 feature = initEMTabAvailability({store, rightSidebar, api})
 return {store, rightSidebar}
}
it('points out the first particle addition, dismisses with OK, and hides after the last removal', () => {
 const {store,rightSidebar} = setup({currentDesign:part([])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(false)
 store.setState({currentDesign:part([particle])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(true)
 const popup = document.querySelector('.em-tab-intro')
 expect(popup.getAttribute('role')).toBe('dialog')
 expect(popup.textContent).toContain('EM Analysis')
 popup.querySelector('button').click()
 expect(document.querySelector('.em-tab-intro')).toBeNull()
 store.setState({currentDesign:part([])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(false)
 store.setState({currentDesign:part([particle])})
 expect(document.querySelector('.em-tab-intro')).toBeNull()
})
it('shows the tab without an addition popup when opening a populated document', () => {
 const {store,rightSidebar} = setup({currentDesign:part([particle])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(true)
 expect(document.querySelector('.em-tab-intro')).toBeNull()
 store.setState({currentDesign:{id:'other',nanoparticles:[particle]}})
 expect(document.querySelector('.em-tab-intro')).toBeNull()
})
it('removes an undismissed callout on removal or document switch', () => {
 const {store} = setup({currentDesign:part([])})
 store.setState({currentDesign:part([particle])})
 store.setState({currentDesign:part([])})
 expect(document.querySelector('.em-tab-intro')).toBeNull()
 store.setState({currentDesign:part([particle])})
 expect(document.querySelector('.em-tab-intro')).not.toBeNull()
 store.setState({currentDesign:{id:'other',nanoparticles:[]}})
 expect(document.querySelector('.em-tab-intro')).toBeNull()
})
it('keeps availability while any assembly instance has particles', () => {
 const assembly = instances => ({id:'assembly',instances})
 const {store,rightSidebar} = setup({assemblyActive:true,currentAssembly:assembly([])})
 store.setState({currentAssembly:assembly([inline([particle]), {...inline([particle]),id:'second'}])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(true)
 expect(document.querySelector('.em-tab-intro')).not.toBeNull()
 store.setState({currentAssembly:assembly([inline([particle])])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(true)
 store.setState({currentAssembly:assembly([])})
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(false)
 expect(document.querySelector('.em-tab-intro')).toBeNull()
})
it('waits for file sources and ignores stale assembly reads after a document switch', async () => {
 let resolve
 const api={getInstanceDesign:vi.fn(()=>new Promise(r=>{resolve=r}))}
 const {store,rightSidebar}=setup({assemblyActive:true,currentAssembly:{id:'assembly',instances:[{id:'file',source:{type:'file'}}]}},api)
 resolve({design:part([particle])})
 await vi.waitFor(()=>expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(true))
 expect(document.querySelector('.em-tab-intro')).toBeNull()
 store.setState({currentAssembly:{id:'assembly',instances:[{id:'file',source:{type:'file',revision:'next'}}]}})
 store.setState({assemblyActive:false,currentDesign:part([])})
 resolve({design:part([particle])})
 await Promise.resolve(); await Promise.resolve()
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(false)
})
it('does not infer particle removal from a failed source read, and removes its listeners on disposal', async () => {
 const {store,rightSidebar}=setup({assemblyActive:true,currentAssembly:{id:'assembly',instances:[inline([particle])]}},{getInstanceDesign:vi.fn().mockRejectedValue(new Error('offline'))})
 store.setState({currentAssembly:{id:'assembly',instances:[{id:'file',source:{type:'file'}}]}})
 await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
 expect(rightSidebar.setEMAvailable).toHaveBeenLastCalledWith(true)
 feature.dispose(); rightSidebar.setEMAvailable.mockClear()
 store.setState({currentAssembly:{id:'assembly',instances:[]}})
 expect(rightSidebar.setEMAvailable).not.toHaveBeenCalled()
})
