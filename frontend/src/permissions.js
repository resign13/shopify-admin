export const moduleGroups = [
  { label: "财务核算", items: [["finance", "财务管理"]] },
  { label: "经营概览", items: [["dashboard", "经营工作台"]] },
  {
    label: "商品与库存",
    items: [
      ["products", "商品管理"],
      ["inventory", "库存管理"],
      ["categories", "商品分类"],
    ],
  },
  {
    label: "订单业务",
    items: [
      ["orders", "订单管理"],
      ["contracts", "合同管理"],
    ],
  },
  {
    label: "商城运营",
    items: [
      ["presale", "预售管理"],
    ],
  },
  {
    label: "账号与系统",
    items: [
      ["store-accounts", "商城账号"],
      ["admin-users", "后台账号"],
      ["audit-logs", "操作日志"],
    ],
  },
];
const all = moduleGroups.flatMap((group) => group.items.map(([key]) => key));
const defaults = {
  admin: all,
  sales: ["dashboard", "products", "inventory", "orders", "categories", "contracts"],
  warehouse: ["inventory", "orders"],
  finance: ["finance", "contracts"],
  customer: ["inventory"],
};
export function roleModules(role) {
  if (["admin", "sales", "warehouse", "finance"].includes(role)) return [...all];
  return role === "customer" ? ["inventory"] : [];
}
export function routeModule(path) {
  const clean = path.replace(/^\//, "");
  return clean.startsWith("activity-zone/") ? clean : clean.split("/")[0];
}

export function defaultRoleModules(role) {
 return [...(defaults[role] || [])];
}

export function editableRolePermissions(role, permissions) {
  const allowed = roleModules(role);
  return [...(permissions ?? defaultRoleModules(role))].filter(key => allowed.includes(key));
}
