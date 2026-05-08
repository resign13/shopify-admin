<template>
  <AdminLayout>
    <div class="admin-page two-col">
      <section class="admin-card">
        <h1>分类管理</h1>
        <div v-if="!admin.categories.length" class="empty-state">暂无分类</div>
        <div v-for="item in admin.categories" :key="item.id" class="list-row stack-row">
          <div>
            <strong>{{ item.labels?.en || item.label || item.key }}</strong>
            <p>{{ item.key }} / 排序 {{ item.sortOrder }}</p>
            <p>关联商品 {{ item.productCount }}</p>
          </div>
          <div class="inline-actions">
            <button class="admin-button ghost" type="button" @click="editItem(item)">编辑</button>
            <button class="admin-button ghost" type="button" @click="removeItem(item.id)">删除</button>
          </div>
        </div>
      </section>

      <section class="admin-card">
        <h2>{{ form.id ? '编辑分类' : '新建分类' }}</h2>
        <form class="editor-form" @submit.prevent="save">
          <input
            v-model.trim="form.key"
            class="admin-field"
            placeholder="分类编码，例如 womenswear"
          />
          <input
            v-model.number="form.sortOrder"
            class="admin-field"
            type="number"
            min="0"
            placeholder="排序值"
          />
          <textarea
            v-model.trim="form.labels.en"
            class="admin-field admin-textarea"
            placeholder="英文分类名"
          ></textarea>
          <textarea
            v-model.trim="form.labels.zh"
            class="admin-field admin-textarea"
            placeholder="中文分类名"
          ></textarea>
          <p v-if="errorText" class="admin-error">{{ errorText }}</p>
          <button class="admin-button" type="submit">
            {{ saving ? '保存中...' : '保存分类' }}
          </button>
        </form>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const saving = ref(false)
const errorText = ref('')

function emptyForm() {
  return {
    id: null,
    key: '',
    sortOrder: 0,
    labels: { zh: '', en: '' },
  }
}

const form = reactive(emptyForm())

function resetForm() {
  Object.assign(form, emptyForm())
  errorText.value = ''
}

function editItem(item) {
  form.id = item.id
  form.key = item.key
  form.sortOrder = item.sortOrder
  form.labels = {
    zh: item.labels?.zh || '',
    en: item.labels?.en || '',
  }
  errorText.value = ''
}

async function save() {
  errorText.value = ''
  saving.value = true
  try {
    await admin.saveCategory({
      id: form.id,
      key: form.key.trim().toLowerCase(),
      sortOrder: Number(form.sortOrder || 0),
      labels: { ...form.labels },
    })
    resetForm()
  } catch (error) {
    errorText.value = error.message || '保存分类失败'
  } finally {
    saving.value = false
  }
}

async function removeItem(id) {
  errorText.value = ''
  try {
    await admin.deleteCategory(id)
    if (form.id === id) {
      resetForm()
    }
  } catch (error) {
    errorText.value = error.message || '删除分类失败'
  }
}

onMounted(() => {
  admin.loadCategories()
})
</script>
