import { routeModule } from "./permissions";
import { createRouter, createWebHistory } from "vue-router";
import { pinia } from "./stores";
import { useAdminAuthStore } from "./stores/auth";
const definitions = [
  ["finance", "FinanceView", "财务管理", ["admin", "finance"]],
  ["contracts", "ContractsView", "合同管理", ["admin", "sales"]],
  ["dashboard", "DashboardView", "经营工作台", ["admin", "sales"]],
  ["products", "ProductsView", "商品管理", ["admin", "sales"]],
  ["products/new", "ProductEditorView", "新建商品", ["admin", "sales"]],
  ["products/:id/edit", "ProductEditorView", "编辑商品", ["admin", "sales"]],
  [
    "inventory",
    "InventoryView",
    "库存管理",
    ["admin", "sales", "warehouse", "customer"],
  ],
  ["orders", "OrdersView", "订单管理", ["admin", "sales", "warehouse"]],
  ["categories", "CategoriesView", "商品分类", ["admin", "sales"]],
  ["presale", "PresaleView", "预售管理", ["admin", "sales"]],
  ["store-accounts", "AccountsView", "商城账号", ["admin"]],
  ["admin-users", "AdminUsersView", "后台账号", ["admin"]],
  ["audit-logs", "AuditLogsView", "操作日志", ["admin"]],
];
const views = import.meta.glob([
  "./views/*.vue",
  "!./views/BannersView.vue",
  "!./views/ActivityZoneView.vue",
  "!./views/HomeConfigView.vue",
  "!./views/ActivityApplyView.vue",
  "!./views/ActivityManageView.vue",
]);
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: () => import("./views/LoginView.vue") },
    {
      path: "/",
      component: () => import("./components/AdminLayout.vue"),
      meta: { requiresAuth: true },
      children: [
        { path: "", redirect: "/dashboard" },
        {
          path: "no-access",
          component: () => import("./views/NoAccessView.vue"),
          meta: { title: "模块权限" },
        },
        ...definitions.map(([path, view, title, roles]) => ({
          path,
          component: views[`./views/${view}.vue`],
          meta: { title, roles, module: routeModule(path), requiresAuth: true },
        })),
        { path: "accounts", redirect: "/store-accounts" },

      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
router.beforeEach(async (to) => {
  const auth = useAdminAuthStore(pinia);
  if (!auth.initialized) await auth.initialize();
  if (to.meta.requiresAuth && !auth.isAuthenticated) return "/login";
  if (to.path === "/login" && auth.isAuthenticated) return auth.defaultRoute;
  if (to.meta.module && !auth.can(to.meta.module)) return auth.defaultRoute;
  document.title = `${to.meta.title || "登录"} · GINGTTO`;
});
export default router;
