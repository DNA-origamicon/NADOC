import { enumerateCylinders } from './yggdnasil_cylinders.js'
self.onmessage = event => {
  try { self.postMessage({ atlas: enumerateCylinders(event.data) }) }
  catch (error) { self.postMessage({ error: error.message }) }
}
