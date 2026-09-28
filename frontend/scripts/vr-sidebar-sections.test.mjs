import { test } from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { sidebarSections } from './vr-sidebar-sections.mjs'

test('desktop nested cards keep distinct identities and ancestor membership', () => {
  const dom = new JSDOM(`<main><section class="panel-section" id="engine"><h2>Engine</h2>
    <div class="ox-card"><div class="ox-card__header" id="one"><span class="ox-card__title">Advanced</span></div>
      <input id="a"><details id="settings"><summary>Settings</summary><input id="b"></details></div>
    <div class="ox-card"><div class="ox-card__header" id="two"><span class="ox-card__title">Advanced</span></div><input id="c"></div>
    </section><input id="outside"></main>`)
  const doc=dom.window.document
  const {headings,parents}=sidebarSections(doc.querySelector('main'),'simulation',s=>s.trim())
  assert.equal(headings.size,4)
  assert.deepEqual(parents(doc.getElementById('b')),['section:simulation:engine','section:simulation:one','section:simulation:settings'])
  assert.deepEqual(parents(doc.getElementById('c')),['section:simulation:engine','section:simulation:two'])
  assert.deepEqual(parents(doc.getElementById('outside')),[])
  assert.deepEqual(headings.get(doc.querySelector('summary')).parents,['section:simulation:engine','section:simulation:one'])
  assert.equal(headings.get(doc.getElementById('one')).label,'Advanced')
  assert.notEqual(headings.get(doc.getElementById('one')).id,headings.get(doc.getElementById('two')).id)
  dom.window.close()
})
