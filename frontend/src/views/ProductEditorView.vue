<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card product-editor-panel">
        <div class="editor-page-head">
          <div>
            <h1>{{ form.editingId ? '编辑商品' : '新建商品' }}</h1>
            <p class="small-note">按分类、标题、颜色、尺码完整维护商品资料。</p>
          </div>
          <button class="admin-button ghost" type="button" @click="goBack">返回商品管理</button>
        </div>

        <form class="editor-form" @submit.prevent="save">
          <div class="editor-section">
            <div class="editor-section-head">
              <strong>基础信息</strong>
            </div>

            <div class="editor-grid">
              <label class="field-label">
                <span>商品分类</span>
                <select v-model="form.categoryKey" class="admin-field">
                  <option value="" disabled>请选择分类</option>
                  <option v-for="category in admin.categories" :key="category.key" :value="category.key">
                    {{ category.labels?.zh || category.label || category.key }}
                  </option>
                </select>
              </label>

              <label class="field-label">
                <span>商品唯一编码</span>
                <input v-model.trim="form.familyCode" class="admin-field" placeholder="例如 ZM393" />
              </label>

              <label class="field-label full-span">
                <span>商品标题</span>
                <input v-model.trim="form.title" class="admin-field" placeholder="例如 High Waist Wide Leg Jeans" />
              </label>

              <label class="inline-check">
                <input v-model="form.featured" type="checkbox" />
                首页推荐
              </label>
            </div>
          </div>

          <div class="editor-section">
            <div class="editor-section-head">
              <strong>颜色与图片</strong>
              <span class="small-note">先勾选常用颜色，也可以新增特殊颜色。每个颜色需要 3-10 张图。</span>
            </div>

            <div class="custom-option-row">
              <input v-model.trim="customColorName" class="admin-field" placeholder="特殊颜色名称，例如 雾霾蓝" />
              <input v-model="customColorHex" class="admin-field color-input" type="color" />
              <button class="admin-button ghost mini-button" type="button" @click="addCustomColor">添加颜色</button>
            </div>

            <div class="color-picker-grid">
              <label v-for="color in colorPalette" :key="color.name" class="color-check">
                <input
                  type="checkbox"
                  :checked="isColorSelected(color.name)"
                  @change="toggleColor(color, $event.target.checked)"
                />
                <span class="color-swatch" :style="{ background: color.hex }"></span>
                {{ color.name }}
              </label>
            </div>

            <div v-if="selectedVariants.length" class="color-table-wrap">
              <table class="color-table">
                <thead>
                  <tr>
                    <th>颜色</th>
                    <th>SKU 编码</th>
                    <th>图片（3-10 张）</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(variant, variantIndex) in selectedVariants" :key="variant.localId">
                    <td class="color-name-cell">{{ variant.colorName }}</td>
                    <td>
                      <input v-model.trim="variant.productCode" class="admin-field compact-field" placeholder="填写货号" />
                    </td>
                    <td>
                      <div class="variant-image-tools">
                        <div class="thumb-strip">
                          <div v-for="(image, imageIndex) in variant.imageUrls" :key="image" class="table-thumb">
                            <img :src="image" :alt="variant.colorName" />
                            <button type="button" title="删除图片" @click="removeVariantImage(variantIndex, imageIndex)">x</button>
                          </div>
                        </div>
                        <button class="admin-button ghost mini-button" type="button" @click="pickVariantFiles(variantIndex)">
                          选择图片
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-else class="empty-state">请先选择商品颜色</div>
          </div>

          <div class="editor-section">
            <div class="editor-section-head">
              <strong>尺码选择</strong>
              <span class="small-note">勾选常用尺码，也可以新增特殊尺码。</span>
            </div>

            <div class="custom-option-row custom-size-row">
              <input v-model.trim="customSizeName" class="admin-field" placeholder="特殊尺码，例如 31 或 Tall L" />
              <button class="admin-button ghost mini-button" type="button" @click="addCustomSize">添加尺码</button>
            </div>

            <div class="size-check-grid">
              <label v-for="size in sizeOptions" :key="size" class="size-check">
                <input type="checkbox" :checked="form.sizes.includes(size)" @change="toggleSize(size, $event.target.checked)" />
                {{ size }}
              </label>
            </div>
          </div>

          <div class="editor-section">
            <div class="editor-section-head">
              <strong>颜色 / 尺码价格与库存</strong>
              <span class="small-note">每个颜色对应的每个尺码都可以单独设置价格和库存。</span>
            </div>

            <div class="bulk-fill-row">
              <div class="bulk-fill-card">
                <span>一键填写价格</span>
                <input
                  v-model.number="bulkPriceValue"
                  class="admin-field compact-field"
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="例如 89.99"
                />
                <button class="admin-button ghost mini-button" type="button" @click="fillAllPrices">应用到全部</button>
              </div>

              <div class="bulk-fill-card">
                <span>一键填写库存</span>
                <input
                  v-model.number="bulkStockValue"
                  class="admin-field compact-field"
                  type="number"
                  min="0"
                  step="1"
                  placeholder="默认 1"
                />
                <button class="admin-button ghost mini-button" type="button" @click="fillAllStocks">应用到全部</button>
              </div>
            </div>

            <div v-if="selectedVariants.length && form.sizes.length" class="price-matrix-wrap">
              <table class="price-matrix">
                <thead>
                  <tr>
                    <th>颜色</th>
                    <th v-for="size in form.sizes" :key="size">{{ size }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="variant in selectedVariants" :key="variant.localId">
                    <td>{{ variant.colorName }}</td>
                    <td v-for="size in form.sizes" :key="size">
                      <div class="matrix-cell-fields">
                        <input
                          v-model.number="variant.sizePrices[size]"
                          class="admin-field price-field"
                          type="number"
                          min="0"
                          step="0.01"
                          placeholder="价格"
                        />
                        <input
                          v-model.number="variant.sizeStocks[size]"
                          class="admin-field price-field"
                          type="number"
                          min="0"
                          step="1"
                          placeholder="库存"
                        />
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-else class="empty-state">选择颜色和尺码后再填写价格与库存</div>
          </div>

          <div class="editor-section">
            <div class="editor-section-head">
              <strong>商品图片资料</strong>
              <span class="small-note">每个产品上传 1 张尺码表图和 1 张商品信息描述图。</span>
            </div>

            <div class="asset-grid">
              <div class="upload-box">
                <div class="upload-box-head">
                  <strong>尺码表图</strong>
                  <button class="admin-button ghost mini-button" type="button" @click="pickSingleFile('sizeChart')">上传</button>
                </div>
                <div v-if="form.sizeChartImage" class="image-preview">
                  <img :src="form.sizeChartImage" alt="尺码表图" />
                </div>
              </div>

              <div class="upload-box">
                <div class="upload-box-head">
                  <strong>商品信息描述图</strong>
                  <button class="admin-button ghost mini-button" type="button" @click="pickSingleFile('descriptionImage')">上传</button>
                </div>
                <div v-if="form.descriptionImage" class="image-preview">
                  <img :src="form.descriptionImage" alt="商品信息描述图" />
                </div>
              </div>
            </div>
          </div>

          <p v-if="formError" class="error-text">{{ formError }}</p>

          <div class="submit-row">
            <button class="admin-button submit-button" type="submit" :disabled="saving">
              {{ saving ? '提交中...' : form.editingId ? '保存修改' : '提交商品' }}
            </button>
            <button class="admin-button ghost" type="button" @click="goBack">取消</button>
          </div>
        </form>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const route = useRoute()
const router = useRouter()
const formError = ref('')
const saving = ref(false)
const customColorName = ref('')
const customColorHex = ref('#d6c2ad')
const customSizeName = ref('')
const bulkPriceValue = ref('')
const bulkStockValue = ref(1)

const colorPalette = ref([
  { name: '白色', hex: '#ffffff' },
  { name: '黑色', hex: '#111111' },
  { name: '米白色', hex: '#f4efe4' },
  { name: '卡其色', hex: '#c4a484' },
  { name: '红色', hex: '#d33b32' },
  { name: '蓝色', hex: '#2f6db5' },
  { name: '牛仔蓝', hex: '#6c8fb4' },
  { name: '灰色', hex: '#858585' },
  { name: '粉色', hex: '#f4b6c6' },
])

const sizeOptions = ref(['XS', 'S', 'M', 'L', 'XL', 'XXL', '25', '26', '27', '28', '29', '30', 'one-size'])


function makeVariant(color, sizes = ['S', 'M', 'L', 'XL']) {
  const sizePrices = {}
  const sizeStocks = {}
  sizes.forEach((size) => {
    sizePrices[size] = ''
    sizeStocks[size] = ''
  })
  return {
    localId: crypto.randomUUID(),
    productCode: '',
    colorName: color.name,
    colorHex: color.hex,
    imageUrls: [],
    sizePrices,
    sizeStocks,
  }
}

function emptyForm() {
  return {
    editingId: null,
    categoryKey: '',
    familyCode: '',
    title: '',
    origin: 'China',
    featured: false,
    sizes: ['S', 'M', 'L', 'XL'],
    sizeChartImage: '',
    descriptionImage: '',
    variants: [],
  }
}

const form = reactive(emptyForm())
const selectedVariants = computed(() => form.variants)

function goBack() {
  router.push('/products')
}

function resetForm() {
  Object.assign(form, emptyForm())
  formError.value = ''
  saving.value = false
  normalizeBaseFields()
}

function syncVariantSizePrices() {
  for (const variant of form.variants) {
    const nextPrices = {}
    const nextStocks = {}
    for (const size of form.sizes) {
      nextPrices[size] = variant.sizePrices?.[size] ?? ''
      nextStocks[size] = variant.sizeStocks?.[size] ?? ''
    }
    variant.sizePrices = nextPrices
    variant.sizeStocks = nextStocks
  }
}

function normalizeBaseFields() {
  if (!form.categoryKey && admin.categories.length) {
    form.categoryKey = admin.categories[0].key
  }
  syncVariantSizePrices()
}

function isColorSelected(colorName) {
  return form.variants.some((variant) => variant.colorName === colorName)
}

function toggleColor(color, checked) {
  if (checked) {
    if (!isColorSelected(color.name)) {
      form.variants.push(makeVariant(color, form.sizes))
    }
    return
  }
  const index = form.variants.findIndex((variant) => variant.colorName === color.name)
  if (index >= 0) {
    form.variants.splice(index, 1)
  }
}

function addCustomColor() {
  const name = customColorName.value.trim()
  if (!name) {
    formError.value = '请填写特殊颜色名称'
    return
  }
  if (!colorPalette.value.some((color) => color.name === name)) {
    colorPalette.value.push({ name, hex: customColorHex.value || '#d6c2ad' })
  }
  toggleColor({ name, hex: customColorHex.value || '#d6c2ad' }, true)
  customColorName.value = ''
  customColorHex.value = '#d6c2ad'
  formError.value = ''
}

function toggleSize(size, checked) {
  if (checked) {
    if (!form.sizes.includes(size)) {
      form.sizes.push(size)
    }
  } else {
    form.sizes = form.sizes.filter((item) => item !== size)
  }
  syncVariantSizePrices()
}

function addCustomSize() {
  const size = customSizeName.value.trim()
  if (!size) {
    formError.value = '请填写特殊尺码'
    return
  }
  if (!sizeOptions.value.includes(size)) {
    sizeOptions.value.push(size)
  }
  toggleSize(size, true)
  customSizeName.value = ''
  formError.value = ''
}



function fillAllPrices() {
  if (bulkPriceValue.value === '' || bulkPriceValue.value === null || bulkPriceValue.value === undefined) {
    formError.value = '请先填写要批量应用的价格'
    return
  }
  if (Number(bulkPriceValue.value) < 0) {
    formError.value = '批量价格不能小于 0'
    return
  }
  for (const variant of form.variants) {
    for (const size of form.sizes) {
      variant.sizePrices[size] = Number(bulkPriceValue.value)
    }
  }
  formError.value = ''
}

function fillAllStocks() {
  if (bulkStockValue.value === '' || bulkStockValue.value === null || bulkStockValue.value === undefined) {
    formError.value = '请先填写要批量应用的库存'
    return
  }
  if (Number(bulkStockValue.value) < 0) {
    formError.value = '批量库存不能小于 0'
    return
  }
  for (const variant of form.variants) {
    for (const size of form.sizes) {
      variant.sizeStocks[size] = Number(bulkStockValue.value)
    }
  }
  formError.value = ''
}

async function pickSingleFile(target) {
  formError.value = ''
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    try {
      const [url] = await admin.uploadFiles([file])
      if (target === 'sizeChart') form.sizeChartImage = url
      if (target === 'descriptionImage') form.descriptionImage = url
    } catch (error) {
      formError.value = error.message || '图片上传失败'
    }
  }
  input.click()
}

async function pickVariantFiles(index) {
  formError.value = ''
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.multiple = true
  input.onchange = async () => {
    const files = Array.from(input.files || [])
    if (!files.length) return
    const variant = form.variants[index]
    const remaining = Math.max(0, 10 - variant.imageUrls.length)
    const selected = files.slice(0, remaining)
    try {
      const urls = await admin.uploadFiles(selected)
      variant.imageUrls = [...variant.imageUrls, ...urls].slice(0, 10)
    } catch (error) {
      formError.value = error.message || '图片上传失败'
    }
  }
  input.click()
}

function removeVariantImage(variantIndex, imageIndex) {
  form.variants[variantIndex].imageUrls.splice(imageIndex, 1)
}

function validateForm() {
  if (!form.categoryKey) return '请选择商品分类'
  if (!form.familyCode) return '请填写商品唯一编码'
  if (!form.title) return '请填写商品标题'
  if (!form.variants.length) return '请至少选择一个颜色'
  if (!form.sizes.length) return '请至少选择一个尺码'
  if (!form.sizeChartImage) return '请上传尺码表图'
  if (!form.descriptionImage) return '请上传商品信息描述图'


  for (const [index, variant] of form.variants.entries()) {
    const row = index + 1
    if (!variant.productCode) return `请填写第 ${row} 个颜色的 SKU 编码`
    if (variant.imageUrls.length < 3 || variant.imageUrls.length > 10) {
      return `第 ${row} 个颜色需要上传 3-10 张图片`
    }
    for (const size of form.sizes) {
      const price = variant.sizePrices[size]
      const stock = variant.sizeStocks[size]
      if (price === '' || price === null || price === undefined) {
        return `请填写 ${variant.colorName} / ${size} 的价格`
      }
      if (Number(price) < 0) {
        return `${variant.colorName} / ${size} 的价格不能小于 0`
      }
      if (stock === '' || stock === null || stock === undefined) {
        return `请填写 ${variant.colorName} / ${size} 的库存`
      }
      if (Number(stock) < 0) {
        return `${variant.colorName} / ${size} 的库存不能小于 0`
      }
    }
  }
  return ''
}

async function save() {
  if (!admin.categories.length) {
    try {
      await admin.loadCategories()
    } catch (error) {
      formError.value = error.message || '加载商品分类失败'
      return
    }
  }

  if (!form.categoryKey && admin.categories.length) {
    form.categoryKey = admin.categories[0].key
  }

  if (!form.categoryKey) {
    formError.value = '请先到分类管理创建并选择一个商品分类'
    return
  }

  formError.value = validateForm()
  if (formError.value) return

  saving.value = true
  try {
    const familyCode = form.familyCode.trim()
    const basePayload = {
      categoryKey: form.categoryKey,
      familyCode,
      title: form.title.trim(),
      origin: form.origin,
      featured: form.featured,
      sizes: [...form.sizes],
      sizeChartImage: form.sizeChartImage,
      descriptionImage: form.descriptionImage,
    }

    const variants = form.variants.map((variant) => {
      const productCode = variant.productCode.trim()
      const sizePrices = form.sizes.map((size) => ({
        sizeCode: size,
        price: Number(variant.sizePrices[size]),
        stock: Number(variant.sizeStocks[size]),
      }))
      return {
        productCode,
        sku: productCode,
        slug: productCode.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
        colorGroup: familyCode,
        colorName: variant.colorName.trim(),
        colorHex: variant.colorHex.trim(),
        stock: sizePrices.reduce((total, item) => total + Number(item.stock || 0), 0),
        imageUrls: [...variant.imageUrls],
        sizePrices,
      }
    })

    const payload =
      form.editingId && variants.length === 1
        ? {
            ...basePayload,
            id: form.editingId,
            ...variants[0],
            sizePrices: variants[0].sizePrices,
            image: variants[0].imageUrls[0],
            gallery: variants[0].imageUrls,
          }
        : { ...basePayload, variants }

    await admin.saveProduct(payload)
    formError.value = ''
    router.push('/products')
  } catch (error) {
    formError.value = error.message || '提交商品失败'
  } finally {
    saving.value = false
  }
}

function ensurePaletteColor(colorName, colorHex) {
  if (!colorName) return
  if (!colorPalette.value.some((color) => color.name === colorName)) {
    colorPalette.value.push({ name: colorName, hex: colorHex || '#d6c2ad' })
  }
}

function ensureSizeOptions(sizes) {
  for (const size of sizes || []) {
    if (size && !sizeOptions.value.includes(size)) {
      sizeOptions.value.push(size)
    }
  }
}

function populateForm(item) {
  resetForm()
  form.categoryKey = item.categoryKey
  form.familyCode = item.colorGroup || item.productCode || item.slug
  form.title = item.name?.zh || item.name?.en || ''
  form.origin = item.origin || 'China'
  form.featured = Boolean(item.featured)
  form.sizes = [...(item.sizes || ['S', 'M', 'L', 'XL'])]
  ensureSizeOptions(form.sizes)
  form.sizeChartImage = item.sizeChartImage || ''
  form.descriptionImage = item.descriptionImage || ''
  form.editingId = item.id
  ensurePaletteColor(item.colorName, item.colorHex)
  form.variants = [
    {
      localId: crypto.randomUUID(),
      productCode: item.productCode || item.slug,
      colorName: item.colorName || '未命名颜色',
      colorHex: item.colorHex || '#ffffff',
      imageUrls: [...(item.gallery || [item.image]).filter(Boolean)],
      sizePrices: Object.fromEntries((item.sizePrices || []).map((row) => [row.sizeCode, row.price])),
      sizeStocks: Object.fromEntries((item.sizePrices || []).map((row) => [row.sizeCode, row.stock ?? 0])),
    },
  ]
  syncVariantSizePrices()
}

async function initializePage() {
  await Promise.all([admin.loadProducts(), admin.loadCategories()])
  const productId = Number(route.params.id || 0)
  if (productId) {
    const item = admin.products.find((product) => product.id === productId)
    if (item) {
      populateForm(item)
      return
    }
    formError.value = '未找到要编辑的商品'
    return
  }
  resetForm()
}

onMounted(async () => {
  await initializePage()
})

watch(
  () => route.fullPath,
  async () => {
    await initializePage()
  },
)
</script>

<style scoped>
.editor-page-head,
.editor-section-head,
.upload-box-head,
.variant-image-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.editor-page-head {
  margin-bottom: 18px;
}

.editor-page-head h1 {
  margin: 0 0 6px;
}

.field-label {
  display: grid;
  gap: 8px;
  color: var(--muted);
  font-size: 0.92rem;
}

.editor-section {
  display: grid;
  gap: 14px;
  padding: 18px 0;
  border-top: 1px solid var(--line);
}

.editor-section:first-child {
  border-top: 0;
  padding-top: 0;
}

.custom-option-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto auto;
  gap: 10px;
  align-items: center;
  max-width: 560px;
}

.custom-size-row {
  grid-template-columns: minmax(180px, 1fr) auto;
}

.bulk-fill-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 12px;
}

.bulk-fill-card {
  display: grid;
  grid-template-columns: auto minmax(120px, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.72);
}

.color-input {
  width: 54px;
  min-width: 54px;
  padding: 4px;
}

.inline-check,
.color-check,
.size-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.color-picker-grid,
.size-check-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(98px, 1fr));
  gap: 12px 22px;
}

.color-swatch {
  width: 14px;
  height: 14px;
  border: 1px solid rgba(46, 33, 24, 0.18);
}

.color-table-wrap,
.price-matrix-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.82);
}

.color-table,
.price-matrix {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
}

.color-table th,
.color-table td,
.price-matrix th,
.price-matrix td {
  border: 1px solid rgba(110, 85, 61, 0.16);
  padding: 10px;
  text-align: center;
  vertical-align: top;
}

.color-table th,
.price-matrix th {
  background: #eeeae5;
  color: var(--text);
  font-weight: 700;
}

.color-name-cell {
  width: 112px;
  font-weight: 700;
}

.compact-field {
  min-height: 38px;
  border-radius: 4px;
}

.variant-image-tools {
  align-items: flex-start;
}

.thumb-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 68px;
}

.table-thumb {
  position: relative;
  width: 58px;
  height: 76px;
  border: 1px solid rgba(110, 85, 61, 0.2);
  background: white;
}

.table-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.table-thumb button {
  position: absolute;
  right: -6px;
  top: -8px;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 999px;
  background: #1d1a17;
  color: white;
  cursor: pointer;
}

.mini-button {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 4px;
  white-space: nowrap;
}

.matrix-cell-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(92px, 1fr));
  gap: 8px;
}

.price-field {
  min-width: 92px;
  min-height: 38px;
  border-radius: 4px;
}


.icon-button {
  width: 38px;
  min-height: 38px;
  padding: 0;
  border-radius: 999px;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.upload-box {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.74);
}

.image-preview {
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: #f4f1ed;
}

.image-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.empty-state {
  padding: 18px;
  color: var(--muted);
  border: 1px dashed var(--line);
  background: rgba(255, 255, 255, 0.62);
}

.error-text {
  color: #a73f35;
  margin: 0;
}

.submit-row {
  display: flex;
  gap: 12px;
}

@media (max-width: 1180px) {
  .asset-grid {
    grid-template-columns: 1fr;
  }

  .color-picker-grid,
  .size-check-grid {
    grid-template-columns: repeat(3, minmax(98px, 1fr));
  }
}

@media (max-width: 720px) {
  .color-picker-grid,
  .size-check-grid,
  .custom-option-row,
  .custom-size-row,
  .bulk-fill-row {
    grid-template-columns: 1fr;
  }

  .bulk-fill-card {
    grid-template-columns: 1fr;
  }

  .editor-page-head,
  .editor-section-head,
  .variant-image-tools,
  .submit-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
