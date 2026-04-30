<template>
  <AdminLayout>
    <div class="admin-page">
      <h1>仪表盘</h1>

      <div class="card-grid">
        <article v-for="item in admin.dashboard?.stats || []" :key="item.label" class="admin-card">
          <strong>{{ item.value }}</strong>
          <span>{{ item.label }}</span>
        </article>
      </div>

      <div class="admin-card">
        <h3>最近订单</h3>
        <div v-for="order in admin.dashboard?.recentOrders || []" :key="order.id" class="list-row stack-row">
          <div>
            <strong>{{ order.orderNo }}</strong>
            <p>{{ order.items?.map((item) => item.productName).join(' / ') || '--' }}</p>
          </div>
          <span>{{ order.status }}</span>
        </div>
      </div>
    </div>
  </AdminLayout>
</template>

<script setup>
import { onMounted } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()

onMounted(() => {
  admin.loadDashboard()
})
</script>
