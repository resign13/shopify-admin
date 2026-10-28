<template>
  <ElDrawer
    :model-value="open"
    :title="isPhone ? '订单详情' : order ? `订单详情 · ${order.orderNo}` : '订单详情'"
    size="min(800px, 100vw)"
    :before-close="close"
    ><div v-if="order && !isPhone" class="order-drawer-heading">
      <OrderNumber :value="order.orderNo" :secondary="order.secondaryOrderNo" :warehouse-printed="order.warehousePrinted" expanded />
    </div><ElSkeleton v-if="loading && !order" :rows="10" animated />
    <ElAlert v-if="!order && !loading && error" :title="error" type="error" :closable="false"><ElButton text @click="refreshDetails">重试读取详情</ElButton></ElAlert>
    <template v-if="order">
      <OrderEditor
        v-if="fullEditing"
        ref="editor"
        :open="true"
        :id="id"
        embedded
        @saved="detailsSaved"
      />
      <section v-else-if="isPhone && !editing" class="m-order-detail" data-testid="mobile-order-detail">
        <div class="m-detail-hero"><div><small>{{ order.orderNo }}</small><span class="m-detail-status">{{ statusNames[order.status] }}</span></div><strong>{{ warehouseStatusOnly ? `${order.itemCount} 件` : money(order.totalAmount) }}</strong><p>{{ order.itemCount }} 件<span v-if="!warehouseStatusOnly"> · 含运费 {{ money(order.shippingFee) }}</span><span v-if="order.warehousePrinted"> · 仓库已打单</span></p></div>
        <section class="m-detail-card"><h3>客户</h3><div class="m-detail-customer"><span>{{ (order.contactName || order.userName || '客').slice(0,1) }}</span><div><strong>{{ order.contactName || order.userName }}</strong><small>{{ order.userName }} · {{ order.country }}</small></div></div><p class="m-detail-address">{{ order.shippingAddress }}</p></section>
        <header class="m-detail-section-head"><h3>商品明细</h3><ElButton text type="primary" :loading="loading" @click="refreshDetails">刷新</ElButton></header>
        <ElAlert v-if="stockRefreshError" :title="stockRefreshError" type="warning" :closable="false"/>
        <section v-for="group in mobileGroups" :key="group.key" class="m-detail-card"><header><h3>{{ group.sku }}</h3><small>{{ group.quantity }} 件</small></header><div v-for="row in group.items" :key="row.productId + ':' + row.sizeCode" class="m-detail-item"><div><strong>{{ row.sizeCode }} <small>× {{ row.quantity }}</small></strong><VariantStockHint :stock="row.currentStock" :title="stockTitle(row)" :data-testid="`detail-stock-${row.productId}-${row.sizeCode}`"/></div><div><strong v-if="!warehouseStatusOnly">{{ money(row.unitPrice) }}</strong><small>{{ row.unitWeightGrams == null ? '净重未设置' : `${row.unitWeightGrams} g / 件` }}</small></div></div></section>
        <section class="m-detail-card m-detail-folds"><details><summary>收货与订单资料<small>联系人 · 地址 · 副单号</small></summary><dl><div><dt>商城客户</dt><dd>{{ order.userName }}</dd></div><div><dt>联系人 / 电话</dt><dd>{{ order.contactName }} · {{ order.phone || order.userEmail }}</dd></div><div><dt>国家 / 地址</dt><dd>{{ order.country }} · {{ order.shippingAddress }}</dd></div><div><dt>副单号</dt><dd>{{ order.secondaryOrderNo || '未填写' }}</dd></div><div><dt>业务员</dt><dd>{{ order.ownerAdminName || '未分配' }}</dd></div><div><dt>下单时间</dt><dd>{{ dateTime(order.createdAt) }}</dd></div></dl></details><details><summary>物流与付款<small>{{ order.trackingNo || '未填写物流' }}</small></summary><dl><div><dt>物流单号</dt><dd>{{ order.trackingNo || '未填写' }}</dd></div><div v-if="!warehouseStatusOnly"><dt>付款链接</dt><dd>{{ order.paymentLink || '未填写' }}</dd></div><div v-if="!warehouseStatusOnly"><dt>商品金额 / 运费</dt><dd>{{ money(order.goodsAmount) }} / {{ money(order.shippingFee) }}</dd></div></dl></details><details><summary>备注与附件<small>{{ order.labelImageUrls?.length || 0 }} 个附件</small></summary><p class="m-detail-note">{{ order.note || '未填写备注' }}</p><div class="image-grid"><template v-for="url in order.labelImageUrls || []" :key="url"><a v-if="/\.pdf(?:[?#]|$)/i.test(url)" :href="url" target="_blank" rel="noopener">打开PDF附件 ↗</a><ElImage v-else :src="imageUrl(url,160)" :preview-src-list="mobileImageAttachments" :initial-index="mobileImageAttachments.indexOf(url)" fit="contain" style="width:80px;height:95px"/></template></div></details><div class="m-detail-weight"><span>商品净重</span><strong>{{ orderWeightText(order) }}</strong></div></section>
        <section v-if="order.status==='cancelled'" class="m-detail-card"><header><h3>取消备注</h3><ElButton v-if="auth.can('orders')" text type="primary" :disabled="busy || loading" @click="cancelNoteOpen=true">修改</ElButton></header><p class="m-detail-note">{{ order.cancelNote || '未填写' }}</p></section>
      </section>
      <template v-else
        ><div class="detail-section">
          <div class="panel-title">
            <h3>客户与收货信息</h3>
            <ElTag>{{ statusNames[order.status] }}</ElTag>
          </div>
          <div class="detail-grid">
            <div>
              <span>业务员</span>
              <p>{{ order.ownerAdminName || "未分配" }} · 商城账号：{{ order.userName }}</p>
            </div>
            <div>
              <span>下单时间（北京时间）</span>
              <p>{{ dateTime(order.createdAt) }}</p>
            </div>
            <div>
              <span>联系人</span>
              <p>
                {{ order.contactName }} · {{ order.phone || order.userEmail }}
              </p>
            </div>
            <div>
              <span>国家 / 收货地址</span>
              <p>{{ order.country }} · {{ order.shippingAddress }}</p>
            </div>
            <div>
              <span>备注</span>
              <p style="white-space: pre-wrap">{{ order.note || "—" }}</p>
            </div>
            <div>
              <span>副单号（选填）</span>
              <p>{{ order.secondaryOrderNo || "未填写" }}</p>
              <ElButton v-if="!warehouseStatusOnly" link type="primary" @click="editDetails">{{ order.secondaryOrderNo ? '修改副单号' : '填写副单号' }}</ElButton>
            </div>
          </div>
        </div>
        <section v-if="order.status === 'cancelled'" class="detail-section cancel-note-section" data-testid="cancel-note-detail">
          <div class="panel-title"><h3>取消备注</h3>
            <ElButton v-if="auth.can('orders')" link type="primary" :disabled="editing || busy || loading" @click="cancelNoteOpen = true">{{ order.cancelNote ? '修改取消备注' : '填写取消备注' }}</ElButton>
          </div>
          <p class="cancel-note-text">{{ order.cancelNote || '未填写' }}</p>
        </section>
        <div class="detail-section">
          <div class="panel-title"><h3>商品明细 · {{ order.itemCount }} 件</h3>
            <ElButton :disabled="editing || busy" :loading="loading" @click="refreshDetails">刷新详情</ElButton>
          </div>
          <ElAlert v-if="stockRefreshError" :title="stockRefreshError" type="warning" :closable="false" data-testid="order-stock-stale" />
          <AdaptiveTable :data="order.items"
            ><ElTableColumn label="商品" min-width="230"
              ><template #default="{ row }"
                ><div class="product-cell">
                  <ProductImage :src="row.image" :alt="row.productName" />
                  <div>
                    <span>{{ row.productName }}</span
                    ><small>{{ row.sku }} · {{ row.sizeCode }}</small>
                  </div>
                </div></template
              ></ElTableColumn
            ><ElTableColumn
              prop="quantity"
              label="数量"
              min-width="120"
              align="right"
            ><template #default="{ row }"><div class="order-detail-quantity">
              <span>{{ row.quantity }}</span>
              <VariantStockHint :stock="row.currentStock" :title="stockTitle(row)" :data-testid="`detail-stock-${row.productId}-${row.sizeCode}`" />
            </div></template></ElTableColumn><ElTableColumn v-if="!warehouseStatusOnly" label="单价" width="85" align="right"
              ><template #default="{ row }">{{
                money(row.unitPrice)
              }}</template></ElTableColumn
            ><ElTableColumn v-if="!warehouseStatusOnly" label="金额" width="95" align="right"
              ><template #default="{ row }">{{
                money(row.totalPrice)
              }}</template></ElTableColumn
            ><ElTableColumn label="单件净重（g）" width="105" align="right"><template #default="{ row }">{{ row.unitWeightGrams == null ? "未设置" : row.unitWeightGrams }}</template></ElTableColumn>
            </AdaptiveTable>
          <div v-if="!warehouseStatusOnly" class="detail-grid section-gap">
            <div>
              <span>商品金额</span
              ><strong>{{ money(order.goodsAmount) }}</strong>
            </div>
            <div>
              <span>应付总额（含运费）</span
              ><strong>{{
                money(Number(order.goodsAmount) + Number(form.shippingFee || 0))
              }}</strong>
            </div>
          </div>
        </div>
        <div class="detail-section order-weight-summary" data-testid="order-weight-summary">
          <span>商品净重（kg）</span>
          <strong :class="{ 'weight-incomplete': order.totalWeightGrams == null }">{{ orderWeightText(order) }}</strong>
          <small>按当前商品重量计算，不含包装；刷新详情可获取最新重量。</small>
        </div>
        <div v-if="order.labelImageUrls?.length" class="detail-section">
          <h3>订单附件</h3>
          <div class="image-grid">
            <template v-for="url in order.labelImageUrls" :key="url"
              ><a
                v-if="/\.pdf(?:\?|$)/i.test(url)"
                :href="url"
                target="_blank"
                rel="noopener"
                >打开 PDF 附件 ↗</a
              ><ElImage
                v-else
                :src="imageUrl(url, 160)"
                :preview-src-list="
                  order.labelImageUrls.filter((u) => !u.includes('.pdf'))
                "
                style="width: 90px; height: 110px"
                fit="contain"
            /></template>
          </div>
        </div>
        <ElForm
          ref="formRef"
          :model="form"
            :disabled="!editing || saving"
          label-position="top"
          ><div class="detail-grid">
            <ElFormItem
              label="订单状态"
              prop="status"
              :rules="[{ required: true, message: '请选择状态' }]"
              ><ElSelect v-model="form.status" @change="form.cancelNote = ''"
                ><ElOption
                  v-for="(label, value) in statusNames"
                  :key="value"
                  :value="value"
                  :label="label" /></ElSelect></ElFormItem
            ><ElFormItem v-if="!warehouseStatusOnly"
              :label="`运费（${order.currency||'USD'}）`"
              prop="shippingFee"
              :rules="[{ validator: validateFee, trigger: 'blur' }]"
              ><ElInputNumber
                v-model="form.shippingFee"
                :disabled="warehouseStatusOnly"
                :min="0"
                :precision="2"
                controls-position="right"
                style="width: 100%" /></ElFormItem
            ><ElFormItem
              label="物流单号"
              prop="trackingNo"
              :rules="[{ validator: validateTracking, trigger: 'blur' }]"
              ><ElInput
                v-model.trim="form.trackingNo"
                placeholder="发货时必填" /></ElFormItem
            ><ElFormItem v-if="!warehouseStatusOnly" label="付款链接"
              ><ElInput
                v-model.trim="form.paymentLink"
                :disabled="warehouseStatusOnly"
                placeholder="填写付款地址"
            /></ElFormItem></div>
          <ElFormItem v-if="editing && form.status === 'cancelled'" label="取消备注（选填）">
            <ElInput v-model="form.cancelNote" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="取消备注（选填）" placeholder="填写取消原因，仅后台可见" />
          </ElFormItem>
        </ElForm>
        <ElAlert
          v-if="changes.length"
          type="info"
          :closable="false"
          title="本次修改预览"
          ><div v-for="line in changes" :key="line">{{ line }}</div></ElAlert
        ><ElAlert v-if="error" :title="error" type="error" :closable="false"
          ><ElButton v-if="conflict" text @click="readLatest"
            >读取最新数据（保留草稿）</ElButton
          ></ElAlert
        >
        <div v-if="latest && !warehouseStatusOnly" class="panel">
          <h3>线上最新数据</h3>
          <p>
            状态：{{ statusNames[latest.status] }}；运费：{{
              money(latest.shippingFee)
            }}；物流：{{ latest.trackingNo || "—" }}
          </p>
          <ElButton @click="useLatest">放弃草稿并使用最新数据</ElButton>
        </div>
        </template
      ><OrderOperations v-if="!isPhone" :order-id="order.id" :open="open" :revision="order.version" />
      </template
    ><template #footer><template v-if="isPhone && fullEditing"><ElButton :disabled="busy" @click="editor?.mobileStep > 1 ? editor.mobilePrevious() : cancelEdit()">{{ editor?.mobileStep > 1 ? '上一步' : '取消修改' }}</ElButton><ElButton type="primary" :disabled="!editor?.ready || (editor?.mobileStep === 3 && !editor?.dirty)" :loading="busy" @click="editor?.mobileStep < 3 ? editor.mobileNext() : editor.submit()">{{ editor?.mobileStep < 3 ? '下一步' : '保存修改' }}</ElButton></template><template v-else>
      <MobileActionMenu :disabled="busy"><ElButton v-if="isPhone && !editing" @click="mobileHistoryOpen=true">订单操作记录</ElButton>
      <ElButton v-if="!editing && auth.canEditOrders"
        :disabled="loading || !order || busy" type="primary" plain @click="emit('reorder', order.id)">再来一单</ElButton>
      <ElButton
        v-if="!warehouseStatusOnly"
        :loading="invoiceLoading"
        :disabled="busy || !order || (fullEditing ? editor?.dirty : dirty)"
        :title="order?.currency === 'CNY' ? '人民币订单按本单汇率换算为 USD 导出 PI' : '导出 USD PI'"
        @click="exportInvoice"
        >导出订单详情</ElButton>
      </MobileActionMenu>
      <ElButton
        v-if="!editing && !warehouseStatusOnly"
        type="primary"
        :disabled="loading || !order"
        @click="editDetails"
        >修改订单资料</ElButton
      >
      <ElButton
        v-if="!editing && warehouseStatusOnly"
        type="primary"
        :disabled="loading || !order"
        @click="editDetails"
        >修改订单状态</ElButton
      >
      <ElButton v-if="editing" :disabled="busy" @click="cancelEdit"
        >取消修改</ElButton
      >
      <ElButton :disabled="busy" @click="close()">关闭</ElButton>
      <ElButton
        v-if="editing"
        type="primary"
        :loading="busy"
        :disabled="fullEditing ? !editor?.ready || !editor?.dirty : !dirty"
        @click="fullEditing ? editor.submit() : submit()"
        >保存修改</ElButton
      >
    </template></template></ElDrawer
  >
  <ElDrawer v-if="isPhone" v-model="mobileHistoryOpen" title="订单操作记录" size="100%" append-to-body><OrderOperations v-if="order" :order-id="order.id" :open="mobileHistoryOpen" :revision="order.version"/></ElDrawer>
  <OrderCancellationDialog v-model:open="cancelNoteOpen" :order="order" note-only @saved="cancelNoteSaved" />
</template>
<script setup>
import { useResponsive } from "../composables/responsive";
import MobileActionMenu from './MobileActionMenu.vue';
import AdaptiveTable from "./AdaptiveTable";
import { computed, reactive, ref, watch } from "vue";
import { orderWeightText } from "../utils/productWeights";
import { ElMessage } from "element-plus";
import OrderEditor from "./OrderEditor.vue";
import OrderCancellationDialog from "./OrderCancellationDialog.vue";
import VariantStockHint from './VariantStockHint.vue';
import OrderNumber from "./OrderNumber.vue";
import OrderOperations from "./OrderOperations.vue";
import ProductImage from "./ProductImage.vue";
import { imageUrl } from "../utils/imageUrl";
import { useAdminAuthStore } from "../stores/auth";
import {
  api,
  save,
  download,
  notifyError,
  useDirty,
  statusNames,
  money as formatMoney,
  dateTime,
  confirm,
} from "../composables/workbench";
const props = defineProps({ open: Boolean, id: [Number, String] }),
  emit = defineEmits(["update:open", "saved", "reorder"]),
  auth = useAdminAuthStore();
const { isPhone } = useResponsive();
const mobileHistoryOpen = ref(false);
const mobileGroups = computed(()=>{const groups=new Map();for(const item of order.value?.items || []){const key=String(item.productId)+':'+item.sku;if(!groups.has(key))groups.set(key,{key,sku:item.sku,quantity:0,items:[]});const group=groups.get(key);group.quantity+=Number(item.quantity||0);group.items.push(item);}return [...groups.values()];});
const mobileImageAttachments = computed(() => (order.value?.labelImageUrls || []).filter(url => !/\.pdf(?:[?#]|$)/i.test(url)));
const invoiceLoading = ref(false);
const editing = ref(false),
  editor = ref();
const cancelNoteOpen = ref(false);
const stockRefreshError = ref('');
let detailSerial = 0;
function stockTitle(row) {
  const scope = row.currentStock == null ? '未匹配到该颜色与尺码的库存，历史商品或尺码可能已移除。' : '该颜色与尺码的当前总库存余额，非本单独立欠货';
  return (stockRefreshError.value ? '刷新失败，当前显示上次读取结果。' : '') + scope;
}
function cancelNoteSaved(item) {
  if (!props.open || String(props.id) !== String(item?.id)) return;
  ++detailSerial; loading.value = false;
  populate(item); emit('saved');
}
const fullEditing = computed(
  () => editing.value && auth.canEditOrders,
);
const warehouseStatusOnly = computed(() => auth.userRole === "warehouse");
const busy = computed(
  () => saving.value || editor.value?.saving || editor.value?.uploading,
);
const order = ref(),
  loading = ref(false),
  saving = ref(false),
  form = reactive({
    status: "",
    cancelNote: "",
    shippingFee: 0,
    trackingNo: "",
    paymentLink: "",
  }),
  formRef = ref(),
  error = ref(""),
  conflict = ref(false),
  latest = ref();
const { dirty, markClean, canLeave } = useDirty(() => form);
const money=(value)=>formatMoney(value,order.value?.currency||'USD');
function populate(item, fresh = true) {
  editing.value = false;
  order.value = item;
  Object.assign(form, {
    status: item.status,
    cancelNote: item.cancelNote || "",
    shippingFee: item.shippingFee,
    trackingNo: item.trackingNo,
    paymentLink: item.paymentLink,
  });
  markClean();
  error.value = "";
  if (fresh) stockRefreshError.value = '';
  conflict.value = false;
  latest.value = null;
}
watch(
  () => [props.open, props.id],
  ([open, id]) => {
    if (!open || !id) { ++detailSerial; loading.value = false; return; }
    editing.value = false;
    order.value = null;
    error.value = ''; stockRefreshError.value = '';
    return loadDetails();
  },
  { immediate: true },
);
const changes = computed(() => {
  if (!order.value) return [];
  const labels = {
    status: "状态",
    cancelNote: "取消备注",
    shippingFee: "运费",
    trackingNo: "物流单号",
    paymentLink: "付款链接",
  };
  return Object.keys(form)
    .filter((k) => String(form[k] ?? "") !== String(order.value[k] ?? ""))
    .map(
      (k) =>
        `${labels[k]}：${k === "status" ? statusNames[order.value[k]] : order.value[k] || "未填写"} → ${k === "status" ? statusNames[form[k]] : form[k] || "清空"}`,
    );
});
function validateFee(_r, v, cb) {
  cb(
    typeof v === "number" && Number.isFinite(v) && v >= 0
      ? undefined
      : new Error("运费必须是非负数字"),
  );
}
function validateTracking(_r, v, cb) {
  cb(
    form.status === "shipped" && !v
      ? new Error("发货必须填写物流单号")
      : undefined,
  );
}
async function close(done) {
  if (busy.value) return;
  if (fullEditing.value && !(await editor.value?.canClose())) return;
  if (await canLeave()) {
    markClean();
    emit("update:open", false);
    if (typeof done === "function") done();
  }
}
async function submit() {
  if (saving.value || !(await formRef.value.validate().catch(() => false)))
    return;
  if (form.status === 'cancelled' && order.value.status !== 'cancelled' &&
    !(await confirm('确认取消订单？商品库存将按现有规则返还。'))) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await save(`orders/${props.id}`, { ...form, version: order.value.version });
    populate(result.order);
    ElMessage.success("订单已保存");
    emit("saved");
  } catch (e) {
    error.value = e.message;
    conflict.value = e.status === 409;
  } finally {
    saving.value = false;
  }
}
async function refreshDetails() {
  if (editing.value || busy.value || loading.value) return;
  await loadDetails();
}
async function loadDetails() {
  if (!props.open || !props.id) return;
  const id = props.id;
  const serial = ++detailSerial;
  loading.value = true;
  try {
    const item = (await api(`orders/${id}`)).order;
    if (serial === detailSerial && props.open && props.id === id) populate(item);
  } catch (e) {
    if (serial !== detailSerial || !props.open || props.id !== id) return;
    if (order.value) stockRefreshError.value = '刷新失败，以下库存为上次读取结果，请点击“刷新详情”重试。';
    else error.value = e.message;
    notifyError(e);
  } finally { if (serial === detailSerial) loading.value = false; }
}
async function readLatest() {
  try {
    latest.value = (await api(`orders/${props.id}`)).order;
  } catch (e) {
    notifyError(e);
  }
}
async function useLatest() {
  if (await confirm("放弃当前草稿，使用线上最新订单？")) populate(latest.value);
}
function editDetails() {
  editing.value = true;
}
async function cancelEdit() {
  if (busy.value) return;
  if (fullEditing.value && !(await editor.value?.canClose())) return;
  if (!(await canLeave())) return;
  populate(order.value, false);
}
function detailsSaved(_id, snapshot) {
  // The save response already contains the committed stock snapshot and version.
  cancelNoteSaved(snapshot);
}
async function exportInvoice() {
  if (invoiceLoading.value) return;
  invoiceLoading.value = true;
  try {
    await download(
      `orders/${props.id}/invoice`,
      `订单详情-${order.value.orderNo}.xlsx`,
    );
  } catch (e) {
    notifyError(e);
  } finally { invoiceLoading.value = false; }
}
</script>
<style scoped>
.order-drawer-heading { min-width:0; margin-bottom:16px; }
.order-drawer-heading :deep(.order-number-primary) { font-size:20px; }
.order-drawer-heading :deep(.order-number-secondary) { font-size:12px; }
.order-weight-summary { display: flex; flex-direction: column; gap: 8px; }
.order-weight-summary span, .order-weight-summary small { color: #64748b; }
.order-weight-summary strong { font-size: 16px; color: #0f172a; }
.order-weight-summary .weight-incomplete { color: #b45309; font-size: 14px; }
.cancel-note-text { white-space:pre-wrap; overflow-wrap:anywhere; color:#475569; margin:8px 0 0; }
.order-detail-quantity { display:flex; flex-direction:column; align-items:flex-end; gap:3px; }
</style>

<style scoped>
@media(max-width:767px){
.m-order-detail{color:#182b49}.m-detail-hero{padding:7px 3px 23px}.m-detail-hero>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.m-detail-hero small{font-size:10px;color:#9cabc0}.m-detail-status{font-size:10px;background:#edf3ff;border-radius:7px;padding:5px 9px;color:#7293c2}.m-detail-hero>strong{display:block;font-size:18px;letter-spacing:-.3px;font-weight:700;margin:15px 0 7px}.m-detail-hero>p{font-size:10px;color:#9bacbf;margin:0}.m-detail-card{background:white;border:1px solid #e5edf7;border-radius:18px;margin-bottom:15px;padding:17px}.m-detail-card h3,.m-detail-section-head h3{font-size:12px;font-weight:650;margin:0;color:#435f86}.m-detail-card>h3{margin-bottom:16px}.m-detail-card>header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:13px}.m-detail-card>header>h3{min-width:0;flex:1;overflow-wrap:anywhere}.m-detail-card header>small{font-size:10px;color:#a0aec1;flex-shrink:0}.m-detail-customer{display:flex;align-items:center;gap:12px}.m-detail-customer>span{width:40px;height:44px;border-radius:13px;display:grid;place-items:center;background:#edf3ff;color:#7e9dcb;font-size:16px}.m-detail-customer strong{font-size:14px}.m-detail-customer small{display:block;font-size:10px;color:#9cacc2;margin-top:4px}.m-detail-address{font-size:11px;color:#8a9eba;line-height:1.7;margin:13px 0 0 52px;overflow-wrap:anywhere}.m-detail-section-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:11px}.m-detail-section-head :deep(.el-button),.m-detail-card header :deep(.el-button){font-size:11px;min-height:44px;padding:0 2px}.m-detail-item{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;border-top:1px solid #edf2f9;padding:12px 0}.m-detail-item:last-child{padding-bottom:0}.m-detail-item>div{display:flex;flex-direction:column;gap:5px}.m-detail-item>div:last-child{text-align:right}.m-detail-item strong{font-size:12px}.m-detail-item small{font-size:10px;font-weight:400;color:#a1b0c4}.m-detail-item :deep(.variant-stock-hint){font-size:9px}.m-detail-folds{padding:0 16px}.m-detail-folds>details{border-bottom:1px solid #edf2f8}.m-detail-folds>details:last-child{border-bottom:0}.m-detail-folds summary{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:53px;font-size:12px;color:#6e87a9;cursor:pointer}.m-detail-folds summary>small{font-size:9px;color:#a5b2c5;font-weight:400}.m-detail-folds dl{margin:0 0 15px}.m-detail-folds dl>div{display:grid;grid-template-columns:90px minmax(0,1fr);gap:10px;font-size:10px;margin-bottom:10px}.m-detail-folds dt{color:#a0b0c7}.m-detail-folds dd{margin:0;color:#6983a6;overflow-wrap:anywhere}.m-detail-folds details>p,.m-detail-note{font-size:11px;color:#8ca0bc;line-height:1.8;white-space:pre-wrap}.m-detail-folds .image-grid{padding-bottom:15px}.m-detail-weight{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:17px 0;font-size:12px;color:#6e87a9}.m-detail-weight>span{flex-shrink:0}.m-detail-weight>strong{min-width:0;text-align:right;font-size:11px;font-weight:500;overflow-wrap:anywhere}
}
</style>
