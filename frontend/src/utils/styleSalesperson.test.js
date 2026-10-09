import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stylePerformanceQuery, isPersonalStyleScope } from "./styleSalesperson.js";

const overview = { dateFrom: "2026-10-01", dateTo: "2026-10-08", country: "Germany", style: "CS2209", salespersonId: "2" };
const filters = { keyword: "CS2209", category: "pants", sort: "amount", direction: "desc", risk: "", velocityWindow: "7" };
test("style owner overrides only the panel and retains style, country, dates and sort", () => {
  const query = stylePerformanceQuery(overview, { ...filters, styleSalespersonId: "5" }, true);
  assert.equal(query.salespersonId, "5");
  for (const key of ["dateFrom", "dateTo", "country", "style"]) assert.equal(query[key], overview[key]);
  for (const key of ["keyword", "category", "sort", "direction"]) assert.equal(query[key], filters[key]);
  assert.equal(overview.salespersonId, "2");
  assert.equal("styleSalespersonId" in query, false);
});
test("clear/reset inherits overview; all and unassigned have distinct scopes", () => {
  assert.equal(stylePerformanceQuery(overview, { ...filters, styleSalespersonId: "" }, true).salespersonId, "2");
  const all = stylePerformanceQuery(overview, { ...filters, styleSalespersonId: "all" }, true);
  assert.equal(all.salespersonId, "all");
  assert.equal(isPersonalStyleScope(all, false), false);
  assert.equal(isPersonalStyleScope({ salespersonId: "unassigned" }, false), true);
});
test("personal panel removes company risk and inventory sorting", () => {
  const query = stylePerformanceQuery(overview, { ...filters, risk: "backordered", sort: "stock", styleSalespersonId: "5" }, true);
  assert.equal(query.risk, "");
  assert.equal(query.sort, "units");
  const all = stylePerformanceQuery(overview, { ...filters, risk: "backordered", sort: "stock", styleSalespersonId: "all" }, true);
  assert.equal(all.risk, "backordered");
  assert.equal(all.sort, "stock");
});
test("sales role never submits forged overview or panel salesperson", () => {
  const query = stylePerformanceQuery(overview, { ...filters, styleSalespersonId: "5" }, false);
  assert.equal("salespersonId" in query, false);
  assert.equal(isPersonalStyleScope(query, true), true);
});
test("panel owner persists in routes and details without changing overview scope", () => {
  const source = readFileSync(new URL("../views/DashboardView.vue", import.meta.url), "utf8");
  assert.match(source, /aria-label="款号业务员筛选"/);
  assert.match(source, /styleSalespersonId: panelSalespersonId/);
  assert.match(source, /styleSalespersonId\.value = auth\.isSuperAdmin \? scalar\(q\.styleSalespersonId\)/);
  assert.match(source, /requestedStyleQuery\.value = filters/);
  assert.match(source, /\.\.\.appliedStyleQuery\.value,[\s\S]*view: "style-detail"/);
  assert.match(source, /<section v-if="!personalScope" class="panel">/);
});
