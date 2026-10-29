<template>
  <ElDrawer :model-value="visible" title="选择商品" size="min(1120px, 100vw)"
    class="order-quantity-picker" :before-close="close" :close-on-press-escape="!busy"
    :show-close="!busy" append-to-body data-testid="order-quantity-picker">
    <ResponsiveFilters class="picker-filters" bare @submit="search">
      <ElInput v-model="query.keyword" clearable placeholder="标题、款式或 SKU" aria-label="选品关键词" :disabled="busy" />
      <ElSelect v-model="query.category" clearable placeholder="全部分类" aria-label="选品分类" :disabled="busy">
        <ElOption v-for="c in categories" :key="c.key" :value="c.key" :label="c.labels?.zh || c.key" />
      </ElSelect>
      <ElButton native-type="submit" :disabled="busy || loading">查询</ElButton>
    </ResponsiveFilters>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" class="picker-error" role="alert" />
    <div v-if="pendingOnly" class="pending-caption">正在查看全部待处理项<ElButton link @click="pendingOnly = false">返回查询结果</ElButton></div>
    <div v-loading="loading" class="quantity-list" role="list" aria-label="商品尺码数量" :aria-busy="loading">
      <div class="picker-list-header" aria-hidden="true"><span>颜色 SKU</span><span>尺码及数量</span><span>操作</span></div>
      <div v-for="row in displayRows" :key="row.id" class="picker-product-row" role="listitem"
        :aria-label="`${row.sku} 商品尺码数量`" :data-testid="`picker-row-${row.id}`">
        <span :title="row.sku" class="picker-sku">{{ row.sku }}</span>
        <div class="picker-row-sizes">
          <label v-for="size in selectionSizes(records[row.id].product)" :key="size" class="picker-size-unit">
            <span class="picker-size-name">{{ size }}</span>
            <input :value="records[row.id].quantities[size]" type="text" inputmode="numeric" role="spinbutton"
              :aria-label="`${row.sku} ${size} 数量`" aria-valuemin="0" :aria-valuemax="MAX_ORDER_QUANTITY"
              :aria-valuenow="numericQuantity(row, size)" :aria-invalid="!!quantityError(row, size)"
              :aria-describedby="quantityError(row, size) ? quantityErrorId(row, size) : undefined"
              :title="quantityError(row, size) || `${row.sku} / ${size} 购买数量`"
              :disabled="busy || disabled" class="picker-quantity" :class="{ 'is-changed': cellChanged(row, size), 'is-invalid': quantityError(row, size) }"
              :data-testid="`picker-qty-${row.id}-${size}`" @input="setQuantity(row, size, $event.target.value)"
              @blur="normalizeQuantity(row, size)" />
            <small v-if="quantityError(row, size)" :id="quantityErrorId(row, size)" class="quantity-error">{{ quantityError(row, size) }}</small>
          </label>
          <span v-if="!selectionSizes(records[row.id].product).length" class="unavailable">未配置尺码</span>
        </div>
        <div class="picker-row-actions">
          <ElButton link type="primary" :disabled="busy || disabled || !selectionSizes(records[row.id].product).length || (existsInOrder(row) && !selectionChanged(records[row.id]))" @click="apply([records[row.id]], false)">
            加入
          </ElButton>
        </div>
      </div>
      <p v-if="!displayRows.length && !loading" class="picker-empty" role="status">暂无商品</p>
    </div>
    <ElPagination v-if="!pendingOnly" v-model:current-page="query.page" :page-size="25" :total="total"
      layout="total,prev,pager,next" class="picker-pagination" :disabled="busy || loading" @current-change="load" />
    <template #footer>
      <div class="picker-footer">
        <p v-if="isPhone && error" ref="mobileErrorFeedback" class="picker-footer-error" role="alert" tabindex="-1"><strong>操作未完成，填写已保留</strong><span>{{ error }}</span></p>
        <span class="pending-count" role="status">待处理 {{ pendingRecords.length }} 个颜色 SKU</span>
        <ElButton link :disabled="busy || (!pendingOnly && !pendingRecords.length)" @click="togglePending">{{ pendingOnly ? '返回查询结果' : '查看待处理' }}</ElButton>
        <span class="footer-spacer" />
        <ElButton :disabled="busy" @click="close()">取消</ElButton>
        <ElButton type="primary" :loading="busy" :disabled="disabled" @click="finish">完成</ElButton>
      </div>
    </template>
  </ElDrawer>
  <ElDialog v-model="confirmationOpen" title="确认商品调整" width="min(700px, 94vw)" append-to-body
    :close-on-click-modal="false" @close="resolveConfirmation(false)">
    <p class="small-note">数量覆盖原值，不累加；已有成交价保持不变。目录参考价变动仅影响新加入的尺码。</p>
    <AdaptiveTable :data="notices" max-height="360">
      <ElTableColumn prop="sku" label="颜色 SKU" min-width="160" />
      <ElTableColumn prop="sizeCode" label="尺码" width="90" />
      <ElTableColumn label="变更" min-width="200"><template #default="{ row }">
        <span v-if="row.before !== undefined">{{ row.before }} → {{ row.after }}<strong v-if="row.clear" class="clear-note">（清零）</strong></span>
        <span v-else>目录参考价 USD {{ row.oldPrice }} → {{ row.newPrice }}</span>
      </template></ElTableColumn>
    </AdaptiveTable>
    <template #footer><ElButton @click="resolveConfirmation(false)">返回修改</ElButton><ElButton type="primary" @click="resolveConfirmation(true)">确认应用</ElButton></template>
  </ElDialog>
</template>

<script setup>
import { errorMessage } from '../utils/adminErrors.js';
import AdaptiveTable from "./AdaptiveTable";
import ResponsiveFilters from './ResponsiveFilters.vue';
import { computed, nextTick, onBeforeUnmount, reactive, ref, useId, watch } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { ElMessage } from 'element-plus';
import { api, confirm } from '../composables/workbench';
import { useResponsive } from '../composables/responsive';
import { MAX_ORDER_QUANTITY, createSelectionRecord, selectionChanged, selectionQuantity, selectionSizes, prepareSelectionApplication } from '../utils/orderSelection';

const props = defineProps({ visible: Boolean, items: { type: Array, default: () => [] }, categories: Array,
  disabled: Boolean, currency: { type: String, default: 'USD' }, exchangeRate: [Number, String], applyQuantities: { type: Function, required: true } });
const emit = defineEmits(['update:visible']);
const { isPhone } = useResponsive();
const mobileErrorFeedback = ref();
const query = reactive({ page: 1, pageSize: 25, keyword: '', category: '' });
const records = reactive({}), rows = ref([]), total = ref(0), error = ref(''), loading = ref(false), busy = ref(false), pendingOnly = ref(false);
const pendingViewIds = ref([]);
const pendingRecords = computed(() => Object.values(records).filter(selectionChanged));
// Keep the row visible while its input is temporarily blank/zero, so a user can
// replace the value without losing focus halfway through typing.
const displayRows = computed(() => pendingOnly.value ? pendingViewIds.value.map(id => records[id]?.product).filter(Boolean) : rows.value);
const confirmationOpen = ref(false), notices = ref([]);
const idPrefix = useId();
const quantityErrorId = (row, size) => `${idPrefix}-quantity-${row.id}-${encodeURIComponent(size)}`;
let serial = 0, epoch = 0, baselineSignature = '', confirmResolver, discarding = false;
const quantityError = (row, size) => { try { selectionQuantity(records[row.id].quantities[size]); return ''; } catch (error) { return errorMessage(error); } };
const numericQuantity = (row, size) => { try { return selectionQuantity(records[row.id].quantities[size]); } catch { return undefined; } };
const cellChanged = (row, size) => quantityError(row, size) || numericQuantity(row, size) !== records[row.id].baseline[size];
const existsInOrder = row => props.items.some(item => String(item.productId) === String(row.id));
function setQuantity(row, size, value) { if (!busy.value && !props.disabled) records[row.id].quantities[size] = value; }
function normalizeQuantity(row, size) { if (!quantityError(row, size)) setQuantity(row, size, numericQuantity(row, size)); }
function togglePending() {
  if (!pendingOnly.value) pendingViewIds.value = pendingRecords.value.map(record => record.product.id);
  pendingOnly.value = !pendingOnly.value;
}
function resolveConfirmation(answer) { const resolve = confirmResolver; confirmResolver = undefined; confirmationOpen.value = false; resolve?.(answer); }
function askConfirmation(changes) {
  notices.value = changes;
  confirmationOpen.value = true;
  return new Promise(resolve => { confirmResolver = resolve; });
}
async function load() {
  const id = ++serial, session = epoch;
  loading.value = true;
  error.value = '';
  try {
    const result = await api('products?' + new URLSearchParams(query));
    if (id !== serial || session !== epoch || !props.visible) return;
    for (const product of result.items) {
      if (!records[product.id] || !selectionChanged(records[product.id])) records[product.id] = createSelectionRecord(product, props.items);
    }
    rows.value = result.items;
    total.value = result.total;
  } catch (failure) { if (id === serial && session === epoch) error.value = errorMessage(failure); }
  finally { if (id === serial && session === epoch) loading.value = false; }
}
function search() { query.page = 1; pendingOnly.value = false; load(); }
async function close(done) {
  if (busy.value || discarding) return;
  discarding = true;
  const session = epoch;
  try {
    if (pendingRecords.value.length && !(await confirm('尚有未同步到订单页面的尺码数量，是否放弃这些填写？', '未应用的商品数量'))) return;
    if (session !== epoch) return;
    emit('update:visible', false);
    if (typeof done === 'function') done();
  } finally { discarding = false; }
}
async function finish() {
  if (busy.value || props.disabled || discarding) return;
  const session = epoch;
  discarding = true;
  try {
    const unjoined = pendingRecords.value.filter(record => !existsInOrder(record.product));
    if (unjoined.length && !(await confirm(`有 ${unjoined.length} 个新 SKU 尚未点击“加入”。完成会放弃这些新 SKU 的填写，不会自动加入，是否继续？`, '新商品尚未加入'))) return;
    if (session !== epoch || !props.visible) return;
    const existing = pendingRecords.value.filter(record => existsInOrder(record.product));
    if (existing.length) await apply(existing, true);
    else emit('update:visible', false);
  } finally { discarding = false; }
}
async function apply(selected, finish) {
  if (busy.value || props.disabled || !selected.length) return;
  busy.value = true;
  error.value = '';
  const session = epoch;
  try {
    if (JSON.stringify(props.items) !== baselineSignature) throw new Error('订单商品已变化，请重新打开选品窗口后调整');
    const fresh = [];
    for (let i = 0; i < selected.length; i += 100) {
      const ids = selected.slice(i, i + 100).map(record => record.product.id).join(',');
      const result = await api('products?' + new URLSearchParams({ page: 1, pageSize: 100, ids }));
      fresh.push(...result.items);
    }
    if (session !== epoch || !props.visible) return;
    const prepared = prepareSelectionApplication(selected, fresh, props.items, props.currency, props.exchangeRate, { join: !finish });
    if (prepared.notices.length && !(await askConfirmation(prepared.notices))) return;
    if (session !== epoch || !props.visible) return;
    if (props.disabled || JSON.stringify(props.items) !== baselineSignature) throw new Error('订单状态或商品已变化，请重新打开选品窗口后调整');
    await props.applyQuantities(prepared.updates);
    await nextTick();
    baselineSignature = JSON.stringify(props.items);
    for (const { product } of prepared.updates) {
      records[product.id] = createSelectionRecord(product, props.items);
      pendingViewIds.value = pendingViewIds.value.filter(id => String(id) !== String(product.id));
    }
    ElMessage.success({ message: '已同步到订单页面，尚未保存订单', grouping: true, duration: 1500 });
    if (finish) emit('update:visible', false);
  } catch (failure) {
    if (session === epoch) {
      error.value = errorMessage(failure, '应用失败，请重试');
      if (isPhone.value) {
        await nextTick();
        if (session === epoch && props.visible) mobileErrorFeedback.value?.focus({ preventScroll: true });
      }
    }
  }
  finally { if (session === epoch) busy.value = false; }
}
watch(() => props.visible, visible => {
  ++epoch; ++serial;
  resolveConfirmation(false);
  busy.value = false; loading.value = false; error.value = ''; pendingOnly.value = false; pendingViewIds.value = [];
  for (const id of Object.keys(records)) delete records[id];
  rows.value = []; total.value = 0;
  if (visible) { baselineSignature = JSON.stringify(props.items); load(); }
}, { immediate: true });
const beforeUnload = event => { if (props.visible && pendingRecords.value.length) { event.preventDefault(); event.returnValue = ''; } };
window.addEventListener('beforeunload', beforeUnload);
onBeforeRouteLeave(async () => {
  if (!props.visible) return true;
  if (busy.value) return false;
  if (!pendingRecords.value.length) return true;
  if (!(await confirm('尚有未同步到订单页面的尺码数量，是否放弃并离开？', '未应用的商品数量'))) return false;
  emit('update:visible', false);
  return true;
});
onBeforeUnmount(() => { ++epoch; ++serial; resolveConfirmation(false); window.removeEventListener('beforeunload', beforeUnload); });
</script>

<style scoped>
.picker-filters { display:flex; gap:8px; margin-bottom:16px; }
.picker-filters > .el-input { flex:1; min-width:0; }
.picker-filters > .el-select { width:180px; }
.picker-error { margin-bottom:12px; }
.quantity-list { min-width:0; font-size:12px; }
.picker-list-header, .picker-product-row { display:grid; grid-template-columns:170px minmax(0,1fr) 120px; gap:16px; padding:12px 8px; border-bottom:1px solid var(--el-border-color-lighter,#ebeef5); }
.picker-list-header { padding-top:8px; padding-bottom:8px; color:var(--el-text-color-secondary,#64748b); }
.picker-list-header > :last-child { text-align:right; }
.picker-sku { min-width:0; padding-top:23px; overflow-wrap:anywhere; color:var(--el-text-color-regular,#334155); }
.picker-row-sizes { display:flex; flex-wrap:wrap; align-items:flex-start; align-content:flex-start; gap:12px 10px; min-width:0; }
.picker-size-unit { display:flex; flex-direction:column; align-items:center; gap:4px; width:72px; max-width:100%; min-width:0; }
.picker-size-name { width:100%; min-height:16px; line-height:16px; text-align:center; font-size:11px; color:var(--el-text-color-secondary,#64748b); white-space:normal; overflow-wrap:anywhere; }
.picker-quantity { box-sizing:border-box; width:72px; max-width:100%; height:32px; border:1px solid var(--el-border-color,#dcdfe6); border-radius:4px; background:var(--el-bg-color,#fff); color:var(--el-text-color-regular,#606266); text-align:center; font-size:12px; outline:none; }
.picker-row-actions { display:flex; justify-content:flex-end; align-items:center; gap:8px; padding-top:20px; }
.picker-row-actions .el-button + .el-button { margin-left:0; }
.picker-empty { padding:28px 8px; margin:0; text-align:center; color:var(--el-text-color-secondary); }
.picker-quantity:focus { border-color:var(--el-color-primary); box-shadow:0 0 0 1px var(--el-color-primary); }
.picker-quantity.is-changed { background:var(--el-color-warning-light-9,#fdf6ec); border-color:var(--el-color-warning-light-5,#e6b85c); }
.picker-quantity.is-invalid { border-color:var(--el-color-danger); }
.picker-quantity:disabled { opacity:.65; cursor:not-allowed; }
.quantity-error { display:block; width:100%; color:var(--el-color-danger); font-size:11px; line-height:1.3; overflow-wrap:anywhere; }
.unavailable { padding-top:23px; color:var(--el-text-color-placeholder); }
.picker-pagination { margin-top:16px; max-width:100%; overflow-x:auto; }
.picker-footer { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.picker-footer .el-button + .el-button { margin-left:0; }
.pending-count { color:var(--el-text-color-secondary); font-size:12px; }
.footer-spacer { flex:1; }
.pending-caption { display:flex; align-items:center; gap:12px; margin-bottom:8px; font-size:12px; }
.clear-note { color:var(--el-color-danger); font-weight:normal; }
@media(max-width:767px) {
  .picker-footer-error { display:flex; flex-direction:column; gap:3px; width:100%; margin:0; padding:9px 11px; box-sizing:border-box; border:1px solid var(--el-color-danger-light-7,#fbc4c4); border-radius:8px; color:var(--el-color-danger,#f56c6c); background:var(--el-color-danger-light-9,#fef0f0); font-size:12px; line-height:1.5; overflow-wrap:anywhere; text-align:left; }
  .picker-footer-error strong { font-weight:600; }
  .picker-footer-error:focus-visible { outline:2px solid var(--el-color-danger,#f56c6c); outline-offset:2px; }
}
@media(max-width:600px) {
  .picker-filters { flex-wrap:wrap; }
  .picker-filters > .el-input { flex-basis:100%; }
  .picker-filters > .el-select { flex:1; }
  .picker-list-header { display:none; }
  .picker-product-row { grid-template-columns:minmax(0,1fr) auto; gap:12px 8px; padding:14px 0; }
  .picker-sku { grid-column:1; grid-row:1; padding-top:0; align-self:center; }
  .picker-row-actions { grid-column:2; grid-row:1; padding-top:0; }
  .picker-row-sizes { grid-column:1 / -1; grid-row:2; }
  .unavailable { padding-top:0; }
  .pending-count { width:100%; text-align:left; }
}
</style>
