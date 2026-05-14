<template>
  <AdminLayout>
    <div class="admin-page two-col">
      <section class="admin-card">
        <h1>轮播图管理</h1>
        <div v-for="item in admin.banners" :key="item.id" class="list-row stack-row">
          <div>
            <strong>{{ item.title.zh }}</strong>
            <p>{{ item.ctaPath }}</p>
          </div>
          <div class="inline-actions">
            <button class="admin-button ghost" type="button" @click="editItem(item)">编辑</button>
            <button class="admin-button ghost" type="button" @click="admin.deleteBanner(item.id)">删除</button>
          </div>
        </div>
      </section>

      <section class="admin-card">
        <h2>{{ form.id ? '编辑轮播图' : '新建轮播图' }}</h2>
        <form class="editor-form" @submit.prevent="save">
          <input v-model.trim="form.image" class="admin-field" placeholder="图片 URL" />
          <input v-model.trim="form.ctaPath" class="admin-field" placeholder="按钮跳转路径" />
          <textarea v-model.trim="form.title.zh" class="admin-field admin-textarea" placeholder="中文标题"></textarea>
          <textarea v-model.trim="form.title.en" class="admin-field admin-textarea" placeholder="英文标题"></textarea>
          <textarea v-model.trim="form.subtitle.zh" class="admin-field admin-textarea" placeholder="中文副标题"></textarea>
          <textarea v-model.trim="form.subtitle.en" class="admin-field admin-textarea" placeholder="英文副标题"></textarea>
          <textarea v-model.trim="form.ctaLabel.zh" class="admin-field admin-textarea" placeholder="中文按钮文案"></textarea>
          <textarea v-model.trim="form.ctaLabel.en" class="admin-field admin-textarea" placeholder="英文按钮文案"></textarea>
          <button class="admin-button" type="submit">保存轮播图</button>
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
    image: '',
    ctaPath: '/shop',
    title: { zh: '', en: '' },
    subtitle: { zh: '', en: '' },
    ctaLabel: { zh: '', en: '' },
  }
}

const form = reactive(emptyForm())

function editItem(item) {
  Object.assign(form, JSON.parse(JSON.stringify(item)))
}

function resetForm() {
  Object.assign(form, emptyForm())
}

async function save() {
  await admin.saveBanner(form)
  resetForm()
}

onMounted(() => {
  admin.loadBanners()
})
</script>
