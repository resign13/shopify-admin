<template>
  <div class="admin-shell">
    <aside class="sidebar">
      <div class="topbar-main">
        <div class="brand-block">
          <div>
            <h2>GINGTTO 管理后台</h2>
            <p>{{ auth.user?.name || '未登录用户' }}</p>
          </div>
          <span class="role-chip">{{ roleLabel }}</span>
        </div>

        <button class="admin-button ghost logout-button" type="button" @click="logout">
          退出登录
        </button>
      </div>

      <nav class="sidebar-nav">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <section class="admin-content">
      <slot />
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { useAdminAuthStore } from '../stores/auth'

const auth = useAdminAuthStore()
const router = useRouter()

const roleLabelMap = {
  admin: '管理员',
  sales: '外贸部',
  warehouse: '仓库部',
}

const allNavItems = [
  { to: '/dashboard', label: '仪表盘', roles: ['admin', 'sales'] },
  { to: '/home-config', label: '首页配置', roles: ['admin', 'sales'] },
  { to: '/activity-zone/apply', label: '活动报名', roles: ['admin', 'sales'] },
  { to: '/activity-zone/manage', label: '活动管理', roles: ['admin', 'sales'] },
  { to: '/categories', label: '商品分类', roles: ['admin', 'sales'] },
  { to: '/products', label: '商品管理', roles: ['admin', 'sales'] },
  { to: '/inventory', label: '库存管理', roles: ['admin', 'sales', 'warehouse'] },
  { to: '/store-accounts', label: '商城账号', roles: ['admin'] },
  { to: '/admin-users', label: '后台账号', roles: ['admin'] },
  { to: '/orders', label: '订单管理', roles: ['admin', 'sales', 'warehouse'] },
]

const navItems = computed(() => allNavItems.filter((item) => item.roles.includes(auth.userRole || '')))
const roleLabel = computed(() => roleLabelMap[auth.userRole] || '未分配角色')

async function logout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.topbar-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand-block h2,
.brand-block p {
  margin: 0;
}

.brand-block h2 {
  font-size: 1.15rem;
  line-height: 1.2;
}

.brand-block p {
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.76);
  font-size: 0.9rem;
}

.role-chip {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: white;
  font-size: 0.82rem;
  white-space: nowrap;
}

.logout-button {
  min-height: 38px;
  padding: 0 14px;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .topbar-main,
  .brand-block {
    flex-direction: column;
    align-items: flex-start;
  }

  .logout-button {
    width: 100%;
  }
}
</style>
