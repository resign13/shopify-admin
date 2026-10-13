<template>
  <span class="order-number" :class="{'is-expanded': expanded}">
    <span class="order-number-primary" :title="parts.full">
    <button v-if="clickable" class="order-number-text order-number-link" type="button" :aria-label="parts.full" @click="$emit('open')"><span class="order-number-fixed">{{ parts.prefix }}</span><span class="order-number-name">{{ parts.name }}</span><span class="order-number-fixed">{{ parts.suffix }}</span></button>
    <span v-else class="order-number-text"><span class="order-number-fixed">{{ parts.prefix }}</span><span class="order-number-name">{{ parts.name }}</span><span class="order-number-fixed">{{ parts.suffix }}</span></span>
    </span>
    <span v-if="secondary" class="order-number-secondary" :title="secondary">
      <span class="order-number-text"><span class="order-number-fixed">{{ subParts.prefix }}</span><span class="order-number-name">{{ subParts.name }}</span><span class="order-number-fixed">{{ subParts.suffix }}</span></span>
    </span>
  </span>
</template>
<script setup>
import { computed } from 'vue';
import { orderNumberParts } from '../utils/orderNumber';
const props = defineProps({ value: String, secondary: String, clickable: Boolean, expanded: Boolean });
defineEmits(['open']);
const parts = computed(() => orderNumberParts(props.value,props.expanded?Infinity:28));
const subParts = computed(() => orderNumberParts(props.secondary,props.expanded?Infinity:28));
</script>
<style scoped>
.order-number { display:flex; flex-direction:column; gap:3px; min-width:0; width:100%; }
.order-number-primary,.order-number-secondary { display:flex; align-items:center; gap:6px; min-width:0; width:100%; }
.order-number-primary { font-size:14px; font-weight:600; }
.order-number-secondary { color:#6b7b90; font-size:11px; font-weight:400; }
.order-number-text { display: flex; align-items: baseline; min-width: 0; max-width: 100%; padding: 0; background: none; border: 0; font: inherit; text-align: left; }
.order-number-link { color: var(--el-color-primary); cursor: pointer; }
.order-number-link:hover { text-decoration: underline; }
.order-number-fixed { flex: 0 0 auto; white-space: pre; }
.order-number-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: pre; }
.is-expanded .order-number-primary,.is-expanded .order-number-secondary { align-items:flex-start; }
.is-expanded .order-number-text { display:block; overflow-wrap:anywhere; }
.is-expanded .order-number-fixed,.is-expanded .order-number-name { white-space:pre-wrap; overflow:visible; }
</style>
