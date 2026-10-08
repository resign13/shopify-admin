<template>
  <section class="order-history">
    <div class="panel-title">
      <h3>订单操作记录</h3>
      <span class="small-note">仅记录修改 · 最新记录在前 · 每页 10 条</span>
    </div>
    <ElAlert v-if="history.error" :title="history.error" type="error" :closable="false">
      <ElButton link type="primary" @click="load">重新加载记录</ElButton>
    </ElAlert>
    <ElTable v-loading="history.loading" :data="history.items" row-key="id" empty-text="暂无订单操作记录">
      <ElTableColumn label="操作时间" width="165">
        <template #default="{ row }">{{ dateTime(row.occurredAt) }}</template>
      </ElTableColumn>
      <ElTableColumn label="操作人" width="100">
        <template #default="{ row }">
          {{ row.actor.name || '未知操作人' }}
          <small class="history-role">{{ roleNames[row.actor.role] || row.actor.role }}</small>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作 / 修改明细" min-width="300">
        <template #default="{ row }">
          <strong>{{ operationNames[row.action] || '修改订单' }}</strong>
          <div v-for="(change, index) in row.changes" :key="index" class="history-change">
            <span v-if="change.sku" class="sku">{{ change.sku }} · {{ change.sizeCode || '无尺码' }} </span>
            {{ operationFields[change.field] || change.field }}：{{ format(change.field, change.before) }} → {{ format(change.field, change.after) }}
            <span v-if="change.field === 'attachments' && change.before === change.after">（附件内容已更新）</span>
            <b v-if="change.delta != null" :class="change.delta < 0 ? 'negative' : 'positive'">（{{ change.delta > 0 ? '+' : '' }}{{ change.delta }}）</b>
          </div>
          <div v-if="!row.changes.length" class="small-note">订单资料已保存</div>
        </template>
      </ElTableColumn>
    </ElTable>
    <ElPagination v-model:current-page="history.page" :page-size="10" :total="history.total" layout="total,prev,pager,next" class="section-gap" />
  </section>
</template>

<script setup>
import { onBeforeUnmount, reactive, watch } from 'vue';
import { api, dateTime, roleNames, statusNames, money } from '../composables/workbench';
import { operationNames, operationFields, operationValue } from '../utils/orderOperations';

const props = defineProps({ orderId: [Number, String], open: Boolean, revision: String });
const history = reactive({ items: [], total: 0, page: 1, loading: false, error: '' });
const format = (field, value) => operationValue(field, value, statusNames, money);
let controller, serial = 0;

async function load() {
  if (!props.open || !props.orderId) return;
  controller?.abort();
  controller = new AbortController();
  const current = ++serial;
  history.loading = true;
  history.error = '';
  history.items = [];
  try {
    const result = await api(`orders/${props.orderId}/operations?page=${history.page}&pageSize=10`, { signal: controller.signal });
    if (current === serial) {
      history.items = result.items;
      history.total = result.total;
    }
  } catch (error) {
    if (current === serial && error.name !== 'AbortError') history.error = error.message;
  } finally {
    if (current === serial) history.loading = false;
  }
}

watch(() => [props.open, props.orderId, props.revision], () => {
  controller?.abort();
  serial++;
  Object.assign(history, { items: [], total: 0, page: 1, loading: false, error: '' });
  load();
}, { immediate: true });
watch(() => history.page, load);
onBeforeUnmount(() => { controller?.abort(); serial++; });
</script>

<style scoped>
.order-history { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border, #e5e7eb); }
.history-role { display: block; color: var(--muted, #64748b); margin-top: 4px; }
.history-change { margin-top: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
.panel-title { flex-wrap: wrap; gap: 8px; }
</style>
