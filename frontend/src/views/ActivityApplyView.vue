<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card">
        <div class="page-head">
          <div>
            <h1>活动报名</h1>
            <p class="small-note">
              先按分类、标题、商品编码或 SKU 查询商品，再批量勾选并报名到指定活动模块。
            </p>
          </div>
        </div>

        <div class="module-pick-grid">
          <label
            v-for="module in modules"
            :key="module.key"
            class="module-pick-card"
            :class="{ active: moduleSelection[module.key] }"
          >
            <input v-model="moduleSelection[module.key]" type="checkbox" />
            <div>
              <strong>{{ module.title }}</strong>
              <p>{{ module.description }}</p>
            </div>
            <span>{{ selectedCount(module.key) }} 已报名</span>
          </label>
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
            <span>关键词</span>
            <input
              v-model.trim="keywordDraft"
              class="admin-field"
              placeholder="请输入商品标题、商品编码或 SKU"
            />
          </label>

          <div class="filter-actions">
            <button class="admin-button ghost" type="submit">查询</button>
          </div>
        </form>

        <div class="toolbar">
          <div class="toolbar-copy">
            <strong>已选 {{ selectedIds.length }} 个商品</strong>
            <span class="small-note">查询结果 {{ filteredProducts.length }} 个</span>
          </div>

          <div class="inline-actions">
            <button
              class="admin-button ghost"
              type="button"
              :disabled="!paginatedProducts.length"
              @click="selectCurrentPage"
            >
              勾选本页
            </button>
            <button
              class="admin-button ghost"
              type="button"
              :disabled="!selectedIds.length"
              @click="clearCurrentPage"
            >
              取消本页
            </button>
            <button
              class="admin-button ghost"
              type="button"
              :disabled="!selectedIds.length"
              @click="clearAllSelection"
            >
              清空已选
            </button>
            <button class="admin-button" type="button" :disabled="saving" @click="submitApply">
              {{ saving ? '提交中...' : '批量报名' }}
            </button>
          </div>
        </div>

        <p v-if="errorText" class="admin-error">{{ errorText }}</p>
        <p v-if="successText" class="success-text">{{ successText }}</p>

        <div v-if="!filteredProducts.length" class="empty-state">没有查到符合条件的商品。</div>

        <div v-else class="product-list-grid">
          <article v-for="item in paginatedProducts" :key="item.id" class="product-item-card">
            <label class="product-check">
              <input
                :checked="isSelected(item.id)"
                type="checkbox"
                @change="toggleSelection(item.id, $event.target.checked)"
              />
            </label>

            <div class="product-item-cover">
              <img :src="item.image" :alt="item.name?.zh || item.productCode || item.sku" />
            </div>

            <div class="product-item-copy">
              <strong>{{ item.name?.zh || item.name?.en || item.productCode || item.sku }}</strong>
              <p>编码：{{ item.productCode || '--' }} / SKU：{{ item.sku || '--' }}</p>
              <p>分类：{{ item.categoryLabel || item.categoryKey || '--' }}</p>
              <div class="tag-row">
                <span
                  v-for="module in enrolledModules(item.id)"
                  :key="`${item.id}-${module.key}`"
                  class="module-tag"
                >
                  {{ module.shortTitle }}
                </span>
                <span v-if="!enrolledModules(item.id).length" class="module-tag muted">未报名</span>
              </div>
            </div>
          </article>
        </div>

        <PaginationBar
          v-if="filteredProducts.length"
          :page="currentPage"
          :page-size="pageSize"
          :size-options="[20, 40, 60]"
          :total-items="filteredProducts.length"
          item-label="个商品"
          @update:page="currentPage = $event"
          @update:page-size="pageSize = $event"
        />
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import PaginationBar from '../components/PaginationBar.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()

const modules = [
  {
    key: 'bestSeller',
    title: 'Best Seller',
    shortTitle: 'Best Seller',
    description: '报名到热销专区的 View All 页面',
  },
  {
    key: 'newArrival',
    title: 'New Arrival',
    shortTitle: 'New Arrival',
    description: '报名到新品专区的 View All 页面',
  },
  {
    key: 'specialPrice',
    title: 'PRE-ORDER',
    shortTitle: 'PRE-ORDER',
    description: '报名到特价专区的 View All 页面',
  },
]

function createEmptyForm() {
  return {
    heroBanners: {
      bestSeller: '',
      newArrival: '',
      specialPrice: '',
    },
    sectionProductIds: {
      bestSeller: [],
      newArrival: [],
      specialPrice: [],
    },
    collectionProductIds: {
      bestSeller: [],
      newArrival: [],
      specialPrice: [],
    },
    displayCategoryKeys: [],
  }
}

const form = reactive(createEmptyForm())
const selectedIds = ref([])
const selectedCategoryDraft = ref('')
const selectedCategory = ref('')
const keywordDraft = ref('')
const keyword = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const saving = ref(false)
const errorText = ref('')
const successText = ref('')

const moduleSelection = reactive({
  bestSeller: false,
  newArrival: false,
  specialPrice: false,
})

watch(
  () => admin.homeConfig,
  (value) => {
    if (!value) return
    form.heroBanners.bestSeller = String(value.heroBanners?.bestSeller || '')
    form.heroBanners.newArrival = String(value.heroBanners?.newArrival || '')
    form.heroBanners.specialPrice = String(value.heroBanners?.specialPrice || '')
    form.sectionProductIds.bestSeller = [...(value.sectionProductIds?.bestSeller || [])]
    form.sectionProductIds.newArrival = [...(value.sectionProductIds?.newArrival || [])]
    form.sectionProductIds.specialPrice = [...(value.sectionProductIds?.specialPrice || [])]
    form.collectionProductIds.bestSeller = [...(value.collectionProductIds?.bestSeller || [])]
    form.collectionProductIds.newArrival = [...(value.collectionProductIds?.newArrival || [])]
    form.collectionProductIds.specialPrice = [...(value.collectionProductIds?.specialPrice || [])]
    form.displayCategoryKeys = [...(value.displayCategoryKeys || [])]
  },
  { immediate: true }
)

const filteredProducts = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()

  return admin.products.filter((item) => {
    const categoryMatch = !selectedCategory.value || item.categoryKey === selectedCategory.value
    if (!categoryMatch) return false
    if (!normalizedKeyword) return true

    const haystack = [
      item.name?.zh,
      item.name?.en,
      item.productCode,
      item.sku,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return haystack.includes(normalizedKeyword)
  })
})

const paginatedProducts = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredProducts.value.slice(start, start + pageSize.value)
})

watch(pageSize, () => {
  currentPage.value = 1
})

watch(
  () => filteredProducts.value.length,
  (count) => {
    const totalPages = Math.max(1, Math.ceil(count / pageSize.value))
    if (currentPage.value > totalPages) {
      currentPage.value = totalPages
    }
  },
  { immediate: true }
)

function applyFilters() {
  selectedCategory.value = selectedCategoryDraft.value
  keyword.value = keywordDraft.value.trim()
  currentPage.value = 1
}

function isSelected(productId) {
  return selectedIds.value.includes(Number(productId))
}

function toggleSelection(productId, checked) {
  const normalizedId = Number(productId)
  if (checked) {
    if (!selectedIds.value.includes(normalizedId)) {
      selectedIds.value = [...selectedIds.value, normalizedId]
    }
    return
  }
  selectedIds.value = selectedIds.value.filter((id) => id !== normalizedId)
}

function selectCurrentPage() {
  const pageIds = paginatedProducts.value.map((item) => Number(item.id))
  selectedIds.value = Array.from(new Set([...selectedIds.value, ...pageIds]))
}

function clearCurrentPage() {
  const pageIdSet = new Set(paginatedProducts.value.map((item) => Number(item.id)))
  selectedIds.value = selectedIds.value.filter((id) => !pageIdSet.has(id))
}

function clearAllSelection() {
  selectedIds.value = []
}

function selectedCount(moduleKey) {
  const validIds = new Set(admin.products.map((item) => Number(item.id)))
  return (form.collectionProductIds[moduleKey] || []).filter((id) => validIds.has(Number(id))).length
}

function enrolledModules(productId) {
  const normalizedId = Number(productId)
  return modules.filter((module) =>
    (form.collectionProductIds[module.key] || []).some((id) => Number(id) === normalizedId)
  )
}

function buildPayload(nextCollectionProductIds) {
  return {
    heroBanners: { ...form.heroBanners },
    sectionProductIds: {
      bestSeller: [...form.sectionProductIds.bestSeller],
      newArrival: [...form.sectionProductIds.newArrival],
      specialPrice: [...form.sectionProductIds.specialPrice],
    },
    collectionProductIds: {
      bestSeller: [...nextCollectionProductIds.bestSeller],
      newArrival: [...nextCollectionProductIds.newArrival],
      specialPrice: [...nextCollectionProductIds.specialPrice],
    },
    displayCategoryKeys: [...form.displayCategoryKeys],
  }
}

async function submitApply() {
  errorText.value = ''
  successText.value = ''

  const targetModules = modules
    .filter((module) => moduleSelection[module.key])
    .map((module) => module.key)

  if (!selectedIds.value.length) {
    errorText.value = '请先勾选要报名的商品。'
    return
  }

  if (!targetModules.length) {
    errorText.value = '请至少选择一个活动模块。'
    return
  }

  saving.value = true

  try {
    const nextCollectionProductIds = {
      bestSeller: [...form.collectionProductIds.bestSeller],
      newArrival: [...form.collectionProductIds.newArrival],
      specialPrice: [...form.collectionProductIds.specialPrice],
    }

    let addedCount = 0

    targetModules.forEach((moduleKey) => {
      const existing = new Set(nextCollectionProductIds[moduleKey].map((id) => Number(id)))
      selectedIds.value.forEach((productId) => {
        const normalizedId = Number(productId)
        if (!existing.has(normalizedId)) {
          nextCollectionProductIds[moduleKey].push(normalizedId)
          existing.add(normalizedId)
          addedCount += 1
        }
      })
    })

    await admin.saveHomeConfig(buildPayload(nextCollectionProductIds))
    await admin.loadHomeConfig()

    successText.value =
      addedCount > 0
        ? `报名成功，新增 ${addedCount} 条活动商品记录。`
        : '所选商品已经在对应活动模块中。'

    selectedIds.value = []
    Object.keys(moduleSelection).forEach((key) => {
      moduleSelection[key] = false
    })
  } catch (error) {
    errorText.value = error.message || '报名失败'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([admin.loadProducts(), admin.loadCategories(), admin.loadHomeConfig()])
})
</script>

<style scoped>
.page-head h1 {
  margin: 0 0 6px;
}

.module-pick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 18px 0;
}

.module-pick-card {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: start;
  gap: 12px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  cursor: pointer;
}

.module-pick-card.active {
  border-color: rgba(179, 110, 72, 0.35);
  box-shadow: 0 10px 24px rgba(179, 110, 72, 0.08);
}

.module-pick-card input {
  margin-top: 4px;
}

.module-pick-card strong,
.module-pick-card p,
.toolbar-copy strong {
  margin: 0;
}

.module-pick-card p,
.module-pick-card span {
  color: var(--muted);
  font-size: 0.92rem;
}

.filter-row {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) auto;
  gap: 14px;
  margin-bottom: 14px;
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

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.toolbar-copy {
  display: grid;
  gap: 4px;
}

.success-text {
  color: #2f7a48;
}

.product-list-grid {
  display: grid;
  gap: 14px;
}

.product-item-card {
  display: grid;
  grid-template-columns: auto 88px minmax(0, 1fr);
  gap: 14px;
  align-items: center;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
}

.product-check {
  display: grid;
  place-items: center;
}

.product-item-cover {
  width: 88px;
  height: 110px;
  overflow: hidden;
  border: 1px solid rgba(110, 85, 61, 0.16);
  background: #f6f2ec;
}

.product-item-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.product-item-copy {
  display: grid;
  gap: 6px;
}

.product-item-copy strong,
.product-item-copy p {
  margin: 0;
}

.tag-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.module-tag {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  background: #f5eee7;
  color: #7a583d;
  font-size: 0.84rem;
}

.module-tag.muted {
  background: #f4f4f4;
  color: #7f7f7f;
}

.empty-state {
  padding: 18px;
  color: var(--muted);
  border: 1px dashed var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
}

@media (max-width: 1080px) {
  .module-pick-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .filter-row,
  .product-item-card {
    grid-template-columns: 1fr;
  }

  .toolbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .product-check {
    justify-content: flex-start;
  }
}
</style>
