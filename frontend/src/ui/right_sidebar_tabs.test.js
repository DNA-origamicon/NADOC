import { beforeEach, describe, expect, it } from 'vitest'
import { JSDOM } from 'jsdom'
import { initRightSidebarTabs } from './right_sidebar_tabs.js'

describe('right sidebar tabs', () => {
  beforeEach(() => {
    const dom = new JSDOM(`
      <div id="right-tab-strip">
        <button id="right-tab-toggle"></button>
        <button class="right-tab-btn" data-tab="properties"></button>
        <button class="right-tab-btn" data-tab="visualization"></button>
        <button class="right-tab-btn" data-tab="clustering"></button>
        <button class="right-tab-btn" data-tab="overhangs"></button>
      </div>
      <div id="right-panel">
        <div id="right-tab-content-properties"></div>
        <div id="right-tab-content-visualization"></div>
        <div id="right-tab-content-clustering"></div>
        <div id="right-tab-content-overhangs"></div>
        <div class="panel-section" id="properties-section"></div>
        <div class="panel-section" id="extrude-panel"></div>
        <div class="panel-section" id="strand-hist-section"></div>
        <div class="panel-section" id="groups-panel"></div>
        <div class="panel-section" id="repr-options-section"></div>
        <div class="panel-section" id="cluster-panel"></div>
        <div class="panel-section" id="joints-panel"></div>
        <div class="panel-section" id="overhang-panel"></div>
        <div class="panel-section" id="overhang-connections-section"></div>
        <div class="panel-section" id="strand-anim-panel"></div>
        <button id="reset-btn"></button><button id="unhide-all-btn"></button>
      </div>
      <button id="menu-view-detail-full" class="is-checked"></button>
    `)
    globalThis.document = dom.window.document
    globalThis.MutationObserver = dom.window.MutationObserver
  })

  it('groups the requested sections and switches panes', () => {
    const storage = { getItem: () => null, setItem: () => {} }
    const tabs = initRightSidebarTabs({ document, storage })
    expect(document.getElementById('measurements-section')).toBeNull()
    expect(document.querySelector('#right-tab-content-properties #extrude-panel')).toBeTruthy()
    expect(document.querySelector('#right-tab-content-clustering #joints-panel')).toBeTruthy()
    expect(document.querySelector('#right-tab-content-overhangs #strand-anim-panel')).toBeTruthy()
    expect(document.querySelector('#right-tab-content-visualization #right-view-actions #reset-btn')).toBeTruthy()
    expect(document.querySelector('#right-tab-content-visualization #right-multi-view-body')).toBeTruthy()
    expect(document.querySelector('#right-tab-content-visualization #right-multi-overlay-body')).toBeTruthy()
    tabs.select('visualization')
    expect(document.getElementById('right-tab-content-properties').hidden).toBe(true)
    expect(document.getElementById('right-tab-content-visualization').hidden).toBe(false)
    tabs.select('visualization')
    expect(document.getElementById('right-panel').classList.contains('hidden')).toBe(true)
    document.getElementById('right-tab-toggle').click()
    expect(document.getElementById('right-panel').classList.contains('hidden')).toBe(false)
  })

  it('opens a requested tab without collapsing it when it is already active', () => {
    const tabs = initRightSidebarTabs({ document, storage: null })
    tabs.open('properties')
    expect(tabs.getActiveTab()).toBe('properties')
    expect(tabs.isCollapsed()).toBe(false)
    tabs.open('properties')
    expect(tabs.isCollapsed()).toBe(false)
  })

  it('proxies representation buttons to the existing controls', () => {
    let clicks = 0
    document.getElementById('menu-view-detail-full').addEventListener('click', () => clicks++)
    initRightSidebarTabs({ document, storage: null })
    const full = [...document.querySelectorAll('.right-repr-btn')].find(b => b.textContent === 'Full')
    expect(full.classList.contains('active')).toBe(true)
    full.click()
    expect(clicks).toBe(1)
  })
})
