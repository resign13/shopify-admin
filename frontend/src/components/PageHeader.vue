<template>
  <header class="page-heading">
    <div>
      <div class="eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="header-actions"><slot /></div>
  </header>
</template>
<script setup>
defineProps({
  title: String,
  description: String,
  eyebrow: { type: String, default: "GINGTTO WORKSPACE" },
});
</script>
