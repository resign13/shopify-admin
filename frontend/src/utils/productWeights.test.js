import test from "node:test";
import assert from "node:assert/strict";
import { applyWeight, weightTargets, realWeightSizes, validWeight, formatWeightKg, orderWeightText, orderWeightPreviewItems } from "./productWeights.js";

const fixture = () => [{ localId: "a", sizePrices: [{ sizeCode: "30/M", stock: -5, price: 17, weightGrams: 100 }, { sizeCode: "Tall XL", stock: 4, price: 19, weightGrams: null }] },
  { localId: "b", sizePrices: [{ sizeCode: "30/M", stock: 8, price: 18, weightGrams: null }] }];
test("real-size union and selected-size apply never create sizes or change money/stock", () => {
  const values = fixture();
  assert.deepEqual(realWeightSizes(values), ["30/M", "Tall XL"]);
  assert.equal(weightTargets(values, "Tall XL").length, 1);
  assert.equal(applyWeight(values, "30/M", 350), 2);
  assert.equal(values[0].sizePrices[0].weightGrams, 350);
  assert.equal(values[1].sizePrices[0].weightGrams, 350);
  assert.equal(values[0].sizePrices[1].weightGrams, null);
  assert.equal(values[0].sizePrices[0].stock, -5);
  assert.equal(values[0].sizePrices[0].price, 17);
  assert.equal(values[1].sizePrices.length, 1);
});
test("apply all, absent size and invalid numbers", () => {
  const values = fixture();
  assert.equal(applyWeight(values, "", 380), 3);
  assert.equal(applyWeight(values, "NONEXISTENT", 380), 0);
  for (const value of [0, -1, 1.5, null, undefined, "350", true, Infinity, 2147483648]) {
    assert.equal(validWeight(value), false);
    assert.throws(() => applyWeight(values, "", value));
  }
  assert.equal(validWeight(2147483647), true);
});
test("exact kg formatting, missing is not zero", () => {
  assert.equal(formatWeightKg("5400"), "5.400");
  assert.equal(formatWeightKg("9007199254740993"), "9,007,199,254,740.993");
  assert.equal(formatWeightKg("1"), "0.001");
  assert.equal(formatWeightKg(null), "未设置");
  assert.equal(orderWeightText({ totalWeightGrams: "5400" }), "5.400 kg");
  assert.match(orderWeightText({ totalWeightGrams: null, knownWeightGrams: "5400", missingWeightQuantity: 2 }), /已知净重.*2 件未设置/);
  assert.match(orderWeightText({ totalWeightGrams: null, knownWeightGrams: "0", missingWeightQuantity: 7 }), /未设置.*7 件/);
});

test("draft preview includes only positive quantities and real sizes, never client weights or prices", () => {
  const items = [{ productId: 1, sizeCode: "30/M", quantity: 3, unitWeightGrams: 900, unitPrice: 29.9 },
    { productId: 1, sizeCode: "L", quantity: 0 }, { productId: 2, sizeCode: "Tall XL", quantity: 2 },
    { productId: 2, sizeCode: "M", quantity: null }, { productId: 3, sizeCode: null, quantity: 1 }];
  assert.deepEqual(orderWeightPreviewItems(items), [{ productId: 1, sizeCode: "30/M", quantity: 3 },
    { productId: 2, sizeCode: "Tall XL", quantity: 2 }, { productId: 3, sizeCode: "", quantity: 1 }]);
  assert.equal(items[0].unitPrice, 29.9);
  assert.equal(items[0].unitWeightGrams, 900);
  assert.deepEqual(orderWeightPreviewItems([]), []);
});
