import test from 'node:test'
import assert from 'node:assert/strict'
import { imageUrl } from './src/utils/imageUrl.js'
globalThis.window = { location: { origin: 'https://admin.gingtto.store' } }

test('known product image uses bounded thumbnail size', () => {
  assert.equal(imageUrl('https://img.smawell.shop/uploads/a.jpg', 160), '/uploads/a.jpg?w=160')
  assert.ok(imageUrl('https://img.smawell.shop/uploads/a.jpg', 161).endsWith('?w=320'))
  assert.ok(imageUrl('https://img.smawell.shop/uploads/a.jpg', 5000).endsWith('?w=1600'))
})
test('external, signed, inline and non-image URLs remain unchanged', () => {
  for (const source of ['https://other.example/uploads/a.jpg', 'https://img.smawell.shop.evil.test/uploads/a.jpg', 'https://img.smawell.shop/uploads/a.jpg?signature=test', 'https://img.smawell.shop/uploads/a.pdf', 'https://img.smawell.shop/uploads/a.gif', 'data:image/png;base64,AAAA', 'blob:https://example.test/id', '']) {
    assert.equal(imageUrl(source, 160), source)
  }
})
