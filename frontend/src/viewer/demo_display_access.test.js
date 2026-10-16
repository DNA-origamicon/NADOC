import { it, expect, vi, afterEach } from 'vitest'
import { mountDemoDisplayAccess } from './demo_display_access.js'
afterEach(()=>{document.body.replaceChildren();sessionStorage.clear()})
function mount(){document.body.innerHTML='<input id="guest-name" value="Demo"><p id="join-error"></p>';return mountDemoDisplayAccess({base:'/meeting/one',onExit:vi.fn()})}
it('keeps ordinary QR entry passwordless until explicit setup and remembers only this tab',()=>{
 let ui=mount();expect(document.querySelector('input[type=password]')).toBeNull()
 document.querySelector('[data-demo-display-setup]').click();document.querySelector('#demo-display-password').value='display-secret'
 expect(ui.credentials()).toEqual({role:'display',password:'display-secret'});ui.accept('Demo screen');ui.dispose()
 ui=mount();expect(ui.remembered).toBe(true);expect(ui.credentials().password).toBe('display-secret')
 expect(document.querySelector('#guest-name').value).toBe('Demo screen')
 document.querySelector('[data-demo-display-exit]').click();expect(sessionStorage.length).toBe(0);ui.dispose()
})
