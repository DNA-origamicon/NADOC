import config from './playwright.config.js'
export default {...config,webServer:config.webServer.map((s,i)=>i===0?{...s,command:s.command+' --lifespan off'}:s)}
