/** A Map whose contents are built on first use. Static display can retain the
 * authoritative entries without paying for every editing/simulation index. */
export class LazyMap extends Map {
  constructor(populate) { super(); this._populate = populate }
  _ensure() {
    const populate = this._populate
    if (!populate) return
    this._populate = null
    populate(this)
  }
  get size() { this._ensure(); return super.size }
  get(key) { this._ensure(); return super.get(key) }
  has(key) { this._ensure(); return super.has(key) }
  set(key, value) { this._ensure(); return super.set(key, value) }
  delete(key) { this._ensure(); return super.delete(key) }
  clear() { this._populate = null; return super.clear() }
  entries() { this._ensure(); return super.entries() }
  keys() { this._ensure(); return super.keys() }
  values() { this._ensure(); return super.values() }
  forEach(callback, thisArg) { this._ensure(); return super.forEach(callback, thisArg) }
  [Symbol.iterator]() { return this.entries() }
}
