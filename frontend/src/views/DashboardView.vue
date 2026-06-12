<template>
  <AdminLayout>
    <div class="admin-page dashboard-page">
      <section class="dashboard-toolbar admin-card">
        <label class="field-label">
          <span>款式</span>
          <select v-model="filters.style" class="admin-field" @change="applyFilters">
            <option value="all">全部款式</option>
            <option v-for="item in styleOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>

        <label class="field-label">
          <span>国家</span>
          <select v-model="filters.country" class="admin-field" @change="applyFilters">
            <option value="all">全部国家</option>
            <option v-for="item in countryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>

        <div class="field-label date-range-field">
          <span>时间</span>
          <button class="admin-field date-range-trigger" type="button" @click="datePanelOpen = !datePanelOpen">
            <span>{{ dateRangeText }}</span>
            <span class="date-range-caret">▾</span>
          </button>

          <div v-if="datePanelOpen" class="date-range-panel">
            <div class="quick-ranges">
              <button
                v-for="preset in datePresets"
                :key="preset.key"
                type="button"
                :class="['quick-range-btn', { active: activePreset === preset.key }]"
                @click="applyPreset(preset.key)"
              >
                {{ preset.label }}
              </button>
            </div>

            <div class="date-range-main">
              <div class="date-range-editors">
                <label>
                  <span>开始日期</span>
                  <input v-model="draftDates.from" class="admin-field" type="date" @change="activePreset = 'custom'" />
                </label>
                <label>
                  <span>结束日期</span>
                  <input v-model="draftDates.to" class="admin-field" type="date" @change="activePreset = 'custom'" />
                </label>
              </div>

              <div class="calendar-preview">
                <div v-for="month in calendarMonths" :key="month.title" class="calendar-month">
                  <strong>{{ month.title }}</strong>
                  <div class="calendar-weekdays">
                    <span v-for="day in weekDays" :key="day">{{ day }}</span>
                  </div>
                  <div class="calendar-days">
                    <span v-for="blank in month.leading" :key="`b-${month.title}-${blank}`"></span>
                    <button
                      v-for="day in month.days"
                      :key="day.value"
                      type="button"
                      :class="['calendar-day', { inRange: isInDraftRange(day.value), edge: isDraftEdge(day.value) }]"
                      @click="pickCalendarDate(day.value)"
                    >
                      {{ day.label }}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div class="date-panel-actions">
              <button class="admin-button ghost" type="button" @click="datePanelOpen = false">取消</button>
              <button class="admin-button" type="button" @click="confirmDateRange">确定</button>
            </div>
          </div>
        </div>

        <button class="admin-button" type="button" :disabled="loading" @click="applyFilters">
          {{ loading ? '加载中...' : '查询' }}
        </button>
        <button class="admin-button ghost" type="button" :disabled="loading" @click="resetFilters">重置</button>
      </section>

      <section class="metric-grid">
        <article class="metric-card">
          <span>订单数</span>
          <strong>{{ trendSummary.orderCount }}</strong>
        </article>
        <article class="metric-card">
          <span>商品件数</span>
          <strong>{{ trendSummary.itemCount }}</strong>
        </article>
        <article class="metric-card">
          <span>订单金额</span>
          <strong>${{ formatAmount(trendSummary.totalAmount) }}</strong>
        </article>
        <article class="metric-card">
          <span>款式数</span>
          <strong>{{ styleSummary.length }}</strong>
        </article>
      </section>

      <section class="admin-card chart-card">
        <div class="chart-head">
          <div>
            <h3>每日订单趋势</h3>
            <p class="summary-subtext">{{ dateRangeText }} · 按订单下单日期统计</p>
          </div>
          <div class="chart-legend"><span></span>订单数</div>
        </div>

        <div v-if="trendPoints.length" class="line-chart-wrap">
          <svg viewBox="0 0 920 320" class="line-chart" preserveAspectRatio="none" role="img" aria-label="每日订单趋势图">
            <line v-for="guide in chartGuides" :key="guide.y" x1="52" :y1="guide.y" x2="900" :y2="guide.y" class="chart-guide" />
            <text v-for="guide in chartGuides" :key="`label-${guide.y}`" x="42" :y="guide.y + 5" text-anchor="end" class="axis-label">{{ guide.label }}</text>
            <polyline :points="chartPolyline" class="chart-area-line" />
            <circle v-for="point in chartPoints" :key="point.date" :cx="point.x" :cy="point.y" r="5" class="chart-dot">
              <title>{{ point.date }}：{{ point.orderCount }} 单，{{ point.itemCount }} 件</title>
            </circle>
          </svg>
          <div class="chart-x-labels">
            <span>{{ trendPoints[0]?.date || '' }}</span>
            <span>{{ trendPoints[Math.floor((trendPoints.length - 1) / 2)]?.date || '' }}</span>
            <span>{{ trendPoints[trendPoints.length - 1]?.date || '' }}</span>
          </div>
        </div>
        <div v-else class="empty-state">当前筛选条件下暂无订单数据。</div>
      </section>

      <section class="admin-card chart-card">
        <div class="chart-head">
          <div>
            <h3>款式数量统计</h3>
            <p class="summary-subtext">按整款编码汇总商品件数，例如 CS2010-黑色 / CS2010-白色 统一计入 CS2010。</p>
          </div>
        </div>

        <div v-if="topStyleSummary.length" class="style-bars">
          <div v-for="item in topStyleSummary" :key="item.style" class="style-bar-row">
            <div class="style-bar-name">{{ item.label || item.style }}</div>
            <div class="style-bar-track">
              <div class="style-bar-fill" :style="{ width: `${styleBarPercent(item.quantity)}%` }"></div>
            </div>
            <div class="style-bar-value">{{ item.quantity }} 件</div>
          </div>
        </div>
        <div v-else class="empty-state">当前筛选条件下暂无款式数量。</div>
      </section>

      <section class="admin-card">
        <h3>最近订单</h3>
        <div v-if="recentOrders.length">
          <div v-for="order in recentOrders" :key="order.id" class="list-row stack-row">
            <div>
              <strong>{{ order.orderNo }}</strong>
              <p>{{ order.items?.map((item) => `${item.sku || item.productName} × ${item.quantity || 0}`).join(' / ') || '--' }}</p>
            </div>
            <span>{{ order.status }}</span>
          </div>
        </div>
        <div v-else class="empty-state">当前筛选条件下暂无最近订单。</div>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const loading = ref(false)
const datePanelOpen = ref(false)
const activePreset = ref('last30')
const selectingStart = ref(true)
const weekDays = ['日', '一', '二', '三', '四', '五', '六']

function pad(value) {
  return String(value).padStart(2, '0')
}

function formatDateInput(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function parseDate(value) {
  if (!value) return null
  const [year, month, day] = String(value).split('-').map(Number)
  if (!year || !month || !day) return null
  return new Date(year, month - 1, day)
}

function addDays(date, days) {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function endOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0)
}

function createPresetRange(key) {
  const today = new Date()
  if (key === 'today') return { from: formatDateInput(today), to: formatDateInput(today) }
  if (key === 'yesterday') {
    const yesterday = addDays(today, -1)
    return { from: formatDateInput(yesterday), to: formatDateInput(yesterday) }
  }
  if (key === 'last7') return { from: formatDateInput(addDays(today, -6)), to: formatDateInput(today) }
  if (key === 'thisMonth') return { from: formatDateInput(startOfMonth(today)), to: formatDateInput(today) }
  if (key === 'lastMonth') {
    const lastMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1)
    return { from: formatDateInput(startOfMonth(lastMonth)), to: formatDateInput(endOfMonth(lastMonth)) }
  }
  if (key === 'yearToDate') return { from: `${today.getFullYear()}-01-01`, to: formatDateInput(today) }
  return { from: formatDateInput(addDays(today, -29)), to: formatDateInput(today) }
}

function createDefaultFilters() {
  const range = createPresetRange('last30')
  return {
    style: 'all',
    country: 'all',
    dateFrom: range.from,
    dateTo: range.to,
  }
}

const datePresets = [
  { key: 'today', label: '今天' },
  { key: 'yesterday', label: '昨天' },
  { key: 'last7', label: '近 7 天' },
  { key: 'last30', label: '近 30 天' },
  { key: 'thisMonth', label: '本月' },
  { key: 'lastMonth', label: '上月' },
  { key: 'yearToDate', label: '本年至今' },
]

const filters = reactive(createDefaultFilters())
const draftDates = reactive({ from: filters.dateFrom, to: filters.dateTo })

const styleOptions = computed(() => admin.dashboard?.filters?.styles || [])
const countryOptions = computed(() => admin.dashboard?.filters?.countries || [])
const trendPoints = computed(() => admin.dashboard?.trend?.points || [])
const recentOrders = computed(() => admin.dashboard?.recentOrders || [])
const styleSummary = computed(() => admin.dashboard?.styleSummary || [])
const topStyleSummary = computed(() => styleSummary.value.slice(0, 12))
const trendSummary = computed(() => admin.dashboard?.trend?.summary || { orderCount: 0, itemCount: 0, totalAmount: 0, dateFrom: '', dateTo: '', maxOrderCount: 0 })
const trendMax = computed(() => Math.max(1, Number(trendSummary.value.maxOrderCount || 0)))
const styleMax = computed(() => Math.max(1, ...styleSummary.value.map((item) => Number(item.quantity || 0))))
const dateRangeText = computed(() => `${filters.dateFrom || '开始'} 至 ${filters.dateTo || '结束'}`)

const chartPoints = computed(() => {
  const points = trendPoints.value
  if (!points.length) return []
  const width = 848
  const height = 260
  const left = 52
  const top = 28
  const xStep = points.length <= 1 ? 0 : width / (points.length - 1)
  return points.map((point, index) => ({
    ...point,
    x: Number((left + index * xStep).toFixed(2)),
    y: Number((top + height - (Number(point.orderCount || 0) / trendMax.value) * height).toFixed(2)),
  }))
})

const chartPolyline = computed(() => chartPoints.value.map((point) => `${point.x},${point.y}`).join(' '))
const chartGuides = computed(() => {
  const top = 28
  const middle = 158
  const bottom = 288
  return [
    { y: top, label: trendMax.value },
    { y: middle, label: Math.round(trendMax.value / 2) },
    { y: bottom, label: 0 },
  ]
})

const calendarMonths = computed(() => {
  const end = parseDate(draftDates.to) || new Date()
  const currentMonth = new Date(end.getFullYear(), end.getMonth(), 1)
  const previousMonth = new Date(end.getFullYear(), end.getMonth() - 1, 1)
  return [previousMonth, currentMonth].map((monthDate) => {
    const year = monthDate.getFullYear()
    const month = monthDate.getMonth()
    const lastDay = new Date(year, month + 1, 0).getDate()
    return {
      title: `${year}-${pad(month + 1)}`,
      leading: new Date(year, month, 1).getDay(),
      days: Array.from({ length: lastDay }, (_, index) => {
        const date = new Date(year, month, index + 1)
        return { label: index + 1, value: formatDateInput(date) }
      }),
    }
  })
})

function formatAmount(value) {
  return Number(value || 0).toFixed(2)
}

function styleBarPercent(value) {
  return Math.max(4, Math.round((Number(value || 0) / styleMax.value) * 100))
}

function applyPreset(key) {
  activePreset.value = key
  const range = createPresetRange(key)
  draftDates.from = range.from
  draftDates.to = range.to
}

function isInDraftRange(value) {
  const date = parseDate(value)
  const from = parseDate(draftDates.from)
  const to = parseDate(draftDates.to)
  if (!date || !from || !to) return false
  return date >= from && date <= to
}

function isDraftEdge(value) {
  return value === draftDates.from || value === draftDates.to
}

function pickCalendarDate(value) {
  activePreset.value = 'custom'
  if (selectingStart.value) {
    draftDates.from = value
    if (parseDate(draftDates.to) && parseDate(value) > parseDate(draftDates.to)) {
      draftDates.to = value
    }
  } else {
    draftDates.to = value
    if (parseDate(draftDates.from) && parseDate(value) < parseDate(draftDates.from)) {
      draftDates.from = value
    }
  }
  selectingStart.value = !selectingStart.value
}

async function confirmDateRange() {
  filters.dateFrom = draftDates.from
  filters.dateTo = draftDates.to
  datePanelOpen.value = false
  await applyFilters()
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
  draftDates.from = filters.dateFrom
  draftDates.to = filters.dateTo
  activePreset.value = 'last30'
  await applyFilters()
}

onMounted(() => {
  applyFilters()
})
</script>

<style scoped>
.dashboard-page { gap: 18px; }
.dashboard-toolbar { display: grid; grid-template-columns: minmax(190px, 1fr) minmax(170px, 0.8fr) minmax(260px, 1.2fr) auto auto; gap: 14px; align-items: end; overflow: visible; }
.date-range-field { position: relative; }
.date-range-trigger { display: flex; align-items: center; justify-content: space-between; gap: 12px; text-align: left; color: var(--text); cursor: pointer; }
.date-range-caret { color: var(--muted); }
.date-range-panel { position: absolute; top: calc(100% + 8px); right: 0; z-index: 50; width: min(760px, calc(100vw - 48px)); padding: 16px; display: grid; grid-template-columns: 118px 1fr; gap: 16px; background: #fff; border: 1px solid var(--line); border-radius: 20px; box-shadow: 0 22px 48px rgba(90, 68, 51, 0.18); }
.date-range-main { display: grid; gap: 14px; }
.quick-ranges { display: grid; align-content: start; gap: 8px; }
.quick-range-btn { min-height: 34px; border: 0; border-radius: 12px; background: #f7f1eb; color: var(--text); cursor: pointer; }
.quick-range-btn.active, .quick-range-btn:hover { background: #b36e48; color: #fff; }
.date-range-editors { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.date-range-editors label { display: grid; gap: 6px; color: var(--muted); font-size: 0.9rem; }
.calendar-preview { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.calendar-month { display: grid; gap: 10px; }
.calendar-month strong { text-align: center; }
.calendar-weekdays, .calendar-days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 5px; text-align: center; }
.calendar-weekdays { color: var(--muted); font-size: 0.78rem; }
.calendar-day { min-height: 30px; border: 0; border-radius: 10px; background: transparent; cursor: pointer; }
.calendar-day.inRange { background: #f4dfcf; }
.calendar-day.edge { background: #b36e48; color: #fff; }
.date-panel-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 10px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.metric-card { display: grid; gap: 8px; padding: 18px 20px; border-radius: 20px; border: 1px solid var(--line); background: rgba(255, 255, 255, 0.88); box-shadow: 0 12px 28px rgba(90, 68, 51, 0.08); }
.metric-card span { color: var(--muted); }
.metric-card strong { font-size: 2rem; color: var(--accent); }
.chart-card { display: grid; gap: 16px; }
.chart-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.chart-head h3 { margin: 0; }
.chart-legend { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-size: 0.9rem; }
.chart-legend span { width: 28px; height: 4px; border-radius: 999px; background: #b36e48; }
.line-chart-wrap { display: grid; gap: 8px; }
.line-chart { width: 100%; height: 320px; background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(250,245,239,0.64)); border: 1px solid rgba(110, 85, 61, 0.08); border-radius: 18px; }
.chart-guide { stroke: rgba(110, 85, 61, 0.16); stroke-dasharray: 5 7; }
.axis-label { fill: #7a6659; font-size: 12px; }
.chart-area-line { fill: none; stroke: #b36e48; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
.chart-dot { fill: #b36e48; stroke: #fff; stroke-width: 2; }
.chart-x-labels { display: flex; justify-content: space-between; color: var(--muted); font-size: 0.85rem; }
.style-bars { display: grid; gap: 12px; }
.style-bar-row { display: grid; grid-template-columns: minmax(120px, 190px) 1fr 72px; gap: 12px; align-items: center; }
.style-bar-name { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.style-bar-track { height: 18px; overflow: hidden; border-radius: 999px; background: #f1e5dc; }
.style-bar-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, #d39a71, #b36e48); }
.style-bar-value { color: var(--muted); text-align: right; font-weight: 700; }
@media (max-width: 1080px) { .dashboard-toolbar, .metric-grid, .date-range-editors, .calendar-preview { grid-template-columns: 1fr; } .date-range-panel { left: 0; right: auto; grid-template-columns: 1fr; } .style-bar-row { grid-template-columns: 1fr; } .style-bar-value { text-align: left; } }
</style>
