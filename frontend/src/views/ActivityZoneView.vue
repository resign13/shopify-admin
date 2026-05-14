<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card">
        <div class="activity-zone-head">
          <div>
            <h1>活动专区</h1>
            <p class="small-note">
              这里单独管理 Best Seller、New Arrival、PRE-ORDER 三个独立页面的商品。
            </p>
          </div>
        </div>

        <form class="editor-form" @submit.prevent="save">
          <section v-for="slot in sectionSlots" :key="slot.key" class="config-panel">
            <button class="config-panel-head" type="button" @click="togglePanel(slot.key)">
              <div>
                <h3>{{ slot.title }}</h3>
                <p class="small-note">{{ slot.description }}</p>
              </div>
              <span>{{ panelOpen[slot.key] ? '收起' : '展开' }}</span>
            </button>

            <div v-if="panelOpen[slot.key]" class="config-panel-body">
              <div class="config-subcard">
                <div class="config-subcard-head">
                  <div>
                    <h4>按编码搜索后添加</h4>
                    <p>输入商品编码、SKU 或标题关键字，筛选商品后再加入当前活动页。</p>
                  </div>
                  <span>{{ selectedProducts(slot.key).length }} 个</span>
                </div>

                <div class="search-grid">
                  <input
                    v-model.trim="addSearchKeywords[slot.key]"
                    class="admin-field"
                    type="text"
                    placeholder="输入商品编码、SKU 或标题搜索"
                  />
                  <select v-model.number="collectionProductDrafts[slot.key]" class="admin-field">
                    <option :value="0">请选择商品</option>
                    <option
                      v-for="item in filteredAvailableProducts(slot.key)"
                      :key="item.id"
                      :value="item.id"
                    >
                      {{ productLabel(item) }}
                    </option>
                  </select>
                  <button
                    class="admin-button ghost"
                    type="button"
                    :disabled="!collectionProductDrafts[slot.key]"
                    @click="addProduct(slot.key)"
                  >
                    添加商品
                  </button>
                </div>

                <div v-if="addSearchKeywords[slot.key] && !filteredAvailableProducts(slot.key).length" class="empty-state">
                  没有搜索到可添加的商品。
                </div>
              </div>

              <div class="config-subcard">
                <div class="config-subcard-head">
                  <div>
                    <h4>已加入活动页的商品</h4>
                    <p>先搜索筛选出已添加的商品，再进行排序或移除。</p>
                  </div>
                  <span>{{ filteredSelectedProducts(slot.key).length }} / {{ selectedProducts(slot.key).length }}</span>
                </div>

                <input
                  v-model.trim="selectedSearchKeywords[slot.key]"
                  class="admin-field"
                  type="text"
                  placeholder="输入商品编码、SKU 或标题筛选已添加商品"
                />

                <div v-if="filteredSelectedProducts(slot.key).length" class="home-config-list">
                  <div
                    v-for="item in filteredSelectedProducts(slot.key)"
                    :key="`${slot.key}-${item.id}`"
                    class="home-config-row"
                  >
                    <div>
                      <strong>{{ productLabel(item) }}</strong>
                      <p>{{ item.categoryLabel || item.categoryKey }}</p>
                    </div>
                    <div class="inline-actions">
                      <button
                        class="admin-button ghost"
                        type="button"
                        :disabled="selectedIndex(slot.key, item.id) === 0"
                        @click="moveByProductId(slot.key, item.id, -1)"
                      >
                        上移
                      </button>
                      <button
                        class="admin-button ghost"
                        type="button"
                        :disabled="selectedIndex(slot.key, item.id) === selectedProducts(slot.key).length - 1"
                        @click="moveByProductId(slot.key, item.id, 1)"
                      >
                        下移
                      </button>
                      <button
                        class="admin-button ghost"
                        type="button"
                        @click="removeByProductId(slot.key, item.id)"
                      >
                        移除活动
                      </button>
                    </div>
                  </div>
                </div>
                <div v-else class="empty-state">
                  {{ selectedProducts(slot.key).length ? '没有匹配到已添加商品。' : '这个活动页面还没有添加商品。' }}
                </div>
              </div>
            </div>
          </section>

          <p v-if="errorText" class="admin-error">{{ errorText }}</p>
          <div class="inline-actions">
            <button class="admin-button" type="submit" :disabled="saving">
              {{ saving ? '保存中...' : '保存活动专区' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const saving = ref(false)
const errorText = ref('')

const collectionProductDrafts = reactive({
  bestSeller: 0,
  newArrival: 0,
  specialPrice: 0,
})

const addSearchKeywords = reactive({
  bestSeller: '',
  newArrival: '',
  specialPrice: '',
})

const selectedSearchKeywords = reactive({
  bestSeller: '',
  newArrival: '',
  specialPrice: '',
})

const panelOpen = reactive({
  bestSeller: true,
  newArrival: false,
  specialPrice: false,
})

const sectionSlots = [
  {
    key: 'bestSeller',
    title: 'Best Seller 活动页',
    description: '配置前台 Best Seller 模块 View All 对应独立页面的商品。',
  },
  {
    key: 'newArrival',
    title: 'New Arrival 活动页',
    description: '配置前台 New Arrival 模块 View All 对应独立页面的商品。',
  },
  {
    key: 'specialPrice',
    title: 'PRE-ORDER 活动页',
    description: '配置前台 PRE-ORDER 模块 View All 对应独立页面的商品。',
  },
]

const form = reactive({
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

function productLabel(item) {
  const title = item.name?.zh || item.name?.en || item.productCode || item.sku
  return `${title} / ${item.productCode || item.sku}`
}

function matchesKeyword(item, keyword) {
  const normalized = String(keyword || '').trim().toLowerCase()
  if (!normalized) return true

  const text = [
    item.productCode,
    item.sku,
    item.name?.zh,
    item.name?.en,
    item.categoryLabel,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

  return text.includes(normalized)
}

function availableProducts(sectionKey) {
  const selected = new Set(form.collectionProductIds[sectionKey] || [])
  return admin.products.filter((item) => !selected.has(item.id))
}

function filteredAvailableProducts(sectionKey) {
  return availableProducts(sectionKey).filter((item) =>
    matchesKeyword(item, addSearchKeywords[sectionKey])
  )
}

function selectedProducts(sectionKey) {
  return (form.collectionProductIds[sectionKey] || [])
    .map((id) => admin.products.find((item) => item.id === id))
    .filter(Boolean)
}

function filteredSelectedProducts(sectionKey) {
  return selectedProducts(sectionKey).filter((item) =>
    matchesKeyword(item, selectedSearchKeywords[sectionKey])
  )
}

function selectedIndex(sectionKey, productId) {
  return form.collectionProductIds[sectionKey].findIndex((id) => Number(id) === Number(productId))
}

function togglePanel(key) {
  panelOpen[key] = !panelOpen[key]
}

function addProduct(sectionKey) {
  const productId = Number(collectionProductDrafts[sectionKey] || 0)
  if (!productId) return
  form.collectionProductIds[sectionKey] = [...form.collectionProductIds[sectionKey], productId]
  collectionProductDrafts[sectionKey] = 0
}

function moveProduct(sectionKey, index, direction) {
  const next = [...form.collectionProductIds[sectionKey]]
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= next.length) return
  const [item] = next.splice(index, 1)
  next.splice(targetIndex, 0, item)
  form.collectionProductIds[sectionKey] = next
}

function moveByProductId(sectionKey, productId, direction) {
  const index = selectedIndex(sectionKey, productId)
  if (index < 0) return
  moveProduct(sectionKey, index, direction)
}

function removeByProductId(sectionKey, productId) {
  form.collectionProductIds[sectionKey] = form.collectionProductIds[sectionKey].filter(
    (id) => Number(id) !== Number(productId)
  )
}

async function save() {
  errorText.value = ''
  saving.value = true

  try {
    await admin.saveHomeConfig({
      heroBanners: { ...form.heroBanners },
      sectionProductIds: {
        bestSeller: [...form.sectionProductIds.bestSeller],
        newArrival: [...form.sectionProductIds.newArrival],
        specialPrice: [...form.sectionProductIds.specialPrice],
      },
      collectionProductIds: {
        bestSeller: [...form.collectionProductIds.bestSeller],
        newArrival: [...form.collectionProductIds.newArrival],
        specialPrice: [...form.collectionProductIds.specialPrice],
      },
      displayCategoryKeys: [...form.displayCategoryKeys],
    })
  } catch (error) {
    errorText.value = error.message || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([admin.loadProducts(), admin.loadHomeConfig()])
})
</script>

<style scoped>
.activity-zone-head h1 {
  margin: 0 0 6px;
}

.config-panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.82);
  overflow: hidden;
}

.config-panel-head {
  width: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 20px 22px;
  border: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(246, 244, 239, 0.92));
  cursor: pointer;
  text-align: left;
}

.config-panel-head h3 {
  margin: 0 0 6px;
}

.config-panel-head span {
  color: var(--muted);
  white-space: nowrap;
}

.config-panel-body {
  display: grid;
  gap: 16px;
  padding: 0 22px 22px;
}

.config-subcard {
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 22px;
  background: #fff;
}

.config-subcard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.config-subcard-head h4 {
  margin: 0 0 6px;
}

.config-subcard-head p {
  margin: 0;
  color: var(--muted);
  font-size: 0.92rem;
}

.config-subcard-head span {
  color: var(--muted);
  white-space: nowrap;
}

.search-grid {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(260px, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.home-config-list {
  display: grid;
  gap: 12px;
}

.home-config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #fff;
}

.home-config-row p {
  margin: 6px 0 0;
  color: var(--muted);
}

.empty-state {
  padding: 16px 18px;
  color: var(--muted);
  border: 1px dashed var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
}

@media (max-width: 980px) {
  .config-panel-head,
  .config-subcard-head,
  .home-config-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .search-grid {
    grid-template-columns: 1fr;
  }
}
</style>
