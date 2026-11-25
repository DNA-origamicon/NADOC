const { test } = require('node:test')
const assert = require('node:assert/strict')
const { parseOptions, localURL, launchURL } = require('./runtime.cjs')

test('validation cannot silently use the normal workspace/profile', () => {
  assert.throws(() => parseOptions(['--validation']), /isolated/)
  assert.throws(() => parseOptions(['--workspace', 'relative']), /absolute/)
  assert.throws(() => parseOptions(['--open', '../user.nadoc']), /relative/)
  assert.deepEqual(parseOptions(['--validation', '--workspace', '/tmp/w', '--profile', '/tmp/p']),
    { validation: true, workspace: '/tmp/w', profile: '/tmp/p' })
})
test('capability only travels to our exact origin', () => {
  const origin = 'http://127.0.0.1:12345'
  assert.equal(localURL(`${origin}/api/design`, origin), true)
  for (const url of ['http://127.0.0.1:12346/', 'https://example.com', 'http://user@127.0.0.1:12345/']) assert.equal(localURL(url, origin), false)
})
test('launch requests preserve the ordinary file-open path and assembly mode', () => {
  const url = new URL(launchURL('http://127.0.0.1:12345', 'large scene.nass'))
  assert.equal(url.searchParams.get('open'), 'large scene.nass')
  assert.equal(url.searchParams.get('open-type'), 'assembly')
})

test('desktop backbone acceleration has an explicit standard-sphere fallback', () => {
  const origin = 'http://127.0.0.1:12345'
  assert.equal(new URL(launchURL(origin)).searchParams.get('fast-backbone'), '1')
  assert.equal(new URL(launchURL(origin, null, parseOptions(['--standard-spheres']))).searchParams.get('fast-backbone'), '0')
})
