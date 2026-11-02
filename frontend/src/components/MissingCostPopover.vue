<template>
  <ElPopover :trigger="touch ? 'click' : ['hover', 'focus']" placement="top" :width="280" :show-after="80" :hide-after="150" popper-style="max-width:calc(100vw - 32px)">
    <template #reference>
      <button type="button" class="missing-cost-help" aria-label="查看缺失成本款号"><ElIcon><QuestionFilled /></ElIcon></button>
    </template>
    <div class="missing-cost-popover">
      <strong>本次核算缺失成本的款号</strong>
      <ul v-if="styles.length">
        <li v-for="item in styles" :key="item.styleCode"><span>{{ item.styleCode || '未归类' }}</span><small>{{ item.missingQuantity }} 件</small></li>
      </ul>
      <p v-else>暂无缺失款号，请重新查询核算。</p>
    </div>
  </ElPopover>
</template>

<script setup>
import { QuestionFilled } from '@element-plus/icons-vue';
defineProps({ styles: { type: Array, default: () => [] }, touch: Boolean });
</script>

<style scoped>
.missing-cost-help{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;border:0;background:none;padding:3px;color:#c17820;cursor:pointer;font-size:13px;line-height:1}
.missing-cost-help:focus-visible{outline:2px solid #2f65ef;outline-offset:2px;border-radius:3px}
.missing-cost-popover strong{font-size:13px;color:#34445b}
.missing-cost-popover ul{list-style:none;padding:0;margin:8px 0 0;max-height:240px;overflow-y:auto}
.missing-cost-popover li{display:flex;justify-content:space-between;gap:12px;padding:5px 0;font-size:12px;color:#40516c}
.missing-cost-popover li span{overflow-wrap:anywhere;min-width:0}
.missing-cost-popover li small{white-space:nowrap;color:#a0733b}
.missing-cost-popover p{font-size:12px;color:#8795aa;margin:8px 0 0}
@media(max-width:767px){.missing-cost-help{min-width:28px;min-height:28px}}
</style>
