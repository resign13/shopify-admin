<template>
  <AdminLayout>
    <div class="admin-page two-col">
      <section class="admin-card">
        <h1>商城账号管理</h1>
        <div v-for="item in admin.storeUsers" :key="item.id" class="list-row stack-row">
          <div>
            <strong>{{ item.name }}</strong>
            <p>{{ item.companyName ? `${item.companyName} · ${item.email}` : item.email }}</p>
            <p class="small-note">{{ item.status === 'active' ? '启用' : '停用' }}</p>
          </div>

          <div class="inline-actions">
            <button class="admin-button ghost" type="button" @click="editItem(item)">编辑</button>
            <button class="admin-button ghost" type="button" @click="admin.deleteStoreUser(item.id)">删除</button>
          </div>
        </div>
      </section>

      <section class="admin-card">
        <h2>{{ form.id ? '编辑商城账号' : '新建商城账号' }}</h2>
        <form class="editor-form" @submit.prevent="save">
          <p v-if="message" class="small-note success-text">{{ message }}</p>
          <p v-if="error" class="admin-error">{{ error }}</p>
          <input v-model.trim="form.name" class="admin-field" placeholder="姓名" />
          <input v-model.trim="form.companyName" class="admin-field" placeholder="公司名称（选填）" />
          <input v-model.trim="form.email" class="admin-field" placeholder="登录账号 / 邮箱" />
          <input
            v-model.trim="form.password"
            class="admin-field"
            type="password"
            :placeholder="form.id ? '密码留空则不修改' : '请输入登录密码'"
          />
          <select v-model="form.status" class="admin-field">
            <option value="active">启用</option>
            <option value="disabled">停用</option>
          </select>

          <div class="inline-actions">
            <button class="admin-button" type="submit" :disabled="saving">{{ saving ? '保存中...' : '保存商城账号' }}</button>
            <button v-if="form.id" class="admin-button ghost" type="button" @click="resetForm">取消编辑</button>
          </div>
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
const error = ref('')
const message = ref('')
const saving = ref(false)

function emptyForm() {
  return {
    id: null,
    name: '',
    companyName: '',
    email: '',
    password: '',
    status: 'active',
  }
}

const form = reactive(emptyForm())

function editItem(item) {
  error.value = ''
  message.value = ''
  Object.assign(form, { ...item, password: '' })
}

function resetForm() {
  error.value = ''
  message.value = ''
  Object.assign(form, emptyForm())
}

function validateForm() {
  if (!form.name.trim()) return '请填写姓名。'
  if (!form.email.trim()) return '请填写登录账号 / 邮箱。'
  if (!form.id && !form.password.trim()) return '请填写登录密码。'
  return ''
}

async function save() {
  error.value = validateForm()
  message.value = ''
  if (error.value || saving.value) return

  saving.value = true
  try {
    await admin.saveStoreUser({ ...form })
    const actionText = form.id ? '更新' : '创建'
    resetForm()
    message.value = `商城账号已${actionText}。`
  } catch (exc) {
    error.value = exc?.message || '保存商城账号失败，请检查填写内容。'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  admin.loadStoreUsers()
})
</script>

<style scoped>
.success-text { color: #3d8f54; }
</style>

