import assert from 'node:assert/strict';
import { test } from 'node:test';
import { customerProfile, applyCustomerProfile } from './customerTemplates.js';

test('presets retain customer fields, notes and attachment order but exclude order state', () => {
  const source = { userId: 2, contactName: 'Alice', address: 'Somewhere', note: 'Pack separately',
    labelImageUrls: ['/uploads/a.jpg', '/uploads/b.jpg'], labelPdfUrl: '/uploads/a.pdf',
    items: [{ quantity: 99 }], shippingFee: 99, status: 'completed', version: 'old', requestId: 'old' };
  const profile = customerProfile(source);
  assert.equal(profile.note, source.note);
  assert.equal(profile.labelPdfUrl, source.labelPdfUrl);
  assert.deepEqual(profile.labelImageUrls, source.labelImageUrls);
  for (const field of ['items', 'shippingFee', 'status', 'version', 'requestId'])
    assert.equal(field in profile, false);
  profile.labelImageUrls.pop();
  assert.equal(source.labelImageUrls.length, 2);
});

test('one-click preset fill replaces customer values, keeps order goods and clones attachments', () => {
  const items = [{ productId: 1, quantity: 3, unitPrice: 20 }];
  const order = { userId: 1, note: 'Old', apartment: 'Old', items, shippingFee: 15,
    status: 'pending_payment', requestId: 'request', labelImageUrls: ['/uploads/old.jpg'] };
  const preset = { userId: 2, contactName: 'New', note: '', labelImageUrls: ['/uploads/new.jpg'] };
  applyCustomerProfile(order, preset);
  assert.equal(order.userId, 2);
  assert.equal(order.note, '');
  assert.equal(order.apartment, '');
  assert.equal(order.items, items);
  assert.equal(order.shippingFee, 15);
  assert.equal(order.status, 'pending_payment');
  assert.equal(order.requestId, 'request');
  order.labelImageUrls.push('/uploads/order-only.jpg');
  assert.deepEqual(preset.labelImageUrls, ['/uploads/new.jpg']);
  assert.equal(order.labelPdfUrl, '');
});
