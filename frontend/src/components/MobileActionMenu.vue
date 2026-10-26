<template>
  <ElPopover v-if="isPhone" v-model:visible="open" trigger="click" placement="top" width="240">
    <template #reference><ElButton :disabled="disabled">{{ label }}</ElButton></template>
    <div class="mobile-more-actions" @click="closeAfterAction"><slot /></div>
  </ElPopover>
  <slot v-else />
</template>
<script setup>
import { ref } from 'vue';
import { useResponsive } from '../composables/responsive';
defineProps({ disabled: Boolean, label: { type: String, default: '更多' } });
const { isPhone } = useResponsive();
const open = ref(false);
function closeAfterAction(event) {
  const button = event.target.closest('button:not(:disabled)');
  if (button && !button.closest('.el-dropdown')) open.value = false;
}
</script>
<style>
.mobile-more-actions { display:flex; flex-direction:column; gap:8px; }
.mobile-more-actions .el-button + .el-button { margin-left:0; }
</style>
