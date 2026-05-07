<template>
  <AdminLayout>
    <div class="admin-page">
      <div class="admin-card admin-floating-card">
        <div class="page-head">
          <div>
            <h1>订单管理</h1>
            <p class="small-note">
              支持按时间、状态、分类和关键词筛选订单，并维护付款链接、物流单号、运费和订单状态。
            </p>
          </div>
          <button class="admin-button" type="button" :disabled="exporting" @click="exportOrders">
            {{ exporting ? '导出中...' : '导出订单 Excel' }}
          </button>
        </div>

        <div class="orders-filter-row orders-filter-row-wide orders-filter-row-full">
          <select v-model="selectedTimeRange" class="admin-field">
            <option value="today">今天</option>
            <option value="yesterday">昨天</option>
            <option value="all">全部时间</option>
            <option value="7d">近 7 天</option>
            <option value="30d">近 30 天</option>
            <option value="90d">近 90 天</option>
            <option value="year">今年</option>
          </select>

          <select v-model="selectedStatus" class="admin-field">
            <option value="all">全部状态</option>
            <option value="pending_payment">待付款</option>
            <option value="paid">已付款</option>
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

          <form class="order-search-form" @submit.prevent="applyKeyword">
            <input
              v-model.trim="keywordDraft"
              class="admin-field"
              placeholder="输入订单号或商城账号姓名"
            />
            <button class="admin-button admin-button-small" type="submit">查询</button>
          </form>
        </div>
      </div>

      <article v-for="order in paginatedOrders" :key="order.id" class="admin-card order-card">
        <div class="order-card-head">
          <div>
            <strong>{{ order.orderNo }}</strong>
            <p>{{ formatOrderOwner(order) }}</p>
            <p>{{ formatDate(order.createdAt) }} / {{ formatStatus(statusDrafts[order.id] || order.status) }}</p>
          </div>

          <div class="order-head-side">
            <select v-model="statusDrafts[order.id]" class="admin-field status-select">
              <option value="pending_payment">待付款</option>
              <option value="paid">已付款</option>
              <option value="shipped">已发货</option>
              <option value="completed">已完成</option>
              <option value="cancelled">已取消</option>
            </select>
            <strong>${{ displayTotal(order).toFixed(2) }}</strong>
          </div>
        </div>

        <div class="order-summary-grid">
          <div>
            <span>联系人</span>
            <strong>{{ order.contactName || '--' }}</strong>
          </div>
          <div>
            <span>联系邮箱</span>
            <strong>{{ order.contactValue || '--' }}</strong>
          </div>
          <div>
            <span>联系电话</span>
            <strong>{{ order.phone || '--' }}</strong>
          </div>
          <div>
            <span>物流单号</span>
            <strong>{{ trackingDrafts[order.id] || order.trackingNo || '暂未填写' }}</strong>
          </div>
          <div class="full-span">
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
          <div class="order-action-fields">
            <input
              v-model.trim="paymentLinkDrafts[order.id]"
              class="admin-field"
              placeholder="请输入付款链接"
              :disabled="statusDrafts[order.id] === 'cancelled'"
            />
            <input
              v-model.trim="trackingDrafts[order.id]"
              class="admin-field"
              placeholder="请输入物流单号"
              :disabled="statusDrafts[order.id] === 'cancelled'"
            />
            <input
              :value="shippingFeeDrafts[order.id]"
              class="admin-field"
              type="number"
              min="0"
              step="0.01"
              placeholder="请输入运费"
              :disabled="statusDrafts[order.id] === 'cancelled'"
              @input="updateShippingFeeDraft(order.id, $event)"
            />
          </div>

          <div class="inline-actions right-actions">
            <button class="admin-button" type="button" @click="saveOrder(order)">
              保存订单修改
            </button>
          </div>
        </div>
      </article>

      <div v-if="!filteredOrders.length" class="admin-card">当前筛选条件下暂无订单。</div>

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
const keywordDraft = ref('')
const keyword = ref('')
const currentPage = ref(1)
const pageSize = ref(6)
const trackingDrafts = reactive({})
const paymentLinkDrafts = reactive({})
const shippingFeeDrafts = reactive({})
const statusDrafts = reactive({})
const exporting = ref(false)

watch(
  () => admin.orders,
  (orders) => {
    orders.forEach((order) => {
      trackingDrafts[order.id] = order.trackingNo || ''
      paymentLinkDrafts[order.id] = order.paymentLink || ''
      shippingFeeDrafts[order.id] = Number(order.shippingFee || 0) > 0 ? String(order.shippingFee) : ''
      statusDrafts[order.id] = order.status || 'pending_payment'
    })
  },
  { immediate: true }
)

watch([selectedTimeRange, selectedStatus, selectedCategory, keyword, pageSize], () => {
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

const filteredOrders = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return admin.orders.filter((order) => {
    const statusMatch = selectedStatus.value === 'all' || order.status === selectedStatus.value
    const timeMatch = matchesTimeRange(order.createdAt, selectedTimeRange.value)
    const categoryMatch =
      selectedCategory.value === 'all' ||
      (order.items || []).some((item) => item.categoryKey === selectedCategory.value)
    const keywordMatch =
      !normalizedKeyword ||
      String(order.orderNo || '').toLowerCase().includes(normalizedKeyword) ||
      String(order.userName || '').toLowerCase().includes(normalizedKeyword)
    return statusMatch && timeMatch && categoryMatch && keywordMatch
  })
})

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

function applyKeyword() {
  keyword.value = keywordDraft.value.trim()
}

function updateShippingFeeDraft(orderId, event) {
  shippingFeeDrafts[orderId] = event.target.value
}

function formatOrderOwner(order) {
  const companyName = String(order.companyName || '').trim()
  const userName = String(order.userName || '').trim()
  if (companyName && userName) return `${companyName} / ${userName}`
  return companyName || userName || '--'
}

function matchesTimeRange(value, range) {
  if (range === 'all') return true
  const target = new Date(value)
  if (Number.isNaN(target.getTime())) return false
  const now = new Date()
  if (range === 'today') {
    return (
      target.getFullYear() === now.getFullYear() &&
      target.getMonth() === now.getMonth() &&
      target.getDate() === now.getDate()
    )
  }
  if (range === 'yesterday') {
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    return (
      target.getFullYear() === yesterday.getFullYear() &&
      target.getMonth() === yesterday.getMonth() &&
      target.getDate() === yesterday.getDate()
    )
  }
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
      pending_payment: '待付款',
      paid: '已付款',
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

function parseShippingFee(value) {
  if (value === '' || value === null || value === undefined) return 0
  const fee = Number(value)
  return Number.isNaN(fee) ? Number.NaN : fee
}

function displayTotal(order) {
  const itemsTotal = Number(order.items?.reduce((sum, item) => sum + Number(item.totalPrice || 0), 0) || 0)
  const shippingFee = parseShippingFee(shippingFeeDrafts[order.id])
  return itemsTotal + (Number.isNaN(shippingFee) ? 0 : shippingFee)
}

async function saveOrder(order) {
  const nextStatus = statusDrafts[order.id] || order.status || 'pending_payment'
  const nextTrackingNo = (trackingDrafts[order.id] || '').trim()
  const nextPaymentLink = (paymentLinkDrafts[order.id] || '').trim()
  const nextShippingFee = parseShippingFee(shippingFeeDrafts[order.id])

  if (nextStatus === 'shipped' && !nextTrackingNo) {
    window.alert('订单状态改为已发货时，必须填写物流单号。')
    return
  }

  if (Number.isNaN(nextShippingFee) || nextShippingFee < 0) {
    window.alert('运费必须是大于等于 0 的数字。')
    return
  }

  await admin.updateOrderStatus(order.id, nextStatus, nextTrackingNo, nextPaymentLink, nextShippingFee)
}

async function exportOrders() {
  exporting.value = true
  try {
    const blob = await admin.exportOrders({
      timeRange: selectedTimeRange.value,
      status: selectedStatus.value,
      category: selectedCategory.value,
      keyword: keyword.value,
      includeImages: '1',
    })
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `orders_export_${timestamp}.xlsx`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    window.alert(error.message || '导出订单失败')
  } finally {
    exporting.value = false
  }
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

.orders-filter-row-full {
  grid-template-columns: repeat(3, minmax(0, 220px)) minmax(320px, 1fr);
}

.order-search-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.admin-button-small {
  min-height: 46px;
  padding: 0 14px;
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

.order-action-fields {
  display: grid;
  gap: 10px;
}

.inline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.right-actions {
  justify-content: flex-end;
}

.status-select {
  width: 120px;
  min-height: 40px;
  padding-right: 30px;
}

@media (max-width: 1080px) {
  .orders-filter-row-full {
    grid-template-columns: 1fr;
  }

  .order-search-form {
    grid-template-columns: 1fr;
  }

  .order-item-main {
    width: 100%;
  }

  .right-actions {
    justify-content: flex-start;
  }
}
</style>
