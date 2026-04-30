<template>
  <AdminLayout>
    <div class="admin-page">
      <div class="admin-card">
        <div class="page-head">
          <div>
            <h1>订单管理</h1>
            <p class="small-note">
              支持按时间、订单状态和商品分类筛选订单，发货后可更新物流单号。
            </p>
          </div>
        </div>

        <div class="orders-filter-row orders-filter-row-wide">
          <select v-model="selectedTimeRange" class="admin-field">
            <option value="all">全部时间</option>
            <option value="7d">近 7 天</option>
            <option value="30d">近 30 天</option>
            <option value="90d">近 90 天</option>
            <option value="year">今年</option>
          </select>

          <select v-model="selectedStatus" class="admin-field">
            <option value="all">全部状态</option>
            <option value="pending">待处理</option>
            <option value="paid">已付款</option>
            <option value="packed">已打包</option>
            <option value="shipped">已发货</option>
            <option value="completed">已完成</option>
            <option value="cancelled">已取消</option>
          </select>

          <select v-model="selectedCategory" class="admin-field">
            <option value="all">全部分类</option>
            <option v-for="item in categoryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </div>
      </div>

      <article v-for="order in paginatedOrders" :key="order.id" class="admin-card order-card">
        <div class="order-card-head">
          <div>
            <strong>{{ order.orderNo }}</strong>
            <p>{{ order.companyName || '--' }} / {{ order.userEmail || '--' }}</p>
            <p>{{ formatDate(order.createdAt) }} / {{ formatStatus(order.status) }}</p>
          </div>

          <div class="order-head-side">
            <span class="order-status-badge" :class="`status-${order.status}`">
              {{ formatStatus(order.status) }}
            </span>
            <strong>${{ Number(order.totalAmount || 0).toFixed(2) }}</strong>
          </div>
        </div>

        <div class="order-summary-grid">
          <div>
            <span>联系人</span>
            <strong>{{ order.contactName || '--' }}</strong>
          </div>
          <div>
            <span>联系电话</span>
            <strong>{{ order.phone || '--' }}</strong>
          </div>
          <div>
            <span>物流单号</span>
            <strong>{{ order.trackingNo || '暂未填写' }}</strong>
          </div>
          <div>
            <span>收货地址</span>
            <strong>{{ order.shippingAddress || '--' }}</strong>
          </div>
        </div>

        <div class="order-items-stack">
          <div class="order-items-head">
            <strong>订单内容</strong>
            <span>{{ order.itemCount }} 件</span>
          </div>

          <div v-if="order.items.length">
            <div
              v-for="item in order.items"
              :key="`${order.id}-${item.productId}-${item.sku}-${item.sizeCode}`"
              class="order-item-row"
            >
              <div class="order-item-main">
                <div v-if="item.image" class="order-item-image">
                  <img :src="item.image" :alt="item.productName" />
                </div>

                <div class="order-item-copy">
                  <strong>{{ item.productName || item.sku }}</strong>
                  <p>
                    SKU {{ item.sku || '--' }}
                    <span v-if="item.sizeCode"> / 尺码 {{ item.sizeCode }}</span>
                    <span v-if="item.categoryLabel"> / {{ item.categoryLabel }}</span>
                  </p>
                </div>
              </div>

              <div class="order-item-side">
                <span>{{ item.quantity }} 件</span>
                <strong>${{ Number(item.totalPrice || 0).toFixed(2) }}</strong>
              </div>
            </div>
          </div>

          <div v-else class="small-note">当前订单暂无商品明细。</div>
        </div>

        <div class="order-actions-panel">
          <input
            v-model.trim="trackingDrafts[order.id]"
            class="admin-field"
            placeholder="请输入物流单号"
            :disabled="order.status === 'cancelled'"
          />

          <div class="inline-actions">
            <button
              v-if="canMarkShipped(order)"
              class="admin-button"
              type="button"
              @click="markShipped(order)"
            >
              标记为已发货
            </button>

            <button
              v-if="canSaveTracking(order)"
              class="admin-button ghost"
              type="button"
              @click="saveTracking(order)"
            >
              保存物流单号
            </button>

            <button
              v-if="order.status === 'shipped'"
              class="admin-button"
              type="button"
              @click="markCompleted(order)"
            >
              标记为已完成
            </button>
          </div>
        </div>
      </article>

      <div v-if="!filteredOrders.length" class="admin-card">
        当前筛选条件下暂无订单。
      </div>

      <div v-else class="admin-card">
        <PaginationBar
          :page="currentPage"
          :page-size="pageSize"
          :total-items="filteredOrders.length"
          item-label="个订单"
          @update:page="currentPage = $event"
          @update:page-size="pageSize = $event"
        />
      </div>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import PaginationBar from '../components/PaginationBar.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const selectedTimeRange = ref('all')
const selectedStatus = ref('all')
const selectedCategory = ref('all')
const currentPage = ref(1)
const pageSize = ref(6)
const trackingDrafts = reactive({})

watch(
  () => admin.orders,
  (orders) => {
    orders.forEach((order) => {
      trackingDrafts[order.id] = order.trackingNo || ''
    })
  },
  { immediate: true }
)

watch([selectedTimeRange, selectedStatus, selectedCategory, pageSize], () => {
  currentPage.value = 1
})

const categoryOptions = computed(() => {
  const map = new Map()
  admin.orders.forEach((order) => {
    ;(order.items || []).forEach((item) => {
      if (!item.categoryKey) return
      if (!map.has(item.categoryKey)) {
        map.set(item.categoryKey, item.categoryLabel || item.categoryKey)
      }
    })
  })
  return Array.from(map.entries()).map(([value, label]) => ({ value, label }))
})

const filteredOrders = computed(() =>
  admin.orders.filter((order) => {
    const statusMatch = selectedStatus.value === 'all' || order.status === selectedStatus.value
    const timeMatch = matchesTimeRange(order.createdAt, selectedTimeRange.value)
    const categoryMatch =
      selectedCategory.value === 'all' ||
      (order.items || []).some((item) => item.categoryKey === selectedCategory.value)
    return statusMatch && timeMatch && categoryMatch
  })
)

const paginatedOrders = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredOrders.value.slice(start, start + pageSize.value)
})

watch(
  () => filteredOrders.value.length,
  (count) => {
    const totalPages = Math.max(1, Math.ceil(count / pageSize.value))
    if (currentPage.value > totalPages) {
      currentPage.value = totalPages
    }
  },
  { immediate: true }
)

function matchesTimeRange(value, range) {
  if (range === 'all') return true
  const target = new Date(value)
  if (Number.isNaN(target.getTime())) return false
  const now = new Date()
  const diffDays = (now.getTime() - target.getTime()) / (24 * 60 * 60 * 1000)
  if (range === '7d') return diffDays <= 7
  if (range === '30d') return diffDays <= 30
  if (range === '90d') return diffDays <= 90
  if (range === 'year') return target.getFullYear() === now.getFullYear()
  return true
}

function formatStatus(status) {
  return (
    {
      pending: '待处理',
      paid: '已付款',
      packed: '已打包',
      shipped: '已发货',
      completed: '已完成',
      cancelled: '已取消',
    }[status] || status
  )
}

function formatDate(value) {
  const date = value ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function canMarkShipped(order) {
  return ['pending', 'paid', 'packed'].includes(order.status)
}

function canSaveTracking(order) {
  return ['shipped', 'completed'].includes(order.status)
}

async function saveTracking(order) {
  const trackingNo = (trackingDrafts[order.id] || '').trim()
  if (!trackingNo) {
    window.alert('请先输入物流单号。')
    return
  }
  await admin.updateOrderStatus(order.id, order.status, trackingNo)
}

async function markShipped(order) {
  const trackingNo = (trackingDrafts[order.id] || '').trim()
  if (!trackingNo) {
    window.alert('请先输入物流单号。')
    return
  }
  await admin.updateOrderStatus(order.id, 'shipped', trackingNo)
}

async function markCompleted(order) {
  const trackingNo = (trackingDrafts[order.id] || order.trackingNo || '').trim()
  await admin.updateOrderStatus(order.id, 'completed', trackingNo)
}

onMounted(() => {
  admin.loadOrders()
})
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-head h1 {
  margin: 0 0 6px;
}

.order-item-main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.order-item-image {
  width: 60px;
  height: 78px;
  overflow: hidden;
  border: 1px solid rgba(110, 85, 61, 0.14);
  border-radius: 14px;
  background: #f7f3ee;
  flex-shrink: 0;
}

.order-item-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.order-item-copy {
  display: grid;
  gap: 4px;
}

.order-item-copy strong,
.order-item-copy p {
  margin: 0;
}

@media (max-width: 1080px) {
  .order-item-main {
    width: 100%;
  }
}
</style>
