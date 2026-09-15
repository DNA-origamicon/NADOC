import {defineConfig} from '@playwright/test'
import base from './playwright.config.js'
export default defineConfig({...base,webServer:base.webServer.map((server,i)=>i?server:{...server,command:server.command+' --lifespan off'})})
