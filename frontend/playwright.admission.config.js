import {defineConfig} from '@playwright/test'
import isolated from './playwright.vr-sweep.config.js'
export default defineConfig({...isolated,testMatch:['guest_admission.spec.js'],timeout:420000,globalTimeout:480000})
