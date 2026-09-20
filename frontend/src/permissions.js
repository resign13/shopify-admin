export const moduleGroups = [
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
      ["home-config", "首页配置"],
      ["activity-zone/apply", "活动报名"],
      ["activity-zone/manage", "活动管理"],
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
export function roleModules(role) {
  if (role === "admin") return [...all];
  if (role === "sales")
    return all.filter(
      (key) => !["store-accounts", "admin-users", "audit-logs"].includes(key),
    );
  if (role === "warehouse") return ["inventory", "orders"];
  return role === "customer" ? ["inventory"] : [];
}
export function routeModule(path) {
  const clean = path.replace(/^\//, "");
  return clean.startsWith("activity-zone/") ? clean : clean.split("/")[0];
}
