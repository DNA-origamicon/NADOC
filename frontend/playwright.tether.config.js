import base from './playwright.smoke.config.js'
// Desktop GPU benchmark: isolated smoke servers/cleanup, 120 rendered JJ updates.
// WSL may need GALLIUM_DRIVER=d3d12; software fallback is not a GPU result.
process.env.NADOC_JJ_RENDER_FRAMES='1'
export default {...base,grep:/JJ_Hinge tethered collision toggle/,use:{...base.use,headless:false,launchOptions:{args:['--enable-gpu','--ignore-gpu-blocklist','--use-angle=gl']}}}
