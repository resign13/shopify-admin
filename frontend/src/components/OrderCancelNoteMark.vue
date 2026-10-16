<template>
  <ElTooltip v-if="note" :trigger="['hover', 'focus', 'click']" placement="top" :show-after="100">
    <template #content><div class="cancel-note-text">{{ note }}</div></template>
    <button type="button" class="cancel-note-mark" aria-label="查看取消备注" data-testid="cancel-note-mark"><ChatDotRound /></button>
  </ElTooltip>
</template>
<script setup>
import { ChatDotRound } from '@element-plus/icons-vue';
defineProps({ note: String });
</script>
<style scoped>
.cancel-note-mark { display:inline-flex; vertical-align:middle; border:0; background:none; padding:3px; margin-left:3px; width:21px; height:21px; color:#64748b; cursor:pointer; }
.cancel-note-mark:focus-visible { outline:2px solid var(--el-color-primary); border-radius:3px; }
.cancel-note-text { max-width:min(320px,80vw); white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.6; }
</style>
