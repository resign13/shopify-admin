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


const MERGED_SIZE_GROUPS = [
  { key: 'S/28', aliases: ['S', '28'] },
  { key: 'M/30', aliases: ['M', '30'] },
  { key: 'L/32', aliases: ['L', '32'] },
  { key: 'XL/34', aliases: ['XL', '34'] },
  { key: 'XXL/36', aliases: ['XXL', '36'] },
  { key: 'XXXL/38', aliases: ['XXXL', '38'] },
]

const MERGED_SIZE_ALIAS_MAP = Object.fromEntries(
  MERGED_SIZE_GROUPS.flatMap((group) =>
    group.aliases.map((alias) => [alias, group])
  )
)

function normalizeSizeCode(size) {
  return String(size || '').trim().toUpperCase()
}

function displaySizeKey(size) {
  const normalized = normalizeSizeCode(size)
  return MERGED_SIZE_ALIAS_MAP[normalized]?.key || normalized
}

function displaySizeAliases(size) {
  const normalized = normalizeSizeCode(size)
  return MERGED_SIZE_ALIAS_MAP[normalized]?.aliases || [normalized]
}

function itemDisplaySizes(item) {
  const seen = new Set()
  const result = []
  for (const rawSize of item.rowSizes || []) {
    const key = displaySizeKey(rawSize)
    if (key && !seen.has(key)) {
      seen.add(key)
      result.push(key)
    }
  }
  return result
}

function distributeMergedStock(total, aliases, previousMap) {
  const normalizedAliases = aliases.map(normalizeSizeCode).filter(Boolean)
  if (!normalizedAliases.length) return {}
  if (normalizedAliases.length === 1) return { [normalizedAliases[0]]: total }

  const previousValues = normalizedAliases.map((alias) => Math.max(0, Number(previousMap[alias] || 0)))
  const previousTotal = previousValues.reduce((sum, value) => sum + value, 0)

  if (previousTotal <= 0) {
    return Object.fromEntries(normalizedAliases.map((alias, index) => [alias, index === 0 ? total : 0]))
  }

  const floors = previousValues.map((value) => Math.floor((total * value) / previousTotal))
  let remainder = total - floors.reduce((sum, value) => sum + value, 0)
  const fractions = previousValues
    .map((value, index) => ({
      index,
      fraction: (total * value) / previousTotal - floors[index],
    }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index)

  for (const item of fractions) {
    if (remainder <= 0) break
    floors[item.index] += 1
    remainder -= 1
  }

  return Object.fromEntries(normalizedAliases.map((alias, index) => [alias, floors[index]]))
}

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
        const normalizedSize = normalizeSizeCode(row?.sizeCode)
        if (normalizedSize) {
          sizeStockMap[normalizedSize] = Number(row.stock || 0)
        }
      }
      const rowSizes = (Array.isArray(item.sizes) && item.sizes.length
        ? item.sizes
        : Object.keys(sizeStockMap)).map(normalizeSizeCode).filter(Boolean)
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
    for (const size of itemDisplaySizes(row)) {
      if (size && !seen.has(size)) {
        seen.add(size)
        items.push(size)
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

function readExactSizeStock(item, size) {
  return Number(item.sizeStockMap?.[normalizeSizeCode(size)] || 0)
}

function readSizeStock(item, size) {
  return displaySizeAliases(size).reduce((total, alias) => total + readExactSizeStock(item, alias), 0)
}

function hasSize(item, size) {
  const rowSizes = (item.rowSizes || []).map(normalizeSizeCode)
  return displaySizeAliases(size).some((alias) => rowSizes.includes(alias))
}

function isEditing(productId) {
  return Number(editingId.value) === Number(productId)
}

function startEdit(item) {
  error.value = ''
  saveMessage.value = ''
  editingId.value = Number(item.id)
  draftStocks.value[String(item.id)] = Object.fromEntries(
    itemDisplaySizes(item).map((size) => [size, String(readSizeStock(item, size))])
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
  return itemDisplaySizes(item).reduce((total, size) => total + toSafeInt(draft[size]), 0)
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
  const previousMap = Object.fromEntries(
    (item.rowSizes || []).map((size) => [normalizeSizeCode(size), readExactSizeStock(item, size)])
  )

  for (const size of itemDisplaySizes(item)) {
    const rawValue = draft[size]
    const number = Number(rawValue)
    if (!Number.isFinite(number) || number < 0 || !Number.isInteger(number)) {
      error.value = `${item.sku || item.productCode} / ${size} 的库存必须是大于等于 0 的整数`
      return
    }

    const aliases = displaySizeAliases(size).filter((alias) => (item.rowSizes || []).includes(alias))
    const expanded = distributeMergedStock(number, aliases.length ? aliases : [size], previousMap)
    Object.assign(payload, expanded)
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
