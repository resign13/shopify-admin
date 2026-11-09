<template>
  <ElPopover trigger="click" placement="bottom-start" :width="250">
    <template #reference>
      <ElButton text size="small" class="allowance-trigger" :aria-label="`验货额度 ${row.sizeCode}`">
        <ElIcon><InfoFilled /></ElIcon><span :class="{ 'allowance-extra': extraInStages }">{{ extraInStages ? `超送 ${extraInStages} 件` : '验货额度' }}</span>
      </ElButton>
    </template>
    <div class="allowance-card">
      <div class="allowance-card__heading"><strong>{{ inventorySizeLabel(row.sizeCode) }} · 验货额度</strong><span>当前未送的 15%</span></div>
      <div class="allowance-card__remaining"><span>{{ preview ? '登记后下一笔最多到货' : '单次最多到货' }}</span><strong>{{ row.contractPending + balanceAllowance(row.contractPending) }}<small> 件</small></strong></div>
      <dl class="allowance-card__details">
        <div><dt>实际合同未送</dt><dd>{{ row.contractPending || 0 }} 件</dd></div>
        <div><dt>可超收数量</dt><dd>{{ balanceAllowance(row.contractPending) }} 件</dd></div>
        <div><dt>待验货中超量</dt><dd>{{ row.overdeliveryInspection || 0 }} 件</dd></div>
        <div v-if="row.overdeliveryQualified"><dt>合格中超送</dt><dd>{{ row.overdeliveryQualified }} 件</dd></div>
      </dl>
      <label v-if="arrival > 0" class="allowance-card__extra">本次超收（选填）
        <ElInputNumber :model-value="row.receiptExtra ?? undefined" :min="0" :precision="0"
          :controls="false" placeholder="留空自动" :aria-label="`本次超收 ${row.sizeCode}`" @change="value => emit('extra', value)" />
      </label>
      <p class="allowance-card__note">按实际未送计算，向下取整。旧批多送时可单独填写超收，超收不扣未送。</p>
      <p v-if="preview" class="allowance-card__preview">当前为草稿预览，保存后生效。</p>
    </div>
  </ElPopover>
</template>

<script setup>
import { computed } from 'vue';
import { InfoFilled } from '@element-plus/icons-vue';
import { inventorySizeLabel } from '../utils/inventorySizes';
import { balanceAllowance, receiptArrival } from '../utils/inventoryStages';
const props = defineProps({ row: { type: Object, required: true } });
const emit = defineEmits(['extra']);
const extraInStages = computed(() => (props.row.overdeliveryInspection || 0) + (props.row.overdeliveryQualified || 0));
const arrival = computed(() => props.row.registrationBase ? receiptArrival(props.row.registrationBase, props.row.pendingInspection, props.row.pendingInbound) : 0);
const preview = computed(() => props.row.pendingInspection !== props.row.originalInspection || props.row.pendingInbound !== props.row.originalInbound);
</script>

<style scoped>
.allowance-extra { color:#8c5006; font-variant-numeric:tabular-nums; }
.allowance-card__extra { display:flex; align-items:center; justify-content:space-between; gap:6px; font-size:12px; }
.allowance-card__extra :deep(.el-input-number) { width:86px; }
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
