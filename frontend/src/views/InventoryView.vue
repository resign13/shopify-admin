<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card">
        <div class="inventory-page-head">
          <div>
            <h1>库存管理</h1>
            <p class="small-note">
              按颜色 SKU 展示商品图片、各尺码库存和当前总库存，查看方式尽量贴近你现在用的 Excel。
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
        <div v-if="loading" class="small-note">库存数据加载中...</div>
        <div v-else-if="!inventoryRows.length" class="empty-state">暂无符合条件的库存数据。</div>

        <div v-else class="inventory-table-wrap">
          <table class="inventory-table">
            <thead>
              <tr>
                <th>颜色 SKU</th>
                <th>图片</th>
                <th>商品名称</th>
                <th>颜色</th>
                <th>分类</th>
                <th v-for="size in visibleSizes" :key="size">{{ size }}</th>
                <th>当前库存</th>
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
                <td class="product-cell">
                  <strong>{{ displayName(item) }}</strong>
                </td>
                <td>{{ item.colorName || '未设置颜色' }}</td>
                <td>{{ categoryLabel(item) }}</td>
                <td v-for="size in visibleSizes" :key="`${item.id}-${size}`">
                  <span class="stock-chip" :class="{ zero: readSizeStock(item, size) === 0 }">
                    {{ readSizeStock(item, size) }}
                  </span>
                </td>
                <td class="total-stock-cell">
                  <strong>{{ item.totalStock }}</strong>
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

.inventory-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.74);
}

.inventory-table {
  width: 100%;
  min-width: 1080px;
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

.sku-cell,
.product-cell {
  text-align: left !important;
  white-space: normal;
}

.sku-cell strong,
.product-cell strong {
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

.total-stock-cell strong {
  color: var(--accent);
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
}
</style>
