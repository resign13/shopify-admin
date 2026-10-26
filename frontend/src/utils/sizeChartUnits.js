// Integer hundredths avoid binary floating-point rounding at half-cent boundaries.
export function convertMeasurement(value, source, target) {
  if (!['cm', 'in'].includes(source) || !['cm', 'in'].includes(target)) throw new Error('单位须为 cm 或 in');
  if (value == null || value === '') return null;
  const text = String(value).trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) throw new Error('请先将测量值填写为非负数，最多两位小数');
  const [whole, fraction = ''] = text.split('.');
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  const limit = 999999999999n;
  if (cents > limit) throw new Error('测量值超出允许范围');
  const numerator = source === target ? cents : cents * (source === 'in' ? 254n : 100n);
  const denominator = source === target ? 1n : source === 'in' ? 100n : 254n;
  const result = (numerator * 2n + denominator) / (2n * denominator);
  if (result > limit) throw new Error('换算后的测量值超出允许范围');
  return `${result / 100n}.${String(result % 100n).padStart(2, '0')}`;
}

export function changeChartUnit(chart, target, anchors = new Map()) {
  const values = {}, nextAnchors = new Map();
  for (const dimension of chart.dimensions) {
    values[dimension.id] = {};
    for (const [size, value] of Object.entries(chart.values[dimension.id])) {
      const key = JSON.stringify([dimension.id, size]);
      const previous = anchors.get(key);
      // Preserve the original precision while toggling, unless this cell was edited.
      const anchor = previous && previous.display === value && previous.unit === dimension.unit
        ? previous : { value, source: dimension.unit };
      const converted = convertMeasurement(anchor.value, anchor.source, target);
      values[dimension.id][size] = converted;
      nextAnchors.set(key, { ...anchor, display: converted, unit: target });
    }
  }
  // Validation/conversion completes before changing any field.
  chart.values = values;
  chart.dimensions.forEach(d => { d.unit = target; });
  chart.unit = target;
  anchors.clear();
  nextAnchors.forEach((v, k) => anchors.set(k, v));
}

export function previewChartInUnit(chart, target) {
  // Always convert from the saved source, never from an already rounded preview.
  const preview = { ...chart, dimensions: chart.dimensions.map(d => ({ ...d })) };
  changeChartUnit(preview, target);
  return preview;
}
