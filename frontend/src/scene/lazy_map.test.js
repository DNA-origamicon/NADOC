import { expect, it, vi } from 'vitest'
import { LazyMap } from './lazy_map.js'

it('defers construction and preserves Map reads, iteration, mutation, and size', () => {
  const fill = vi.fn(map => { map.set('a', 1); map.set('b', 2) })
  const map = new LazyMap(fill)
  expect(fill).not.toHaveBeenCalled()
  expect(map instanceof Map).toBe(true)
  expect(map.get('a')).toBe(1)
  expect(map.has('b')).toBe(true)
  expect(map.size).toBe(2)
  expect([...map]).toEqual([['a', 1], ['b', 2]])
  expect([...map.keys()]).toEqual(['a', 'b'])
  expect([...map.values()]).toEqual([1, 2])
  map.set('c', 3); map.delete('b')
  const values = []; map.forEach((value, key) => values.push([key, value]))
  expect(values).toEqual([['a', 1], ['c', 3]])
  expect(fill).toHaveBeenCalledOnce()
})

it('clear can discard unneeded deferred entries without constructing them', () => {
  const fill = vi.fn(map => map.set('a', 1)), map = new LazyMap(fill)
  map.clear(); map.set('b', 2)
  expect([...map]).toEqual([['b', 2]])
  expect(fill).not.toHaveBeenCalled()
})
