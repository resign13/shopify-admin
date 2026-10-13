<template>
  <span class="order-number" :title="parts.full">
    <button v-if="clickable" class="order-number-text order-number-link" type="button" :aria-label="parts.full" @click="$emit('open')"><span class="order-number-fixed">{{ parts.prefix }}</span><span class="order-number-name">{{ parts.name }}</span><span class="order-number-fixed">{{ parts.suffix }}</span></button>
    <span v-else class="order-number-text"><span class="order-number-fixed">{{ parts.prefix }}</span><span class="order-number-name">{{ parts.name }}</span><span class="order-number-fixed">{{ parts.suffix }}</span></span>
    <ElButton v-if="copyable" link class="order-number-copy" title="复制完整订单号" :aria-label="`复制完整订单号 ${parts.full}`" @click.stop="copy(parts.full)"><ElIcon><CopyDocument /></ElIcon></ElButton>
  </span>
</template>
<script setup>
import { computed } from 'vue';
import { CopyDocument } from '@element-plus/icons-vue';
import { copy } from '../composables/workbench';
import { orderNumberParts } from '../utils/orderNumber';
const props = defineProps({ value: String, clickable: Boolean, copyable: Boolean });
defineEmits(['open']);
const parts = computed(() => orderNumberParts(props.value));
</script>
<style scoped>
.order-number { display: flex; align-items: center; gap: 6px; min-width: 0; width: 100%; }
.order-number-text { display: flex; align-items: baseline; min-width: 0; max-width: 100%; padding: 0; background: none; border: 0; font: inherit; text-align: left; }
.order-number-link { color: var(--el-color-primary); cursor: pointer; }
.order-number-link:hover { text-decoration: underline; }
.order-number-fixed { flex: 0 0 auto; white-space: pre; }
.order-number-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: pre; }
.order-number-copy { flex: 0 0 auto; padding: 4px; }
</style>
