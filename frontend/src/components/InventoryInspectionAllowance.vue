<template>
  <ElPopover trigger="click" placement="bottom-start" :width="300">
    <template #reference>
      <ElButton text size="small" class="allowance-trigger" :aria-label="`验货额度 ${row.sizeCode}`">
        <ElIcon><InfoFilled /></ElIcon><span>验货额度</span>
      </ElButton>
    </template>
    <div class="allowance-card">
      <div class="allowance-card__heading"><strong>{{ inventorySizeLabel(row.sizeCode) }} · 验货额度</strong><span>按原合同累计 15%</span></div>
      <div class="allowance-card__remaining"><span>{{ preview ? '登记后剩余额度' : '剩余超量额度' }}</span><strong>{{ row.overdeliveryRemaining || 0 }}<small> 件</small></strong></div>
      <dl class="allowance-card__details">
        <div><dt>原合同总数</dt><dd>{{ row.originalContractQuantity || 0 }} 件</dd></div>
        <div><dt>15% 超量额度</dt><dd>{{ row.overdeliveryLimit || 0 }} 件</dd></div>
        <div><dt>累计已用</dt><dd>{{ row.overdeliveryUsed || 0 }} 件</dd></div>
        <div><dt>待验货中超量</dt><dd>{{ row.overdeliveryInspection || 0 }} 件</dd></div>
      </dl>
      <p v-if="!row.originalContractQuantity" class="allowance-card__note">该尺码尚无采购合同额度，手动登记合同未送不增加超量额度。</p>
      <p v-else class="allowance-card__note">额度按尺码计算、向下取整。已使用额度在减少数量、入库或打回后不返还。</p>
      <p v-if="preview" class="allowance-card__preview">当前为草稿预览，保存后生效。</p>
    </div>
  </ElPopover>
</template>

<script setup>
import { computed } from 'vue';
import { InfoFilled } from '@element-plus/icons-vue';
import { inventorySizeLabel } from '../utils/inventorySizes';
const props = defineProps({ row: { type: Object, required: true } });
const preview = computed(() => props.row.pendingInspection !== props.row.originalInspection || props.row.pendingInbound !== props.row.originalInbound);
</script>

<style scoped>
.allowance-trigger { margin: 3px 0 0 -5px; padding: 4px 5px; height: 28px; color: #64748b; font-size: 12px; }
.allowance-trigger :deep(.el-icon) { margin-right: 4px; color: #8293ab; }
.allowance-trigger:hover, .allowance-trigger:focus-visible { color: #2563eb; background: #eff6ff; }
.allowance-card { color: #334155; }
.allowance-card__heading { display: flex; flex-direction: column; gap: 4px; }
.allowance-card__heading strong { font-size: 14px; }
.allowance-card__heading > span { color: #8491a5; font-size: 12px; }
.allowance-card__remaining { display: flex; justify-content: space-between; align-items: center; margin: 14px 0; padding: 12px; background: #eff6ff; border-radius: 8px; color: #1d4ed8; font-size: 12px; }
.allowance-card__remaining strong { font-size: 23px; font-variant-numeric: tabular-nums; }
.allowance-card__remaining small { font-size: 12px; font-weight: 400; }
.allowance-card__details { margin: 0; display: grid; gap: 10px; font-size: 12px; }
.allowance-card__details > div { display: flex; justify-content: space-between; gap: 16px; }
.allowance-card__details dt { color: #64748b; }
.allowance-card__details dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
.allowance-card__note { margin: 14px 0 0; padding-top: 12px; border-top: 1px solid #e8edf3; color: #7a8699; font-size: 12px; line-height: 1.7; }
.allowance-card__preview { margin: 8px 0 0; color: #2563eb; font-size: 12px; }
</style>
