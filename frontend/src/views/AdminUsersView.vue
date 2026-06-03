<template>
  <AdminLayout>
    <div class="admin-page two-col">
      <section class="admin-card">
        <h1>后台账号管理</h1>
        <p class="small-note">管理员拥有全部权限，外贸部不可管理账号，仓库部仅可进入订单管理，客户仅可查看库存管理。</p>

        <div v-for="item in admin.adminUsers" :key="item.id" class="list-row stack-row">
          <div>
            <strong>{{ item.name }}</strong>
            <p>{{ item.email }}</p>
            <p class="small-note">{{ roleLabelMap[item.role] || item.role }} · {{ statusLabelMap[item.status] || item.status }}</p>
          </div>

          <div class="inline-actions">
            <button class="admin-button ghost" type="button" @click="editItem(item)">编辑</button>
            <button
              class="admin-button ghost"
              type="button"
              :disabled="auth.user?.id === item.id"
              @click="admin.deleteAdminUser(item.id)"
            >
              删除
            </button>
          </div>
        </div>
      </section>

      <section class="admin-card">
        <h2>{{ form.id ? '编辑后台账号' : '新建后台账号' }}</h2>
        <form class="editor-form" @submit.prevent="save">
          <input v-model.trim="form.name" class="admin-field" placeholder="姓名" />
          <input v-model.trim="form.email" class="admin-field" placeholder="邮箱" />

          <select v-model="form.role" class="admin-field">
            <option value="admin">管理员</option>
            <option value="sales">外贸部</option>
            <option value="warehouse">仓库部</option>
            <option value="customer">客户</option>
          </select>

          <select v-model="form.status" class="admin-field" :disabled="auth.user?.id === form.id">
            <option value="active">启用</option>
            <option value="disabled">停用</option>
          </select>

          <input
            v-model.trim="form.password"
            class="admin-field"
            type="password"
            :placeholder="form.id ? '密码留空则不修改' : '请输入登录密码'"
          />

          <div class="inline-actions">
            <button class="admin-button" type="submit">保存后台账号</button>
            <button v-if="form.id" class="admin-button ghost" type="button" @click="resetForm">取消编辑</button>
          </div>
        </form>
      </section>
    </div>
  </AdminLayout>
</template>

<script setup>
import { onMounted, reactive } from 'vue'

import AdminLayout from '../components/AdminLayout.vue'
import { useAdminAuthStore } from '../stores/auth'
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()
const auth = useAdminAuthStore()

const roleLabelMap = {
  admin: '管理员',
  sales: '外贸部',
  warehouse: '仓库部',
  customer: '客户',
}

const statusLabelMap = {
  active: '启用',
  disabled: '停用',
}

function emptyForm() {
  return {
    id: null,
    name: '',
    email: '',
    password: '',
    role: 'sales',
    status: 'active',
  }
}

const form = reactive(emptyForm())

function editItem(item) {
  Object.assign(form, {
    id: item.id,
    name: item.name || '',
    email: item.email || '',
    password: '',
    role: item.role || 'sales',
    status: item.status || 'active',
  })
}

function resetForm() {
  Object.assign(form, emptyForm())
}

async function save() {
  await admin.saveAdminUser({ ...form })
  resetForm()
}

onMounted(() => {
  admin.loadAdminUsers()
})
</script>
