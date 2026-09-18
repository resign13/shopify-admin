<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card inventory-card">
        <header class="inventory-page-head">
          <div>
            <p class="inventory-kicker">INVENTORY CONTROL</p>
            <h1>库存管理</h1>
            <p class="small-note">按颜色 SKU 管理各真实尺码库存，合同未送独立登记。</p>
          </div>
          <div v-if="canManageInventory" class="inventory-head-actions">
            <button class="admin-button ghost" type="button" :disabled="exporting" @click="exportInventory">
              {{ exporting ? '导出中...' : '导出库存' }}
            </button>
            <button class="admin-button" type="button" :disabled="previewLoading" @click="openImportPicker">
              {{ previewLoading ? '读取中...' : '导入库存' }}
            </button>
            <input
              ref="importInput"
              class="visually-hidden"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              @change="handleImportFile"
            />
          </div>
        </header>

        <form class="filter-row" @submit.prevent="applyFilters">
          <label class="field-label">
            <span>商品分类</span>
            <select v-model="selectedCategoryDraft" class="admin-field">
              <option value="">全部分类</option>
              <option v-for="category in filterCategories" :key="category.key" :value="category.key">
                {{ category.labels?.zh || category.label || category.key }}
              </option>
            </select>
          </label>
          <label class="field-label search-field">
            <span>搜索</span>
            <input v-model.trim="keywordDraft" class="admin-field" placeholder="输入商品名、SKU、商品编码或颜色" />
          </label>
          <div class="filter-actions">
            <button class="admin-button ghost" type="submit">查询</button>
          </div>
        </form>

        <div class="inventory-summary-grid">
          <div class="inventory-summary-card">
            <span>颜色 SKU 数</span>
            <strong>{{ inventoryRows.length }}</strong>
          </div>
          <div class="inventory-summary-card">
            <span>当前总库存</span>
            <strong>{{ totalStock }}</strong>
          </div>
          <div v-if="showContractPending" class="inventory-summary-card">
            <span>合同未送合计</span>
            <strong>{{ totalContractPending }}</strong>
          </div>
          <div class="inventory-summary-card compact-summary">
            <span>尺码种类</span>
            <strong>{{ visibleSizeCount }}</strong>
          </div>
        </div>

        <p v-if="error" class="admin-error inventory-message">{{ error }}</p>
        <p v-else-if="saveMessage" class="inventory-success inventory-message">{{ saveMessage }}</p>
        <div v-if="loading" class="small-note inventory-loading">库存数据加载中...</div>
        <div v-else-if="!inventoryRows.length" class="empty-state">暂无符合条件的库存数据。</div>

        <div v-else class="inventory-table-wrap">
          <table class="inventory-table">
            <colgroup>
              <col class="product-column" />
              <col class="size-column" />
              <col class="total-column" />
              <col v-if="showContractPending" class="pending-column" />
              <col v-if="canEditInventory" class="action-column" />
            </colgroup>
            <thead>
              <tr>
                <th>商品信息</th>
                <th>尺码 / 库存 / 合同未送</th>
                <th>当前库存</th>
                <th v-if="showContractPending">合同未送</th>
                <th v-if="canEditInventory">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in inventoryRows" :key="item.id">
                <td class="product-cell">
                  <div class="product-info">
                    <div class="inventory-thumb" :class="{ empty: !item.image }">
                      <ProductImage v-if="item.image" :src="item.image" :alt="displayName(item)" />
                      <span v-else>暂无图片</span>
                    </div>
                    <div class="product-copy">
                      <strong class="product-title" :title="displayName(item)">{{ truncatedTitle(item) }}</strong>
                      <span class="product-sku">{{ item.sku || item.productCode || '--' }}</span>
                      <span class="product-meta">{{ item.colorName || '未设置颜色' }} · {{ categoryLabel(item) }}</span>
                    </div>
                  </div>
                </td>
                <td class="size-cell">
                  <div class="size-grid">
                    <div v-for="size in item.sizeRows" :key="`${item.id}-${size}`" class="size-card">
                      <strong class="size-label">{{ size }}</strong>
                      <div class="size-metric">
                        <span>库存</span>
                        <b :class="{ muted: readSizeStock(item, size) === 0 }">{{ readSizeStock(item, size) }}</b>
                      </div>
                      <div v-if="showContractPending" class="size-metric pending-metric">
                        <span>未送</span>
                        <b :class="{ muted: readContractPending(item, size) === 0 }">
                          {{ readContractPending(item, size) }}
                        </b>
                      </div>
                    </div>
                  </div>
                </td>
                <td class="total-stock-cell">
                  <span>库存合计</span>
                  <strong>{{ displayTotalStock(item) }}</strong>
                </td>
                <td v-if="showContractPending" class="total-stock-cell pending-total-cell">
                  <span>未送合计</span>
                  <strong>{{ displayContractPending(item) }}</strong>
                </td>
                <td v-if="canEditInventory" class="actions-cell">
                  <div v-if="isEditing(item.id)" class="editing-state">正在编辑</div>
                  <button
                    v-else
                    class="admin-button ghost compact-button"
                    type="button"
                    :disabled="Boolean(editingItem)"
                    @click="startEdit(item)"
                  >
                    修改库存
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div v-if="editingItem" class="inventory-drawer-backdrop" @click.self="cancelEdit">
      <aside class="inventory-drawer" role="dialog" aria-modal="true" aria-labelledby="inventory-drawer-title">
        <div class="drawer-head">
          <div>
            <p class="inventory-kicker">EDIT STOCK</p>
            <h2 id="inventory-drawer-title">修改库存</h2>
            <p class="small-note">{{ truncatedTitle(editingItem, 48) }} · {{ editingItem.sku || editingItem.productCode }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" title="关闭" @click="cancelEdit">×</button>
        </div>
        <div class="drawer-size-list">
          <div v-for="size in editingItem.sizeRows" :key="`edit-${editingItem.id}-${size}`" class="drawer-size-row">
            <strong>{{ size }}</strong>
            <label>
              <span>当前库存</span>
              <input v-model="draftStocks[String(editingItem.id)].stocks[size]" class="admin-field" type="number" min="0" step="1" />
            </label>
            <label v-if="showContractPending">
              <span>合同未送</span>
              <input v-model="draftStocks[String(editingItem.id)].pending[size]" class="admin-field" type="number" min="0" step="1" />
            </label>
          </div>
        </div>
        <div class="drawer-total-row">
          <span>库存合计</span><strong>{{ displayTotalStock(editingItem) }}</strong>
          <template v-if="showContractPending">
            <span>未送合计</span><strong>{{ displayContractPending(editingItem) }}</strong>
          </template>
        </div>
        <div class="drawer-actions">
          <button class="admin-button ghost" type="button" :disabled="savingId === editingItem.id" @click="cancelEdit">取消</button>
          <button class="admin-button" type="button" :disabled="savingId === editingItem.id" @click="saveRow(editingItem)">
            {{ savingId === editingItem.id ? '保存中...' : '保存修改' }}
          </button>
        </div>
      </aside>
    </div>

    <div v-if="previewOpen" class="inventory-drawer-backdrop" @click.self="closePreview">
      <section class="inventory-import-modal" role="dialog" aria-modal="true" aria-labelledby="inventory-import-title">
        <div class="drawer-head">
          <div>
            <p class="inventory-kicker">IMPORT PREVIEW</p>
            <h2 id="inventory-import-title">导入库存预览</h2>
            <p class="small-note">{{ importFile?.name || '库存文件' }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" title="关闭" @click="closePreview">×</button>
        </div>
        <p v-if="previewError" class="admin-error inventory-message">{{ previewError }}</p>
        <template v-if="previewData">
          <div class="import-summary-grid">
            <span>数据行 <b>{{ previewData.summary.rowCount }}</b></span>
            <span>商品数 <b>{{ previewData.summary.productCount }}</b></span>
            <span>待修改行 <b>{{ previewData.summary.changedRowCount }}</b></span>
            <span>待修改字段 <b>{{ previewData.summary.changedFieldCount }}</b></span>
          </div>
          <div v-if="previewData.errors?.length" class="import-errors">
            <strong>请先修正以下行：</strong>
            <p v-for="item in previewData.errors.slice(0, 12)" :key="`${item.row}-${item.message}`">第 {{ item.row }} 行：{{ item.message }}</p>
            <p v-if="previewData.errors.length > 12">另有 {{ previewData.errors.length - 12 }} 行错误未展开。</p>
          </div>
          <div v-else class="import-preview-table-wrap">
            <table class="import-preview-table">
              <thead><tr><th>商品 / SKU</th><th>尺码</th><th>库存</th><th>合同未送</th></tr></thead>
              <tbody>
                <tr v-for="row in previewData.rows.slice(0, 80)" :key="`${row.productId}-${row.sizeCode}`">
                  <td>{{ row.title }}<small>{{ row.sku }}</small></td>
                  <td>{{ row.sizeCode }}</td>
                  <td :class="{ changed: row.stockChanged }">{{ row.originalStock }} → {{ row.stock }}</td>
                  <td :class="{ changed: row.contractPendingChanged }">{{ row.originalContractPending }} → {{ row.contractPending }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="previewData.rows.length > 80" class="small-note">仅展示前 80 行，确认后将处理全部 {{ previewData.rows.length }} 行。</p>
          </div>
        </template>
        <div class="drawer-actions">
          <button class="admin-button ghost" type="button" :disabled="importing" @click="closePreview">取消</button>
          <button
            class="admin-button"
            type="button"
            :disabled="importing || !previewData || previewData.errors?.length"
            @click="confirmImport"
          >
            {{ importing ? '导入中...' : '确认导入' }}
          </button>
        </div>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import ProductImage from '../components/ProductImage.vue'
import { computed, onMounted, ref } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminAuthStore } from '../stores/auth'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const auth = useAdminAuthStore()
const selectedCategoryDraft = ref('')
const selectedCategory = ref('')
const keywordDraft = ref('')
const keyword = ref('')
const loading = ref(false)
const error = ref('')
const saveMessage = ref('')
const editingId = ref(0)
const savingId = ref(0)
const draftStocks = ref({})
const exporting = ref(false)
const importInput = ref(null)
const importFile = ref(null)
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewData = ref(null)
const previewError = ref('')
const importing = ref(false)

const canEditInventory = computed(() => ['admin', 'sales', 'warehouse'].includes(auth.userRole))
const canManageInventory = computed(() => canEditInventory.value)
const showContractPending = computed(() => auth.userRole !== 'customer')
const editingItem = computed(() => inventoryRows.value.find((item) => Number(item.id) === Number(editingId.value)) || null)

const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '28', '30', '32', '34', '36', '38']

function normalizeSizeCode(value) {
  return String(value || '').trim()
}

function sizeRank(value) {
  const normalized = normalizeSizeCode(value).toUpperCase()
  const base = normalized.split('/')[0]
  const index = SIZE_ORDER.indexOf(normalized)
  const baseIndex = SIZE_ORDER.indexOf(base)
  if (index >= 0) return index
  if (baseIndex >= 0) return baseIndex
  return 1000
}

function sortSizes(values) {
  return [...values].sort((left, right) => {
    const rankDiff = sizeRank(left) - sizeRank(right)
    if (rankDiff) return rankDiff
    return String(left).localeCompare(String(right), 'en', { numeric: true })
  })
}

const inventoryRows = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return (admin.inventoryItems || [])
    .filter((item) => {
      if (selectedCategory.value && item.categoryKey !== selectedCategory.value) return false
      if (!normalizedKeyword) return true
      const names = item.name && typeof item.name === 'object' ? Object.values(item.name) : [item.name]
      const haystack = [displayName(item), ...names, item.sku, item.productCode, item.colorName, categoryLabel(item)]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(normalizedKeyword)
    })
    .map((item) => {
      const stocks = {}
      const pending = {}
      for (const row of item.sizePrices || []) {
        const size = normalizeSizeCode(row?.sizeCode)
        if (!size) continue
        stocks[size] = Number(row.stock || 0)
        pending[size] = Number(row.contractPending || 0)
      }
      const sizeRows = sortSizes(
        Array.from(new Set([...(item.sizes || []), ...Object.keys(stocks)].map(normalizeSizeCode).filter(Boolean)))
      )
      const summedStock = Object.values(stocks).reduce((total, value) => total + Number(value || 0), 0)
      const summedPending = Object.values(pending).reduce((total, value) => total + Number(value || 0), 0)
      return {
        ...item,
        sizeRows,
        sizeStockMap: stocks,
        contractPendingMap: pending,
        totalStock: Number(item.stock ?? summedStock),
        totalContractPending: summedPending,
      }
    })
    .sort((left, right) => String(left.sku || left.productCode || '').localeCompare(String(right.sku || right.productCode || ''), 'zh-Hans-CN', { numeric: true }))
})

const visibleSizeCount = computed(() => new Set(inventoryRows.value.flatMap((item) => item.sizeRows || [])).size)
const filterCategories = computed(() => {
  if (Array.isArray(admin.categories) && admin.categories.length) return admin.categories
  const mapped = new Map()
  for (const item of admin.inventoryItems || []) {
    if (item.categoryKey && !mapped.has(item.categoryKey)) {
      mapped.set(item.categoryKey, { key: item.categoryKey, label: item.categoryLabel || item.categoryKey })
    }
  }
  return Array.from(mapped.values())
})
const totalStock = computed(() => inventoryRows.value.reduce((total, item) => total + Number(displayTotalStock(item) || 0), 0))
const totalContractPending = computed(() => inventoryRows.value.reduce((total, item) => total + Number(displayContractPending(item) || 0), 0))

function displayName(item) {
  if (item?.name && typeof item.name === 'object') return item.name.zh || item.name.en || Object.values(item.name).find(Boolean) || item.productCode || item.sku || '未命名商品'
  return item?.name || item?.productCode || item?.sku || '未命名商品'
}

function truncatedTitle(item, limit = 32) {
  const value = typeof item === 'string' ? item : displayName(item)
  const chars = Array.from(String(value || ''))
  return chars.length > limit ? `${chars.slice(0, limit).join('')}...` : chars.join('')
}

function categoryLabel(item) {
  const matched = admin.categories.find((category) => category.key === item.categoryKey)
  return item.categoryLabel || matched?.labels?.zh || matched?.label || item.categoryKey || '--'
}

function readSizeStock(item, size) {
  if (isEditing(item.id)) return Number(draftStocks.value[String(item.id)]?.stocks?.[size] || 0)
  return Number(item.sizeStockMap?.[size] || 0)
}

function readContractPending(item, size) {
  if (isEditing(item.id)) return Number(draftStocks.value[String(item.id)]?.pending?.[size] || 0)
  return Number(item.contractPendingMap?.[size] || 0)
}

function displayTotalStock(item) {
  return (item.sizeRows || []).reduce((total, size) => total + readSizeStock(item, size), 0)
}

function displayContractPending(item) {
  return showContractPending.value
    ? (item.sizeRows || []).reduce((total, size) => total + readContractPending(item, size), 0)
    : 0
}

function isEditing(productId) {
  return Number(editingId.value) === Number(productId)
}

function hasUnsavedChanges() {
  const item = editingItem.value
  if (!item) return false
  const draft = draftStocks.value[String(item.id)] || { stocks: {}, pending: {} }
  return item.sizeRows.some((size) =>
    String(draft.stocks[size] ?? '') !== String(item.sizeStockMap?.[size] ?? 0)
    || (showContractPending.value && String(draft.pending[size] ?? '') !== String(item.contractPendingMap?.[size] ?? 0))
  )
}

function startEdit(item) {
  if (!canEditInventory.value) return
  if (editingItem.value && !isEditing(item.id) && hasUnsavedChanges() && !window.confirm('当前修改尚未保存，确定切换吗？')) return
  error.value = ''
  saveMessage.value = ''
  editingId.value = Number(item.id)
  draftStocks.value[String(item.id)] = {
    stocks: Object.fromEntries(item.sizeRows.map((size) => [size, String(item.sizeStockMap?.[size] ?? 0)])),
    pending: Object.fromEntries(item.sizeRows.map((size) => [size, String(item.contractPendingMap?.[size] ?? 0)])),
  }
}

function cancelEdit() {
  if (savingId.value) return
  if (hasUnsavedChanges() && !window.confirm('当前修改尚未保存，确定取消吗？')) return
  if (editingId.value) delete draftStocks.value[String(editingId.value)]
  editingId.value = 0
}

function toSafeInteger(value, label) {
  const raw = String(value ?? '').trim()
  if (!/^\d+$/.test(raw)) throw new Error(`${label}必须是大于等于 0 的整数`)
  return Number(raw)
}

async function saveRow(item) {
  if (!canEditInventory.value) return
  const draft = draftStocks.value[String(item.id)] || { stocks: {}, pending: {} }
  const stocks = {}
  const pending = {}
  try {
    for (const size of item.sizeRows) {
      stocks[size] = toSafeInteger(draft.stocks[size], `${item.sku || item.productCode} / ${size} 库存`)
      if (showContractPending.value) pending[size] = toSafeInteger(draft.pending[size], `${item.sku || item.productCode} / ${size} 合同未送`)
    }
  } catch (validationError) {
    error.value = validationError.message
    return
  }
  savingId.value = Number(item.id)
  error.value = ''
  saveMessage.value = ''
  try {
    await admin.saveInventory(item.id, stocks, pending)
    saveMessage.value = `${item.sku || item.productCode} 库存已更新`
    if (editingId.value) delete draftStocks.value[String(editingId.value)]
    editingId.value = 0
  } catch (saveError) {
    error.value = saveError.message || '库存保存失败'
  } finally {
    savingId.value = 0
  }
}

function applyFilters() {
  if (hasUnsavedChanges() && !window.confirm('当前修改尚未保存，确定应用筛选吗？')) return
  selectedCategory.value = selectedCategoryDraft.value
  keyword.value = keywordDraft.value.trim()
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function exportInventory() {
  exporting.value = true
  error.value = ''
  try {
    const blob = await admin.exportInventory({ category: selectedCategory.value, keyword: keyword.value })
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
    downloadBlob(blob, `inventory_export_${timestamp}.xlsx`)
    saveMessage.value = '库存文件已导出'
  } catch (exportError) {
    error.value = exportError.message || '库存导出失败'
  } finally {
    exporting.value = false
  }
}

function openImportPicker() {
  importInput.value?.click()
}

async function handleImportFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  importFile.value = file
  previewOpen.value = true
  previewLoading.value = true
  previewData.value = null
  previewError.value = ''
  try {
    previewData.value = await admin.previewInventoryImport(file)
  } catch (previewRequestError) {
    previewError.value = previewRequestError.message || '库存导入预览失败'
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  if (importing.value) return
  previewOpen.value = false
  importFile.value = null
  previewData.value = null
  previewError.value = ''
}

async function confirmImport() {
  if (!importFile.value || !previewData.value || previewData.value.errors?.length) return
  importing.value = true
  previewError.value = ''
  try {
    const result = await admin.confirmInventoryImport(importFile.value, previewData.value.fileHash)
    saveMessage.value = `${result.updatedProducts} 个商品、${result.updatedRows} 行库存已更新`
    closePreview()
  } catch (importError) {
    previewError.value = importError.message || '库存导入失败，请重新预览'
  } finally {
    importing.value = false
  }
}

async function loadPage() {
  loading.value = true
  error.value = ''
  try {
    await admin.loadInventory()
    if (!auth.isCustomer) await admin.loadCategories()
  } catch (loadError) {
    error.value = loadError.message || '库存数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadPage)
</script>

<style scoped>
.inventory-card { min-width: 0; overflow: hidden; }
.inventory-page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; margin-bottom: 20px; }
.inventory-page-head h1 { margin: 0 0 6px; }
.inventory-kicker { margin: 0 0 6px; color: var(--accent); font-size: 0.76rem; font-weight: 700; letter-spacing: 0.12em; }
.inventory-head-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.filter-row { display: grid; grid-template-columns: minmax(190px, 250px) minmax(0, 1fr) auto; gap: 14px; margin-bottom: 18px; align-items: end; }
.field-label { display: grid; gap: 8px; color: var(--muted); font-size: 0.9rem; }
.search-field { min-width: 0; }
.filter-actions { display: flex; align-items: end; }
.inventory-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.inventory-summary-card { display: grid; gap: 7px; min-width: 0; padding: 14px 16px; border: 1px solid var(--line); border-radius: 16px; background: rgba(255, 255, 255, 0.78); }
.inventory-summary-card span { color: var(--muted); font-size: 0.86rem; }
.inventory-summary-card strong { overflow: hidden; color: var(--accent); font-size: 1.65rem; text-overflow: ellipsis; }
.compact-summary { background: rgba(255, 255, 255, 0.56); }
.inventory-message { margin: 0 0 14px; }
.inventory-success { color: #2d7b46; }
.inventory-loading { padding: 20px 0; }
.inventory-table-wrap { width: 100%; overflow: hidden; border: 1px solid var(--line); border-radius: 16px; background: rgba(255, 255, 255, 0.74); }
.inventory-table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.inventory-table th, .inventory-table td { padding: 12px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
.inventory-table th { background: #f6ede4; color: var(--text); font-size: 0.86rem; text-align: center; }
.inventory-table tbody tr:last-child td { border-bottom: 0; }
.inventory-table tbody tr:hover { background: rgba(255, 255, 255, 0.74); }
.product-column { width: 27%; }
.size-column { width: 47%; }
.total-column { width: 10%; }
.pending-column { width: 10%; }
.action-column { width: 112px; }
.product-cell { min-width: 0; }
.product-info { display: flex; align-items: center; gap: 10px; min-width: 0; }
.inventory-thumb { width: 58px; height: 58px; flex: 0 0 58px; display: grid; place-items: center; overflow: hidden; border-radius: 12px; background: #f3ebe4; color: var(--muted); font-size: 0.72rem; text-align: center; }
.inventory-thumb img { width: 100%; height: 100%; object-fit: cover; }
.inventory-thumb.empty { border: 1px dashed var(--line); }
.product-copy { display: grid; min-width: 0; gap: 4px; }
.product-title { display: block; overflow: hidden; color: var(--text); line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.product-sku, .product-meta { overflow: hidden; color: var(--muted); font-size: 0.82rem; text-overflow: ellipsis; white-space: nowrap; }
.product-sku { color: var(--text); font-weight: 600; }
.size-cell { min-width: 0; }
.size-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(74px, 1fr)); gap: 7px; min-width: 0; }
.size-card { min-width: 0; padding: 7px 6px; border: 1px solid var(--line); border-radius: 10px; background: rgba(250, 247, 243, 0.72); }
.size-label { display: block; margin-bottom: 5px; overflow: hidden; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.size-metric { display: flex; align-items: baseline; justify-content: space-between; gap: 4px; color: var(--muted); font-size: 0.7rem; }
.size-metric b { color: var(--text); font-size: 0.86rem; }
.size-metric b.muted { color: #ad9e92; }
.pending-metric { margin-top: 2px; }
.pending-metric b { color: var(--accent); }
.total-stock-cell { text-align: center !important; }
.total-stock-cell span { display: block; color: var(--muted); font-size: 0.74rem; }
.total-stock-cell strong { display: block; margin-top: 5px; color: var(--accent); font-size: 1.1rem; }
.pending-total-cell strong { color: #8f5d3f; }
.actions-cell { text-align: center !important; }
.compact-button { min-height: 38px; padding: 0 10px; font-size: 0.8rem; }
.editing-state { color: var(--accent); font-size: 0.82rem; }
.empty-state { padding: 36px 0 20px; color: var(--muted); text-align: center; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
.icon-button { width: 36px; height: 36px; flex: 0 0 36px; border: 1px solid var(--line); border-radius: 50%; background: white; color: var(--text); font-size: 1.35rem; line-height: 1; cursor: pointer; }
.inventory-drawer-backdrop { position: fixed; inset: 0; z-index: 200; display: flex; justify-content: flex-end; background: rgba(46, 33, 24, 0.26); }
.inventory-drawer, .inventory-import-modal { width: min(520px, 100%); height: 100%; overflow-y: auto; padding: 26px; background: #fffdfa; box-shadow: -12px 0 32px rgba(46, 33, 24, 0.16); }
.inventory-import-modal { width: min(780px, 100%); height: auto; max-height: 92vh; align-self: center; margin: 18px; border-radius: 18px; box-shadow: 0 18px 42px rgba(46, 33, 24, 0.2); }
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 20px; }
.drawer-head h2 { margin: 0 0 5px; }
.drawer-size-list { display: grid; gap: 10px; }
.drawer-size-row { display: grid; grid-template-columns: 70px minmax(0, 1fr) minmax(0, 1fr); gap: 10px; align-items: end; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: rgba(250, 247, 243, 0.68); }
.drawer-size-row > strong { align-self: center; }
.drawer-size-row label { display: grid; gap: 5px; color: var(--muted); font-size: 0.76rem; }
.drawer-size-row .admin-field { min-height: 40px; padding: 0 9px; border-radius: 10px; }
.drawer-total-row { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; margin-top: 16px; padding: 13px 0; border-top: 1px solid var(--line); color: var(--muted); }
.drawer-total-row strong { color: var(--accent); font-size: 1.1rem; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.import-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
.import-summary-grid span { padding: 10px; border: 1px solid var(--line); border-radius: 10px; color: var(--muted); font-size: 0.78rem; }
.import-summary-grid b { display: block; margin-top: 4px; color: var(--accent); font-size: 1.15rem; }
.import-errors { padding: 13px; border: 1px solid rgba(167, 63, 53, 0.2); border-radius: 12px; background: #fff4f2; color: #a73f35; }
.import-errors p { margin: 6px 0 0; font-size: 0.84rem; }
.import-preview-table-wrap { max-height: 440px; overflow: auto; border: 1px solid var(--line); border-radius: 12px; }
.import-preview-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.import-preview-table th, .import-preview-table td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; }
.import-preview-table th { position: sticky; top: 0; background: #f6ede4; }
.import-preview-table td small { display: block; margin-top: 3px; color: var(--muted); }
.import-preview-table td.changed { color: var(--accent); font-weight: 700; }

@media (max-width: 1080px) {
  .filter-row { grid-template-columns: minmax(180px, 240px) minmax(0, 1fr); }
  .filter-actions { grid-column: 1 / -1; justify-content: flex-end; }
  .inventory-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .product-column { width: 29%; }
  .size-column { width: 43%; }
  .action-column { width: 98px; }
}

@media (max-width: 720px) {
  .inventory-page-head { flex-direction: column; }
  .inventory-head-actions { width: 100%; justify-content: stretch; }
  .inventory-head-actions .admin-button { flex: 1; }
  .filter-row { grid-template-columns: 1fr; }
  .filter-actions { grid-column: auto; justify-content: stretch; }
  .filter-actions .admin-button { width: 100%; }
  .inventory-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .inventory-table-wrap { border: 0; background: transparent; overflow: visible; }
  .inventory-table, .inventory-table tbody, .inventory-table tr, .inventory-table td { display: block; width: 100%; }
  .inventory-table thead { display: none; }
  .inventory-table tbody { display: grid; gap: 12px; }
  .inventory-table tbody tr { display: grid; grid-template-columns: minmax(0, 1fr) minmax(84px, 0.34fr); border: 1px solid var(--line); border-radius: 14px; background: rgba(255, 255, 255, 0.78); overflow: hidden; }
  .inventory-table tbody tr:hover { background: rgba(255, 255, 255, 0.78); }
  .inventory-table td { padding: 12px; border-bottom: 1px solid var(--line); }
  .inventory-table td:last-child { border-bottom: 0; }
  .product-cell, .size-cell { grid-column: 1 / -1; }
  .product-cell { padding-bottom: 8px !important; }
  .size-cell { padding-top: 5px !important; }
  .size-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .total-stock-cell, .actions-cell { grid-column: span 1; }
  .actions-cell { display: grid !important; place-items: center; }
  .compact-button { width: 100%; }
  .drawer-size-row { grid-template-columns: 54px minmax(0, 1fr) minmax(0, 1fr); }
  .inventory-drawer, .inventory-import-modal { padding: 20px 16px; }
  .inventory-import-modal { margin: 8px; max-height: calc(100vh - 16px); }
  .import-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 390px) {
  .inventory-summary-grid { gap: 8px; }
  .inventory-summary-card { padding: 11px; }
  .inventory-summary-card strong { font-size: 1.35rem; }
  .inventory-thumb { width: 50px; height: 50px; flex-basis: 50px; }
  .product-title { font-size: 0.9rem; }
  .drawer-size-row { grid-template-columns: 44px minmax(0, 1fr) minmax(0, 1fr); gap: 6px; padding: 9px 7px; }
}
</style>
