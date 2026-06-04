/**
 * Shared test double for the app's Zustand-style store.
 *
 * Every factory-extraction test (`initX({ store, ... })`) needs the same minimal
 * store mock: getState / setState-that-notifies / subscribe / a test-only _emit.
 * Before this helper each test hand-rolled an identical ~15-line copy; they only
 * ever differed in the *initial state fields*, which is exactly the one argument.
 *
 * NOT a `.test.js` file, so vitest's `src/**​/*.test.js` glob ignores it; it is
 * imported by the real test files. Behavioural contract matches the real store
 * closely enough for wiring tests: subscribers fire in registration order with
 * `(newState, prevState)`, and a state change is a shallow `{ ...state, ...patch }`.
 *
 * @param {object} [initialState] — seed fields the factory reads via getState()
 * @returns {{
 *   getState: () => object,
 *   setState: (patch: object) => void,
 *   subscribe: (cb: (n: object, p: object) => void) => (() => void),
 *   _emit: (patch: object) => void,
 * }}
 */
export function createMockStore(initialState = {}) {
  let state = { ...initialState }
  const subs = []
  const notify = (prev) => { for (const cb of subs) cb(state, prev) }
  const apply = (patch) => { const prev = state; state = { ...state, ...patch }; notify(prev) }
  return {
    getState: () => state,
    setState: apply,
    subscribe: (cb) => {
      subs.push(cb)
      return () => { const i = subs.indexOf(cb); if (i >= 0) subs.splice(i, 1) }
    },
    // Test-only alias for setState — kept so existing specs that called `_emit`
    // to mean "change state and fire subscribers" read the same.
    _emit: apply,
  }
}
