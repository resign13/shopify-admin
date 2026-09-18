<template>
  <section class="panel empty-state">
    <h2>暂未分配模块权限</h2>
    <p>请联系管理员勾选需要使用的模块，或刷新权限后重试。</p>
    <ElButton :loading="loading" @click="refresh">刷新权限</ElButton>
  </section>
</template>
<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAdminAuthStore } from "../stores/auth";
const auth = useAdminAuthStore(),
  router = useRouter(),
  loading = ref(false);
async function refresh() {
  loading.value = true;
  try {
    await auth.initialize();
    await router.replace(auth.isAuthenticated ? auth.defaultRoute : "/login");
  } finally {
    loading.value = false;
  }
}
</script>
