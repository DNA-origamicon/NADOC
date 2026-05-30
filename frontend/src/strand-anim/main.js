/**
 * Entry point for the standalone "Strand Animations Testing" page.
 */

import { initStrandAnimApp } from './app.js'

const canvas = document.getElementById('strand-canvas')
const panelRoot = document.getElementById('strand-panel-body')

const app = initStrandAnimApp(canvas, panelRoot)

// Expose for quick console poking during development.
window.strandAnim = app
