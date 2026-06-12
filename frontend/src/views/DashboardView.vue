<template>
  <AdminLayout>
    <div class="admin-page">
      <div class="summary-head">
        <div>
          <h1>Dashboard</h1>
          <p class="summary-subtext">Visualize daily order trends with style, country, and date-range filters.</p>
        </div>
      </div>

      <section class="admin-card dashboard-filter-card">
        <div class="orders-filter-row dashboard-filter-grid">
          <label class="field-label">
            <span>Style</span>
            <select v-model="filters.style" class="admin-field">
              <option value="all">All styles</option>
              <option v-for="item in styleOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label class="field-label">
            <span>Country</span>
            <select v-model="filters.country" class="admin-field">
              <option value="all">All countries</option>
              <option v-for="item in countryOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label class="field-label">
            <span>Start date</span>
            <input v-model="filters.dateFrom" class="admin-field" type="date" />
          </label>

          <label class="field-label">
            <span>End date</span>
            <input v-model="filters.dateTo" class="admin-field" type="date" />
          </label>
        </div>

        <div class="inline-actions dashboard-filter-actions">
          <button class="admin-button" type="button" :disabled="loading" @click="applyFilters">{{ loading ? 'Loading...' : 'Apply filters' }}</button>
          <button class="admin-button ghost" type="button" :disabled="loading" @click="resetFilters">Reset</button>
        </div>
      </section>

      <div class="card-grid">
        <article v-for="item in admin.dashboard?.stats || []" :key="item.label" class="admin-card">
          <strong>{{ item.value }}</strong>
          <span>{{ item.label }}</span>
        </article>
      </div>

      <section class="admin-card dashboard-trend-card">
        <div class="summary-head">
          <div>
            <h3>Daily order trend</h3>
            <p class="summary-subtext">{{ trendDateRangeLabel }} · {{ trendSummary.orderCount }} orders / {{ trendSummary.itemCount }} items / ${{ formatAmount(trendSummary.totalAmount) }}</p>
          </div>
        </div>

        <div class="dashboard-trend-metrics">
          <div class="style-summary-card">
            <span class="style-summary-category">Filtered orders</span>
            <strong>{{ trendSummary.orderCount }}</strong>
          </div>
          <div class="style-summary-card">
            <span class="style-summary-category">Filtered items</span>
            <strong>{{ trendSummary.itemCount }}</strong>
          </div>
          <div class="style-summary-card">
            <span class="style-summary-category">Filtered amount</span>
            <strong>${{ formatAmount(trendSummary.totalAmount) }}</strong>
          </div>
        </div>

        <div v-if="trendPoints.length" class="dashboard-chart-wrap">
          <div class="dashboard-chart-y-axis">
            <span>{{ trendMax }}</span>
            <span>{{ Math.max(0, Math.round(trendMax / 2)) }}</span>
            <span>0</span>
          </div>
          <svg viewBox="0 0 760 260" class="dashboard-chart" preserveAspectRatio="none">
            <line v-for="guide in chartGuides" :key="guide.y" x1="0" :y1="guide.y" x2="760" :y2="guide.y" class="chart-guide" />
            <polyline :points="chartPolyline" class="chart-line" />
            <circle v-for="point in chartPoints" :key="point.date" :cx="point.x" :cy="point.y" r="4.5" class="chart-dot">
              <title>{{ point.date }}: {{ point.orderCount }} orders</title>
            </circle>
          </svg>
        </div>
        <div v-else class="empty-state">No order data for the current filters.</div>

        <div v-if="trendPoints.length" class="dashboard-chart-labels">
          <span>{{ trendPoints[0]?.date || '' }}</span>
          <span>{{ trendPoints[trendPoints.length - 1]?.date || '' }}</span>
        </div>
      </section>

      <div class="admin-card">
        <h3>Recent orders</h3>
        <div v-if="recentOrders.length">
          <div v-for="order in recentOrders" :key="order.id" class="list-row stack-row">
            <div>
              <strong>{{ order.orderNo }}</strong>
              <p>{{ order.items?.map((item) => item.productName || item.sku).join(' / ') || '--' }}</p>
            </div>
            <span>{{ order.status }}</span>
          </div>
        </div>
        <div v-else class="empty-state">No recent orders for the current filters.</div>
      </div>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const loading = ref(false)

function formatDateInput(date) {
  return date.toISOString().slice(0, 10)
}

function createDefaultFilters() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 29)
  return {
    style: 'all',
    country: 'all',
    dateFrom: formatDateInput(start),
    dateTo: formatDateInput(end),
  }
}

const filters = reactive(createDefaultFilters())
const styleOptions = computed(() => admin.dashboard?.filters?.styles || [])
const countryOptions = computed(() => admin.dashboard?.filters?.countries || [])
const trendPoints = computed(() => admin.dashboard?.trend?.points || [])
const recentOrders = computed(() => admin.dashboard?.recentOrders || [])
const trendSummary = computed(() => admin.dashboard?.trend?.summary || { orderCount: 0, itemCount: 0, totalAmount: 0, dateFrom: '', dateTo: '', maxOrderCount: 0 })
const trendMax = computed(() => Math.max(1, Number(trendSummary.value.maxOrderCount || 0)))
const trendDateRangeLabel = computed(() => {
  if (!trendSummary.value.dateFrom || !trendSummary.value.dateTo) return 'All time'
  return `${trendSummary.value.dateFrom} to ${trendSummary.value.dateTo}`
})

const chartPoints = computed(() => {
  const points = trendPoints.value
  if (!points.length) return []
  const width = 760
  const height = 260
  const xStep = points.length <= 1 ? 0 : width / (points.length - 1)
  return points.map((point, index) => ({
    ...point,
    x: Number((index * xStep).toFixed(2)),
    y: Number((height - (Number(point.orderCount || 0) / trendMax.value) * (height - 20) - 10).toFixed(2)),
  }))
})

const chartPolyline = computed(() => chartPoints.value.map((point) => `${point.x},${point.y}`).join(' '))
const chartGuides = computed(() => [{ y: 10 }, { y: 130 }, { y: 250 }])

function formatAmount(value) {
  return Number(value || 0).toFixed(2)
}

async function applyFilters() {
  loading.value = true
  try {
    await admin.loadDashboard({ ...filters })
  } finally {
    loading.value = false
  }
}

async function resetFilters() {
  Object.assign(filters, createDefaultFilters())
  await applyFilters()
}

onMounted(() => {
  applyFilters()
})
</script>

<style scoped>
.dashboard-filter-card,
.dashboard-trend-card {
  display: grid;
  gap: 16px;
}

.dashboard-filter-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.dashboard-filter-actions {
  justify-content: flex-end;
}

.dashboard-trend-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.dashboard-chart-wrap {
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 14px;
  align-items: stretch;
}

.dashboard-chart-y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  color: var(--muted);
  font-size: 0.85rem;
  padding: 4px 0 8px;
}

.dashboard-chart {
  width: 100%;
  height: 260px;
  overflow: visible;
}

.chart-guide {
  stroke: rgba(110, 85, 61, 0.16);
  stroke-dasharray: 4 6;
}

.chart-line {
  fill: none;
  stroke: #b36e48;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.chart-dot {
  fill: #b36e48;
  stroke: #fff;
  stroke-width: 2;
}

.dashboard-chart-labels {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  font-size: 0.85rem;
}

@media (max-width: 1080px) {
  .dashboard-filter-grid,
  .dashboard-trend-metrics {
    grid-template-columns: 1fr;
  }

  .dashboard-chart-wrap {
    grid-template-columns: 1fr;
  }

  .dashboard-chart-y-axis {
    display: none;
  }
}
</style>
