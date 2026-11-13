import { defineConfig } from '@playwright/test'
import isolated from './playwright.multi-overlay.config.js'
export default defineConfig({...isolated,testMatch:['md_slab_alignment.spec.js'],outputDir:'../.development-artifacts/slab-audit/app'})
