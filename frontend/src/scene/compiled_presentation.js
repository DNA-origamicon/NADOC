import { offlinePresentation } from './offline_presentation.js'

export function presentationAnimation(animation, fps) {
  return { ...animation, loop: false, keyframes: animation.keyframes.map(kf => ({ ...kf,
    transition_duration_s: Math.max(0, Number(kf.transition_duration_s) || 0),
    hold_duration_s: Math.max(1 / fps, Number(kf.hold_duration_s) || 0),
  })) }
}

export function compilationEstimate(done, total, elapsedMs) {
  return done > 0 && total >= done && elapsedMs > 0 ? Math.ceil((total - done) * elapsedMs / done / 1000) : null
}

export function presentationHTML(title, clips, inspection = null) {
  const escape = text => String(text).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  const data = JSON.stringify({ version: 1, title, clips, inspection }).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029')
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; media-src blob: data:; connect-src 'none'">
<title>${escape(title)}</title><style>
*{box-sizing:border-box}body{margin:0;background:#10141c;color:#eee;font:16px system-ui}main{height:100vh;display:flex;flex-direction:column}#stage{flex:1;min-height:0;position:relative;background:#000;cursor:pointer}video,#poster{position:absolute;width:100%;height:100%;object-fit:contain}footer{padding:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}button,select{font:inherit;padding:7px;background:#263448;color:white;border:1px solid #667;border-radius:5px}#status{margin-left:auto}small{width:100%;color:#bfc8d6} [hidden]{display:none!important}
</style><main><div id="stage"><img id="poster" alt="Keyframe"></div><footer>
<button id="back">Back</button><button id="replay">Replay</button><button id="pause">Play / pause</button><button id="next">Next</button><select id="jump" aria-label="Keyframe"></select><button id="fullscreen">Fullscreen</button><span id="status" role="status"></span>
<small>Click / Space / →: next · ←: previous endpoint · R: replay · P: pause/resume · Esc: pause and leave fullscreen. Videos play once and hold. This file works offline.</small>
</footer></main><script id="nadoc-presentation-data" type="application/json">${data}</script><script>(${offlinePresentation.toString()})(JSON.parse(document.getElementById("nadoc-presentation-data").textContent).clips);</script></html>`
}
