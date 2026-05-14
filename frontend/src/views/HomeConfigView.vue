<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card">
        <div class="home-config-head">
          <div>
            <h1>首页配置</h1>
            <p class="small-note">
              这里统一管理首页海报、首页展示分类，以及首页 3 个模块展示的商品。
            </p>
          </div>
        </div>

        <form class="editor-form" @submit.prevent="save">
          <section class="config-panel">
            <button class="config-panel-head" type="button" @click="togglePanel('hero')">
              <div>
                <h3>首页海报</h3>
                <p class="small-note">上传首页顶部 3 张横幅海报，保存后前台会立即使用。</p>
              </div>
              <span>{{ panelOpen.hero ? '收起' : '展开' }}</span>
            </button>

            <div v-if="panelOpen.hero" class="config-panel-body">
              <div class="hero-grid">
                <article v-for="slot in bannerSlots" :key="slot.key" class="hero-card">
                  <div class="hero-card-head">
                    <div>
                      <h4>{{ slot.label }}</h4>
                      <p>{{ slot.tip }}</p>
                    </div>
                    <span v-if="uploadingSlots[slot.key]" class="uploading-tag">上传中...</span>
                  </div>

                  <div class="hero-preview">
                    <img v-if="heroPreview(slot.key)" :src="heroPreview(slot.key)" :alt="slot.label" />
                    <div v-else class="hero-preview-empty">暂未上传图片</div>
                  </div>

                  <div class="hero-actions">
                    <label class="admin-button ghost upload-trigger">
                      上传图片
                      <input
                        accept="image/*"
                        hidden
                        type="file"
                        @change="handleHeroUpload(slot.key, $event)"
                      />
                    </label>
                    <button
                      class="admin-button ghost"
                      type="button"
                      :disabled="!form.heroBanners[slot.key]"
                      @click="clearHero(slot.key)"
                    >
                      清空
                    </button>
                  </div>

                  <p class="hero-url" :title="form.heroBanners[slot.key]">
                    {{ form.heroBanners[slot.key] || '上传后会显示图片地址' }}
                  </p>
                </article>
              </div>
            </div>
          </section>

          <section class="config-panel">
            <button class="config-panel-head" type="button" @click="togglePanel('categories')">
              <div>
                <h3>首页展示分类</h3>
                <p class="small-note">显示在首页海报下方，最多展示 5 个分类。</p>
              </div>
              <span>{{ panelOpen.categories ? '收起' : '展开' }}</span>
            </button>

            <div v-if="panelOpen.categories" class="config-panel-body">
              <div v-if="!hasCategories" class="empty-state">
                请先到商品分类管理中创建分类，再回到这里选择首页展示分类。
              </div>

              <div v-else class="home-config-adder">
                <select v-model="categoryDraft" class="admin-field">
                  <option value="">请选择商品分类</option>
                  <option v-for="item in availableCategories" :key="item.key" :value="item.key">
                    {{ item.labels?.en || item.label || item.key }}
                  </option>
                </select>
                <button
                  class="admin-button ghost"
                  type="button"
                  :disabled="!categoryDraft || form.displayCategoryKeys.length >= 5"
                  @click="addCategory"
                >
                  添加分类
                </button>
              </div>

              <div v-if="displayCategories.length" class="home-config-list">
                <div
                  v-for="(item, index) in displayCategories"
                  :key="`${item.key}-${index}`"
                  class="home-config-row"
                >
                  <div>
                    <strong>{{ item.label }}</strong>
                    <p>{{ item.key }}</p>
                  </div>
                  <div class="inline-actions">
                    <button
                      class="admin-button ghost"
                      type="button"
                      :disabled="index === 0"
                      @click="moveCategory(index, -1)"
                    >
                      上移
                    </button>
                    <button
                      class="admin-button ghost"
                      type="button"
                      :disabled="index === form.displayCategoryKeys.length - 1"
                      @click="moveCategory(index, 1)"
                    >
                      下移
                    </button>
                    <button class="admin-button ghost" type="button" @click="removeCategory(index)">
                      删除
                    </button>
                  </div>
                </div>
              </div>
              <div v-else class="empty-state">还没有选择首页展示分类。</div>
            </div>
          </section>

          <section v-for="slot in sectionSlots" :key="slot.key" class="config-panel">
            <button class="config-panel-head" type="button" @click="togglePanel(slot.key)">
              <div>
                <h3>{{ slot.title }}</h3>
                <p class="small-note">{{ slot.description }}</p>
              </div>
              <span>{{ panelOpen[slot.key] ? '收起' : '展开' }}</span>
            </button>

            <div v-if="panelOpen[slot.key]" class="config-panel-body">
              <div class="config-subcard-head">
                <div>
                  <h4>首页模块商品</h4>
                  <p>请先查询商品，再选择并提交到首页模块。每个模块最多 5 个。</p>
                </div>
                <span>{{ selectedProducts(slot.key).length }}/5</span>
              </div>

              <div class="module-action-row">
                <form class="search-grid" @submit.prevent="applySectionSearch(slot.key)">
                  <input
                    v-model.trim="searchKeywordDrafts[slot.key]"
                    class="admin-field"
                    type="text"
                    placeholder="请输入商品标题、商品编码或 SKU"
                  />
                  <button class="admin-button ghost compact-button" type="submit">查询</button>
                </form>

                <div class="home-config-adder">
                  <select v-model.number="homeProductDrafts[slot.key]" class="admin-field">
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
                    class="admin-button ghost compact-button"
                    type="button"
                    :disabled="!homeProductDrafts[slot.key] || selectedProducts(slot.key).length >= 5"
                    @click="addProduct(slot.key)"
                  >
                    提交商品
                  </button>
                </div>
              </div>

              <p class="small-note">
                查询结果 {{ filteredAvailableProducts(slot.key).length }} 个
                <template v-if="searchKeywordValues[slot.key]">
                  ，关键词：{{ searchKeywordValues[slot.key] }}
                </template>
              </p>

              <div v-if="selectedProducts(slot.key).length" class="home-config-list">
                <div
                  v-for="(item, index) in selectedProducts(slot.key)"
                  :key="`${slot.key}-${item.id}-${index}`"
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
                      :disabled="index === 0"
                      @click="moveProduct(slot.key, index, -1)"
                    >
                      上移
                    </button>
                    <button
                      class="admin-button ghost"
                      type="button"
                      :disabled="index === selectedProducts(slot.key).length - 1"
                      @click="moveProduct(slot.key, index, 1)"
                    >
                      下移
                    </button>
                    <button class="admin-button ghost" type="button" @click="removeProduct(slot.key, index)">
                      删除
                    </button>
                  </div>
                </div>
              </div>
              <div v-else class="empty-state">这个模块还没有添加首页商品。</div>
            </div>
          </section>

          <p v-if="errorText" class="admin-error">{{ errorText }}</p>
          <div class="inline-actions">
            <button class="admin-button" type="submit" :disabled="saving">
              {{ saving ? '保存中...' : '保存首页配置' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const saving = ref(false)
const errorText = ref('')
const categoryDraft = ref('')

const homeProductDrafts = reactive({
  bestSeller: 0,
  newArrival: 0,
  specialPrice: 0,
})

const searchKeywordDrafts = reactive({
  bestSeller: '',
  newArrival: '',
  specialPrice: '',
})

const searchKeywordValues = reactive({
  bestSeller: '',
  newArrival: '',
  specialPrice: '',
})

const uploadingSlots = reactive({
  bestSeller: false,
  newArrival: false,
  specialPrice: false,
})

const localHeroPreviews = reactive({
  bestSeller: '',
  newArrival: '',
  specialPrice: '',
})

const panelOpen = reactive({
  hero: false,
  categories: false,
  bestSeller: false,
  newArrival: false,
  specialPrice: false,
})

const bannerSlots = [
  { key: 'bestSeller', label: 'Best Seller 海报', tip: '首页 Best Seller 模块顶部海报' },
  { key: 'newArrival', label: 'New Arrival 海报', tip: '首页 New Arrival 模块顶部海报' },
  { key: 'specialPrice', label: 'PRE-ORDER 海报', tip: '首页 PRE-ORDER 模块顶部海报' },
]

const sectionSlots = [
  { key: 'bestSeller', title: 'Best Seller 模块', description: '设置首页 Best Seller 模块展示的商品。' },
  { key: 'newArrival', title: 'New Arrival 模块', description: '设置首页 New Arrival 模块展示的商品。' },
  { key: 'specialPrice', title: 'PRE-ORDER 模块', description: '设置首页 PRE-ORDER 模块展示的商品。' },
]

function emptyForm() {
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

const form = reactive(emptyForm())

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

const hasCategories = computed(() => admin.categories.length > 0)

const availableCategories = computed(() =>
  admin.categories.filter((item) => item.key && !form.displayCategoryKeys.includes(item.key))
)

const displayCategories = computed(() =>
  form.displayCategoryKeys
    .map((key) => {
      const item = admin.categories.find((category) => category.key === key)
      if (!item) return null
      return {
        key,
        label: item.labels?.en || item.label || key,
      }
    })
    .filter(Boolean)
)

function matchesKeyword(item, keyword) {
  const normalizedKeyword = String(keyword || '').trim().toLowerCase()
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
}

function availableProducts(sectionKey) {
  const selected = new Set((form.sectionProductIds[sectionKey] || []).map((id) => Number(id)))
  return admin.products.filter((item) => !selected.has(Number(item.id)))
}

function filteredAvailableProducts(sectionKey) {
  return availableProducts(sectionKey).filter((item) =>
    matchesKeyword(item, searchKeywordValues[sectionKey])
  )
}

function selectedProducts(sectionKey) {
  return (form.sectionProductIds[sectionKey] || [])
    .map((id) => admin.products.find((item) => Number(item.id) === Number(id)))
    .filter(Boolean)
}

function syncDisplayCategories() {
  const validKeys = new Set(admin.categories.map((item) => item.key).filter(Boolean))
  form.displayCategoryKeys = form.displayCategoryKeys.filter((key) => validKeys.has(key))
  if (categoryDraft.value && !validKeys.has(categoryDraft.value)) {
    categoryDraft.value = ''
  }
}

function productLabel(item) {
  const title = item.name?.zh || item.productCode || item.sku
  return `${title} / ${item.productCode || item.sku}`
}

function togglePanel(key) {
  panelOpen[key] = !panelOpen[key]
}

function addCategory() {
  if (!categoryDraft.value || form.displayCategoryKeys.length >= 5) return
  form.displayCategoryKeys.push(categoryDraft.value)
  categoryDraft.value = ''
}

function moveCategory(index, direction) {
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= form.displayCategoryKeys.length) return
  const next = [...form.displayCategoryKeys]
  const [item] = next.splice(index, 1)
  next.splice(targetIndex, 0, item)
  form.displayCategoryKeys = next
}

function removeCategory(index) {
  form.displayCategoryKeys = form.displayCategoryKeys.filter(
    (_, currentIndex) => currentIndex !== index
  )
}

function applySectionSearch(sectionKey) {
  searchKeywordValues[sectionKey] = searchKeywordDrafts[sectionKey].trim()
  homeProductDrafts[sectionKey] = 0
}

function addProduct(sectionKey) {
  const productId = Number(homeProductDrafts[sectionKey] || 0)
  if (!productId || form.sectionProductIds[sectionKey].length >= 5) return
  form.sectionProductIds[sectionKey] = [...form.sectionProductIds[sectionKey], productId]
  homeProductDrafts[sectionKey] = 0
}

function moveProduct(sectionKey, index, direction) {
  const next = [...form.sectionProductIds[sectionKey]]
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= next.length) return
  const [item] = next.splice(index, 1)
  next.splice(targetIndex, 0, item)
  form.sectionProductIds[sectionKey] = next
}

function removeProduct(sectionKey, index) {
  form.sectionProductIds[sectionKey] = form.sectionProductIds[sectionKey].filter(
    (_, currentIndex) => currentIndex !== index
  )
}

function heroPreview(slotKey) {
  return localHeroPreviews[slotKey] || form.heroBanners[slotKey] || ''
}

function revokePreview(slotKey) {
  const value = localHeroPreviews[slotKey]
  if (value && value.startsWith('blob:')) {
    URL.revokeObjectURL(value)
  }
  localHeroPreviews[slotKey] = ''
}

async function handleHeroUpload(slotKey, event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return

  errorText.value = ''
  revokePreview(slotKey)
  localHeroPreviews[slotKey] = URL.createObjectURL(file)
  uploadingSlots[slotKey] = true

  try {
    const urls = await admin.uploadFiles([file])
    form.heroBanners[slotKey] = String(urls?.[0] || '')
    revokePreview(slotKey)
  } catch (error) {
    errorText.value = error.message || '图片上传失败'
  } finally {
    uploadingSlots[slotKey] = false
  }
}

function clearHero(slotKey) {
  revokePreview(slotKey)
  form.heroBanners[slotKey] = ''
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
  await Promise.all([admin.loadProducts(), admin.loadCategories(), admin.loadHomeConfig()])
  syncDisplayCategories()
})

onBeforeUnmount(() => {
  Object.keys(localHeroPreviews).forEach(revokePreview)
})
</script>

<style scoped>
.home-config-head h1 {
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

.hero-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.hero-card {
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 22px;
  background: #fff;
}

.hero-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hero-card-head h4 {
  margin: 0 0 6px;
}

.hero-card-head p {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
}

.uploading-tag {
  color: #7a5f2f;
  font-size: 0.88rem;
}

.hero-preview {
  display: grid;
  place-items: center;
  min-height: 180px;
  padding: 10px;
  border-radius: 18px;
  background: #f7f5ef;
  border: 1px dashed rgba(44, 39, 30, 0.12);
}

.hero-preview img {
  width: 100%;
  height: auto;
  max-height: 240px;
  object-fit: contain;
  display: block;
}

.hero-preview-empty {
  color: var(--muted);
  font-size: 0.92rem;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.upload-trigger {
  position: relative;
  overflow: hidden;
}

.hero-url {
  margin: 0;
  color: var(--muted);
  font-size: 0.86rem;
  line-height: 1.5;
  word-break: break-all;
}

.home-config-adder {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.search-grid {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.module-action-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.compact-button {
  min-width: 108px;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 999px;
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

@media (max-width: 1180px) {
  .hero-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 980px) {
  .config-panel-head,
  .config-subcard-head,
  .home-config-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .home-config-adder,
  .search-grid,
  .module-action-row {
    grid-template-columns: 1fr;
  }
}
</style>
