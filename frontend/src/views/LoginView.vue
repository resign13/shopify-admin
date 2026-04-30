<template>
  <section class="login-page">
    <form class="login-card" @submit.prevent="handleSubmit">
      <h1>后台登录</h1>
      <input v-model.trim="email" class="admin-field" placeholder="后台账号邮箱" />
      <input v-model.trim="password" class="admin-field" type="password" placeholder="密码" />
      <button class="admin-button" :disabled="auth.loading" type="submit">登录后台</button>
      <p v-if="auth.error" class="admin-error">{{ auth.error }}</p>
    </form>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAdminAuthStore } from '../stores/auth'

const auth = useAdminAuthStore()
const router = useRouter()

const email = ref('')
const password = ref('')

async function handleSubmit() {
  const ok = await auth.login({ email: email.value, password: password.value })
  if (ok) {
    router.push(auth.defaultRoute)
  }
}
</script>
