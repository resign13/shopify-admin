<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card">
        <div class="inventory-page-head">
          <div>
            <h1>库存管理</h1>
            <p class="small-note">
              在这里可以直接修改各颜色 SKU 的尺码库存，保存后会同步到商品管理和其他读取同一库存数据的页面。
            </p>
          </div>
        </div>

        <form class="filter-row" @submit.prevent="applyFilters">
          <label class="field-label">
            <span>商品分类</span>
            <select v-model="selectedCategoryDraft" class="admin-field">
              <option value="">全部分类</option>
              <option
                v-for="category in admin.categories"
                :key="category.key"
                :value="category.key"
              >
                {{ category.labels?.zh || category.label || category.key }}
              </option>
            </select>
          </label>

          <label class="field-label search-field">
            <span>搜索</span>
            <input
              v-model.trim="keywordDraft"
              class="admin-field"
              placeholder="输入商品名、SKU、商品编码或颜色"
            />
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
          <div class="inventory-summary-card">
            <span>当前尺码列</span>
            <strong>{{ visibleSizes.length }}</strong>
          </div>
        </div>

        <p v-if="error" class="admin-error">{{ error }}</p>
        <p v-else-if="saveMessage" class="inventory-success">{{ saveMessage }}</p>
        <div v-if="loading" class="small-note">库存数据加载中...</div>
        <div v-else-if="!inventoryRows.length" class="empty-state">暂无符合条件的库存数据。</div>

        <div v-else class="inventory-table-wrap">
          <table class="inventory-table">
            <thead>
              <tr>
                <th>颜色 SKU</th>
                <th>图片</th>
                <th>颜色</th>
                <th>分类</th>
                <th v-for="size in visibleSizes" :key="size">{{ size }}</th>
                <th>当前库存</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in inventoryRows" :key="item.id">
                <td class="sku-cell">
                  <strong>{{ item.sku || item.productCode || '--' }}</strong>
                  <p v-if="item.productCode && item.productCode !== item.sku">{{ item.productCode }}</p>
                </td>
                <td class="image-cell">
                  <div class="inventory-thumb" :class="{ empty: !item.image }">
                    <img v-if="item.image" :src="item.image" :alt="displayName(item)" />
                    <span v-else>暂无图片</span>
                  </div>
                </td>
                <td>{{ item.colorName || '未设置颜色' }}</td>
                <td>{{ categoryLabel(item) }}</td>
                <td v-for="size in visibleSizes" :key="`${item.id}-${size}`" class="stock-cell">
                  <template v-if="hasSize(item, size)">
                    <input
                      v-if="isEditing(item.id)"
                      v-model="draftStocks[String(item.id)][size]"
                      class="stock-input"
                      type="number"
                      min="0"
                      step="1"
                    />
                    <span
                      v-else
                      class="stock-chip"
                      :class="{ zero: readSizeStock(item, size) === 0 }"
                    >
                      {{ readSizeStock(item, size) }}
                    </span>
                  </template>
                  <span v-else class="stock-chip zero empty-chip">—</span>
                </td>
                <td class="total-stock-cell">
                  <strong>{{ displayTotalStock(item) }}</strong>
                </td>
                <td class="actions-cell">
                  <div v-if="isEditing(item.id)" class="row-actions">
                    <button
                      class="admin-button"
                      type="button"
                      :disabled="savingId === item.id"
                      @click="saveRow(item)"
                    >
                      {{ savingId === item.id ? '保存中...' : '保存' }}
                    </button>
                    <button
                      class="admin-button ghost"
                      type="button"
                      :disabled="savingId === item.id"
                      @click="cancelEdit()"
                    >
                      取消
                    </button>
                  </div>
                  <button
                    v-else
                    class="admin-button ghost"
                    type="button"
                    :disabled="savingId > 0"
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
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
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

const inventoryRows = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()

  return (admin.inventoryItems || [])
    .filter((item) => {
      const categoryMatch = !selectedCategory.value || item.categoryKey === selectedCategory.value
      if (!categoryMatch) return false
      if (!normalizedKeyword) return true

      const haystack = [
        displayName(item),
        item.name?.en,
        item.sku,
        item.productCode,
        item.colorName,
        categoryLabel(item),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()

      return haystack.includes(normalizedKeyword)
    })
    .map((item) => {
      const sizeStockMap = {}
      for (const row of item.sizePrices || []) {
        if (row?.sizeCode) {
          sizeStockMap[row.sizeCode] = Number(row.stock || 0)
        }
      }
      const rowSizes = Array.isArray(item.sizes) && item.sizes.length
        ? item.sizes
        : Object.keys(sizeStockMap)
      const summedStock = Object.values(sizeStockMap).reduce((total, value) => total + Number(value || 0), 0)
      return {
        ...item,
        rowSizes,
        sizeStockMap,
        totalStock: Number(item.stock ?? summedStock ?? 0),
      }
    })
    .sort((a, b) =>
      String(a.sku || a.productCode || '').localeCompare(String(b.sku || b.productCode || ''), 'zh-Hans-CN', {
        numeric: true,
      })
    )
})

const visibleSizes = computed(() => {
  const seen = new Set()
  const items = []
  for (const row of inventoryRows.value) {
    for (const size of row.rowSizes || []) {
      const normalized = String(size || '').trim()
      if (normalized && !seen.has(normalized)) {
        seen.add(normalized)
        items.push(normalized)
      }
    }
  }
  return items
})

const totalStock = computed(() =>
  inventoryRows.value.reduce((total, item) => total + Number(item.totalStock || 0), 0)
)

function displayName(item) {
  if (item?.name && typeof item.name === 'object') {
    return item.name.zh || item.name.en || Object.values(item.name).find(Boolean) || item.productCode || item.sku || '未命名商品'
  }
  return item?.name || item?.productCode || item?.sku || '未命名商品'
}

function categoryLabel(item) {
  const matched = admin.categories.find((category) => category.key === item.categoryKey)
  return item.categoryLabel || matched?.labels?.zh || matched?.label || item.categoryKey || '--'
}

function readSizeStock(item, size) {
  return Number(item.sizeStockMap?.[size] || 0)
}

function hasSize(item, size) {
  return (item.rowSizes || []).includes(size)
}

function isEditing(productId) {
  return Number(editingId.value) === Number(productId)
}

function startEdit(item) {
  error.value = ''
  saveMessage.value = ''
  editingId.value = Number(item.id)
  draftStocks.value[String(item.id)] = Object.fromEntries(
    (item.rowSizes || []).map((size) => [size, String(readSizeStock(item, size))])
  )
}

function cancelEdit() {
  if (editingId.value) {
    delete draftStocks.value[String(editingId.value)]
  }
  editingId.value = 0
}

function displayTotalStock(item) {
  if (!isEditing(item.id)) {
    return Number(item.totalStock || 0)
  }
  const draft = draftStocks.value[String(item.id)] || {}
  return (item.rowSizes || []).reduce((total, size) => total + toSafeInt(draft[size]), 0)
}

function toSafeInt(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  if (number < 0) return 0
  return Math.floor(number)
}

async function saveRow(item) {
  const productId = Number(item.id)
  const draft = draftStocks.value[String(productId)] || {}
  const payload = {}

  for (const size of item.rowSizes || []) {
    const rawValue = draft[size]
    const number = Number(rawValue)
    if (!Number.isFinite(number) || number < 0 || !Number.isInteger(number)) {
      error.value = `${item.sku || item.productCode} / ${size} 的库存必须是大于等于 0 的整数`
      return
    }
    payload[size] = number
  }

  savingId.value = productId
  error.value = ''
  saveMessage.value = ''
  try {
    await admin.saveInventory(productId, payload)
    saveMessage.value = `${item.sku || item.productCode} 库存已更新`
    cancelEdit()
  } catch (err) {
    error.value = err.message || '库存保存失败'
  } finally {
    savingId.value = 0
  }
}

function applyFilters() {
  selectedCategory.value = selectedCategoryDraft.value
  keyword.value = keywordDraft.value.trim()
}

async function loadPage() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([admin.loadInventory(), admin.loadCategories()])
  } catch (err) {
    error.value = err.message || '库存数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadPage)
</script>

<style scoped>
.inventory-page-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.inventory-page-head h1 {
  margin: 0 0 6px;
}

.filter-row {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) auto;
  gap: 14px;
  margin-bottom: 18px;
  align-items: end;
}

.field-label {
  display: grid;
  gap: 8px;
  color: var(--muted);
  font-size: 0.92rem;
}

.search-field {
  min-width: 0;
}

.filter-actions {
  display: flex;
  align-items: end;
}

.inventory-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.inventory-summary-card {
  display: grid;
  gap: 8px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.76);
}

.inventory-summary-card span {
  color: var(--muted);
  font-size: 0.92rem;
}

.inventory-summary-card strong {
  font-size: 1.8rem;
  color: var(--accent);
}

.inventory-success {
  color: #2d7b46;
}

.inventory-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.74);
}

.inventory-table {
  width: 100%;
  min-width: 1180px;
  border-collapse: collapse;
}

.inventory-table th,
.inventory-table td {
  padding: 14px 12px;
  border-bottom: 1px solid var(--line);
  text-align: center;
  vertical-align: middle;
  white-space: nowrap;
}

.inventory-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6ede4;
  font-weight: 700;
}

.inventory-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.72);
}

.sku-cell {
  text-align: left !important;
  white-space: normal;
}

.sku-cell strong {
  display: block;
}

.sku-cell p {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 0.88rem;
}

.image-cell {
  min-width: 96px;
}

.inventory-thumb {
  width: 64px;
  height: 64px;
  margin: 0 auto;
  border-radius: 14px;
  overflow: hidden;
  background: #f3ebe4;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 0.82rem;
}

.inventory-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.inventory-thumb.empty {
  border: 1px dashed var(--line);
}

.stock-cell {
  min-width: 76px;
}

.stock-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  min-height: 32px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(179, 110, 72, 0.12);
  color: var(--text);
  font-weight: 600;
}

.stock-chip.zero {
  background: rgba(122, 102, 89, 0.12);
  color: var(--muted);
}

.empty-chip {
  min-width: 32px;
}

.stock-input {
  width: 72px;
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: white;
  text-align: center;
}

.total-stock-cell strong {
  color: var(--accent);
}

.actions-cell {
  min-width: 176px;
}

.row-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
}

.empty-state {
  padding: 36px 0 20px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 1080px) {
  .filter-row,
  .inventory-summary-grid {
    grid-template-columns: 1fr;
  }

  .row-actions {
    flex-direction: column;
  }
}
</style>
