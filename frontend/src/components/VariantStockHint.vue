<template>
  <small class="variant-stock-hint" :class="{ 'is-shortage': hint.shortage }" :title="title">{{ hint.text }}</small>
</template>
<script setup>
import { computed } from 'vue';
import { variantStockHint } from '../utils/orderQuantities';
const props = defineProps({ stock: [Number, String], title: String, unavailableText: { type: String, default: '库存不可用' } });
const hint = computed(() => variantStockHint(props.stock, props.unavailableText));
</script>
<style scoped>
.variant-stock-hint { display:block; color:var(--muted,#64748b); font-size:11px; line-height:1.5; font-weight:400; white-space:normal; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.variant-stock-hint.is-shortage { color:var(--el-color-danger,#f56c6c); }
</style>
