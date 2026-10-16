import {defineConfig} from '@playwright/test'
import isolated from './playwright.vr-sweep.config.js'
export default defineConfig({...isolated,testMatch:['vr_share.spec.js','sharing_setup.spec.js'],timeout:420000,globalTimeout:600000})
