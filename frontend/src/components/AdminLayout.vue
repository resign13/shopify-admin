<template>
  <div class="admin-shell">
    <aside class="sidebar">
      <div class="brand-block">
        <h2>GINGTTO 管理后台</h2>
        <p>{{ auth.user?.name || '未登录用户' }}</p>
        <span class="role-chip">{{ roleLabel }}</span>
      </div>

      <nav class="sidebar-nav">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to">
          {{ item.label }}
        </RouterLink>
      </nav>

      <button class="admin-button ghost logout-button" type="button" @click="logout">
        退出登录
      </button>
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
.brand-block {
  display: grid;
  gap: 8px;
}

.brand-block h2,
.brand-block p {
  margin: 0;
}

.brand-block p {
  color: rgba(255, 255, 255, 0.76);
}

.role-chip {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: white;
  font-size: 0.88rem;
}

.logout-button {
  margin-top: auto;
}
</style>
