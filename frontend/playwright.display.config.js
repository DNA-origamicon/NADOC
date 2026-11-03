import {defineConfig} from '@playwright/test'
import isolated from './playwright.vr-sweep.config.js'
export default defineConfig({...isolated,testMatch:['demo_display.spec.js'],timeout:180000,globalTimeout:240000})
