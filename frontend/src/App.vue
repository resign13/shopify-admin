<template>
  <RouterView />
  <div v-if="isAdminPageLoading" class="admin-global-loading">
    <div class="admin-global-loading-box">
      <div class="admin-global-loading-spinner"></div>
      <span>Loading...</span>
    </div>
  </div>
</template>

<script setup>
import { RouterView } from 'vue-router'

import { isAdminPageLoading } from './loading'
</script>

<style scoped>
.admin-global-loading {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(255, 248, 242, 0.68);
  backdrop-filter: blur(2px);
  display: grid;
  place-items: center;
}

.admin-global-loading-box {
  min-width: 180px;
  padding: 18px 22px;
  border-radius: 18px;
  background: rgba(33, 22, 14, 0.9);
  color: #fff;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  box-shadow: 0 20px 50px rgba(33, 22, 14, 0.25);
}

.admin-global-loading-spinner {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  border: 2px solid rgba(255, 255, 255, 0.28);
  border-top-color: #fff;
  animation: admin-spin 0.8s linear infinite;
}

@keyframes admin-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
