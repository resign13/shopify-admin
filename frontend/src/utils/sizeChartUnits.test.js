import test from 'node:test';
import assert from 'node:assert/strict';
import { convertMeasurement, changeChartUnit, previewChartInUnit } from './sizeChartUnits.js';

test('standard formula, half-up rounding, blanks and zero', () => {
  assert.equal(convertMeasurement('1', 'in', 'cm'), '2.54');
  assert.equal(convertMeasurement('2.54', 'cm', 'in'), '1.00');
  assert.equal(convertMeasurement('100.5', 'cm', 'in'), '39.57');
  assert.equal(convertMeasurement('0.25', 'in', 'cm'), '0.64');
  assert.equal(convertMeasurement('0', 'in', 'cm'), '0.00');
  assert.equal(convertMeasurement('', 'in', 'cm'), null);
  assert.equal(convertMeasurement(null, 'cm', 'in'), null);
  for (const v of ['-1', 'bad', '1.234', 'Infinity', '10000000000']) {
    assert.throws(() => convertMeasurement(v, 'cm', 'in'));
  }
  assert.throws(() => convertMeasurement('9999999999.99', 'in', 'cm'));
});

const fixture = () => ({unit:'cm',dimensions:[{id:'hip',unit:'cm'},{id:'waist',unit:'cm'}],values:{hip:{S:'1.00',L:null},waist:{S:'0',L:'2.54'}}});
test('whole style conversion including hidden dimensions; toggles do not accumulate rounding', () => {
  const c = fixture(), anchors = new Map();
  changeChartUnit(c, 'in', anchors);
  assert.equal(c.unit, 'in');
  assert.ok(c.dimensions.every(d => d.unit === 'in'));
  assert.deepEqual(c.values, {hip:{S:'0.39',L:null},waist:{S:'0.00',L:'1.00'}});
  changeChartUnit(c, 'cm', anchors);
  assert.equal(c.values.hip.S, '1.00');
  changeChartUnit(c, 'in', anchors);
  c.values.hip.S = '2';
  changeChartUnit(c, 'cm', anchors);
  assert.equal(c.values.hip.S, '5.08');
});
test('invalid cell leaves whole style and conversion cache unchanged', () => {
  const c = fixture(), anchors = new Map();
  c.values.waist.L = 'bad';
  const before = structuredClone(c);
  assert.throws(() => changeChartUnit(c, 'in', anchors));
  assert.deepEqual(c, before);
  assert.equal(anchors.size, 0);
});

test('readonly preview converts a detached chart and never rounds the saved source', () => {
  const chart=fixture(), original=structuredClone(chart);
  chart.values.hip.S='100.50';original.values.hip.S='100.50';
  const inches=previewChartInUnit(chart,'in');
  assert.equal(inches.values.hip.S,'39.57');
  assert.equal(inches.values.waist.S,'0.00');
  assert.equal(inches.values.hip.L,null);
  assert.ok(inches.dimensions.every(d=>d.unit==='in'));
  assert.deepEqual(chart,original);
  assert.equal(previewChartInUnit(chart,'cm').values.hip.S,'100.50');
  inches.values.hip.S='99';inches.dimensions[0].unit='cm';
  assert.deepEqual(chart,original);
});
