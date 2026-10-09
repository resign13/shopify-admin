<template>
  <div class="quantity-change" aria-live="polite">
    <span class="quantity-change__original" :title="`原值 ${original}`">原值 {{ original }}</span>
    <span :class="['quantity-change__delta', change.tone]" :aria-label="`变化 ${change.text}`" :title="`变化 ${change.text}`">{{ change.text }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { quantityChange } from '../utils/inventoryRegistrationUI';
const props = defineProps({ value: Number, original: Number });
const change = computed(() => quantityChange(props.value, props.original));
</script>

<style scoped>
.quantity-change { display: flex; align-items: center; justify-content: space-between; gap: 4px; margin-top: 6px; color: #7a8699; font-size: 11px; line-height: 18px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.quantity-change__original { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.quantity-change__delta { flex-shrink: 0; border-radius: 4px; padding: 0 4px; }
.increase { background: #ecfdf5; color: #047857; font-weight: 600; }
.decrease { background: #fff1f2; color: #be123c; font-weight: 600; }
.incomplete { background: #fffbeb; color: #92400e; }
.unchanged { color: #98a2b3; }
</style>
