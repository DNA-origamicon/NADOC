import {broadcastFingerprint} from '../viewer/broadcast_fingerprint.js'
/** Content-aware invalidation also covers instancing and prepared assembly textures.
 * Ignore field opacity: crossfades composite already-integrated endpoint images. */
export function volumeViewKey(scene,camera,size,palette,renderer){
 return broadcastFingerprint({scene,pane:[size.x,size.y,camera.matrixWorld.toArray(),camera.projectionMatrix.toArray(),camera.layers.mask,palette.version,
  renderer.clippingPlanes?.map(p=>[...p.normal.toArray(),p.constant]),renderer.localClippingEnabled]}, {ignoreEM:true})
}
