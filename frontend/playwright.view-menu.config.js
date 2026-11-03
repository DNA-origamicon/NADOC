import { defineConfig } from '@playwright/test'
import isolated from './playwright.vr-history.config.js'
export default defineConfig({...isolated,testMatch:'vr_view_tools_capture.spec.js'})
