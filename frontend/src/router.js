import { createRouter, createWebHistory } from 'vue-router'

import AdminUsersView from './views/AdminUsersView.vue'
import AccountsView from './views/AccountsView.vue'
import ActivityApplyView from './views/ActivityApplyView.vue'
import ActivityManageView from './views/ActivityManageView.vue'
import CategoriesView from './views/CategoriesView.vue'
import DashboardView from './views/DashboardView.vue'
import HomeConfigView from './views/HomeConfigView.vue'
import InventoryView from './views/InventoryView.vue'
import LoginView from './views/LoginView.vue'
import OrdersView from './views/OrdersView.vue'
import ProductEditorView from './views/ProductEditorView.vue'
import ProductsView from './views/ProductsView.vue'
import { pinia } from './stores'
import { useAdminAuthStore } from './stores/auth'
import { startRouteLoading, stopRouteLoading } from './loading'

function withAuth(component, roles) {
  return {
    component,
    meta: {
      requiresAuth: true,
      roles,
    },
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView },
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', ...withAuth(DashboardView, ['admin', 'sales']) },
    { path: '/home-config', ...withAuth(HomeConfigView, ['admin', 'sales']) },
    { path: '/activity-zone', redirect: '/activity-zone/apply' },
    { path: '/activity-zone/apply', ...withAuth(ActivityApplyView, ['admin', 'sales']) },
    { path: '/activity-zone/manage', ...withAuth(ActivityManageView, ['admin', 'sales']) },
    { path: '/categories', ...withAuth(CategoriesView, ['admin', 'sales']) },
    { path: '/products', ...withAuth(ProductsView, ['admin', 'sales']) },
    { path: '/inventory', ...withAuth(InventoryView, ['admin', 'sales', 'warehouse', 'customer']) },
    { path: '/products/new', ...withAuth(ProductEditorView, ['admin', 'sales']) },
    { path: '/products/:id/edit', ...withAuth(ProductEditorView, ['admin', 'sales']) },
    { path: '/accounts', redirect: '/store-accounts' },
    { path: '/store-accounts', ...withAuth(AccountsView, ['admin']) },
    { path: '/admin-users', ...withAuth(AdminUsersView, ['admin']) },
    { path: '/orders', ...withAuth(OrdersView, ['admin', 'sales', 'warehouse']) },
  ],
})

router.beforeEach(async (to) => {
  startRouteLoading()
  const auth = useAdminAuthStore(pinia)
  if (!auth.initialized) {
    await auth.initialize()
  }
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return '/login'
  }
  if (to.path === '/login' && auth.isAuthenticated) {
    return auth.defaultRoute
  }
  if (to.meta.requiresAuth) {
    const allowedRoles = Array.isArray(to.meta.roles) ? to.meta.roles : []
    if (allowedRoles.length && !allowedRoles.includes(auth.userRole)) {
      return auth.defaultRoute
    }
  }
  return true
})

export default router


router.afterEach(() => {
  window.setTimeout(() => {
    stopRouteLoading()
  }, 120)
})

router.onError(() => {
  stopRouteLoading()
})
