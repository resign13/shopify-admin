<template>
  <AdminLayout>
    <div class="admin-page">
      <section class="admin-card">
        <div class="product-page-head">
          <div>
            <h1>商品管理</h1>
            <p class="small-note">支持按商品分类筛选，并按商品标题、商品编码或 SKU 搜索。</p>
          </div>
          <button class="admin-button" type="button" @click="goCreate">新建商品</button>
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
              placeholder="请输入商品标题、商品编码或 SKU"
            />
          </label>

          <div class="filter-actions">
            <button class="admin-button ghost" type="submit">查询</button>
          </div>
        </form>

        <div class="small-note result-note">共找到 {{ filteredProducts.length }} 个商品</div>

        <div v-if="!filteredProducts.length" class="empty-state">暂无符合条件的商品。</div>

        <div v-else class="product-list-grid">
          <article v-for="item in paginatedProducts" :key="item.id" class="product-item-card">
            <div class="product-item-main">
              <div class="product-item-cover">
                <img :src="item.image" :alt="item.name?.zh || item.productCode" />
              </div>

              <div class="product-item-copy">
                <strong>{{ item.name?.zh || item.productCode || item.sku }}</strong>
                <p>{{ item.productCode || '--' }} / {{ item.colorName || '未设置颜色' }}</p>
                <p>{{ item.categoryLabel || item.categoryKey }}</p>
                <p>库存 {{ item.stock }} / ${{ item.price }}</p>
              </div>
            </div>

            <div class="product-item-actions">
              <button class="admin-button ghost" type="button" @click="goEdit(item.id)">编辑</button>
              <button class="admin-button ghost" type="button" @click="openDeleteDialog(item)">
                删除
              </button>
            </div>
          </article>
        </div>

        <PaginationBar
          v-if="filteredProducts.length"
          :page="currentPage"
          :page-size="pageSize"
          :total-items="filteredProducts.length"
          item-label="个商品"
          @update:page="currentPage = $event"
          @update:page-size="pageSize = $event"
        />
      </section>
    </div>
    <div v-if="deleteTarget" class="confirm-mask" @click.self="closeDeleteDialog">
      <div class="confirm-dialog">
        <h3>删除商品</h3>
        <p>
          确认删除商品“{{ deleteTarget.name?.zh || deleteTarget.productCode || deleteTarget.sku }}”吗？
          删除后会直接从数据库移除，无法恢复。
        </p>
        <p class="small-note">如果商品已经产生订单，系统会阻止删除以保护订单历史数据。</p>
        <div class="confirm-actions">
          <button class="admin-button ghost" type="button" :disabled="deleting" @click="closeDeleteDialog">
            取消
          </button>
          <button class="admin-button danger" type="button" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? '删除中...' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </AdminLayout>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import AdminLayout from '../components/AdminLayout.vue'
import PaginationBar from '../components/PaginationBar.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const router = useRouter()
const selectedCategoryDraft = ref('')
const selectedCategory = ref('')
const keywordDraft = ref('')
const keyword = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const deleteTarget = ref(null)
const deleting = ref(false)

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

function goCreate() {
  router.push('/products/new')
}

function goEdit(id) {
  router.push(`/products/${id}/edit`)
}

function openDeleteDialog(item) {
  deleteTarget.value = item
}

function closeDeleteDialog() {
  if (deleting.value) return
  deleteTarget.value = null
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return
  deleting.value = true
  try {
    await admin.deleteProduct(deleteTarget.value.id)
    deleteTarget.value = null
  } catch (error) {
    window.alert(error.message || '删除商品失败')
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  await Promise.all([admin.loadProducts(), admin.loadCategories()])
})
</script>

<style scoped>
.product-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.product-page-head h1 {
  margin: 0 0 6px;
}

.filter-row {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) auto;
  gap: 14px;
  margin-bottom: 10px;
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

.result-note {
  margin-bottom: 14px;
}

.product-list-grid {
  display: grid;
  gap: 14px;
}

.product-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.82);
}

.product-item-main {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.product-item-cover {
  width: 88px;
  height: 110px;
  overflow: hidden;
  border: 1px solid rgba(110, 85, 61, 0.16);
  background: #f6f2ec;
  flex-shrink: 0;
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

.product-item-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.empty-state {
  padding: 18px;
  color: var(--muted);
  border: 1px dashed var(--line);
  background: rgba(255, 255, 255, 0.62);
}

.confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(33, 24, 18, 0.32);
}

.confirm-dialog {
  width: min(460px, 100%);
  padding: 24px;
  border-radius: 24px;
  border: 1px solid var(--line);
  background: #fff;
  box-shadow: 0 24px 60px rgba(33, 24, 18, 0.16);
}

.confirm-dialog h3,
.confirm-dialog p {
  margin: 0;
}

.confirm-dialog h3 {
  margin-bottom: 12px;
}

.confirm-dialog p + p {
  margin-top: 10px;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.admin-button.danger {
  color: #fff;
  border-color: #1f1712;
  background: #1f1712;
}

@media (max-width: 900px) {
  .filter-row {
    grid-template-columns: 1fr;
  }

  .product-page-head,
  .product-item-card {
    flex-direction: column;
    align-items: flex-start;
  }

  .product-item-actions {
    width: 100%;
  }
}
</style>
