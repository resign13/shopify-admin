<template>
  <header class="page-heading">
    <div>
      <div class="eyebrow">{{ eyebrow }}</div>
      <h1>{{ isPhone && mobileTitle ? mobileTitle : title }}</h1>
      <p v-if="isPhone ? mobileDescription || description : description">{{ isPhone ? mobileDescription || description : description }}</p>
    </div>
    <div class="header-actions"><slot /></div>
  </header>
</template>
<script setup>
import { useResponsive } from '../composables/responsive';
const { isPhone } = useResponsive();
defineProps({
  title: String,
  description: String,
  eyebrow: { type: String, default: "GINGTTO WORKSPACE" },
  mobileTitle: String,
  mobileDescription: String,
});
</script>
