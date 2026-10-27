<template>
  <template v-if="isPhone">
    <ElButton class="mobile-more-trigger" :class="{ 'is-icon-only': iconOnly || label === '更多' || label.endsWith('操作') }" :disabled="disabled" :aria-label="label" @click="open = true">
      <ElIcon v-if="iconOnly || label === '更多' || label.endsWith('操作')"><MoreFilled /></ElIcon><span v-else>{{ label }}</span>
    </ElButton>
    <ElDrawer v-model="open" :title="label === '更多' ? '更多操作' : label" direction="btt" size="auto" append-to-body class="mobile-action-sheet">
      <div class="mobile-more-actions" @click="closeAfterAction"><slot /></div>
      <button class="mobile-sheet-dismiss" @click="open = false">取消</button>
    </ElDrawer>
  </template>
  <slot v-else />
</template>
<script setup>
import { ref } from 'vue';
import { useResponsive } from '../composables/responsive';
import { MoreFilled } from '@element-plus/icons-vue';
defineProps({ disabled: Boolean, iconOnly: Boolean, label: { type: String, default: '更多' } });
const { isPhone } = useResponsive();
const open = ref(false);
function closeAfterAction(event) {
  // An action may become disabled/loading in its own click handler.
  const button = event.target.closest('button');
  if (button && !button.closest('.el-dropdown')) open.value = false;
}
</script>
<style>
.mobile-more-actions { display:flex; flex-direction:column; gap:8px; }
.mobile-more-actions .el-button + .el-button { margin-left:0; }
</style>
