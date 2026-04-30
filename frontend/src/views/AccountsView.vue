<template>
  <AdminLayout>
    <div class="admin-page two-col">
      <section class="admin-card">
        <h1>商城账号管理</h1>
        <div v-for="item in admin.storeUsers" :key="item.id" class="list-row stack-row">
          <div>
            <strong>{{ item.name }}</strong>
            <p>{{ item.companyName }} · {{ item.email }}</p>
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
          <input v-model.trim="form.name" class="admin-field" placeholder="姓名" />
          <input v-model.trim="form.companyName" class="admin-field" placeholder="公司名称" />
          <input v-model.trim="form.email" class="admin-field" placeholder="邮箱" />
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
            <button class="admin-button" type="submit">保存商城账号</button>
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
import { useAdminStore } from '../stores/admin'

const admin = useAdminStore()

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
  Object.assign(form, { ...item, password: '' })
}

function resetForm() {
  Object.assign(form, emptyForm())
}

async function save() {
  await admin.saveStoreUser({ ...form })
  resetForm()
}

onMounted(() => {
  admin.loadStoreUsers()
})
</script>
