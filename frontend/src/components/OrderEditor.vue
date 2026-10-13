<template>
  <component
    :is="embedded ? 'div' : ElDrawer"
    :model-value="open"
    :title="id ? '订单详情' : sourceOrderId ? `再来一单 · 来源订单 ${sourceOrderNo || '加载中…'}` : draftId ? '订单草稿' : '新增订单'"
    size="min(900px, 100vw)"
    :before-close="close"
    :close-on-click-modal="false"
  >
    <ElSkeleton v-if="loading" :rows="12" animated />
    <ElAlert v-if="error" :title="error" type="error" :closable="false"
      ><ElButton v-if="conflict" text @click="readLatest"
        >查看线上最新订单</ElButton
      ></ElAlert
    >
    <section v-if="latest" class="panel">
      <h3>线上最新订单（草稿已保留）</h3>
      <p>
        {{ latest.orderNo }} · {{ statusNames[latest.status] }} ·
        {{ latest.itemCount }} 件 · {{ money(latest.totalAmount) }}
      </p>
      <ElTable :data="latest.items"
        ><ElTableColumn prop="sku" label="SKU" /><ElTableColumn
          prop="sizeCode"
          label="尺码" /><ElTableColumn
          prop="quantity"
          label="数量" /><ElTableColumn
          prop="unitPrice"
          label="单价" /></ElTable
      ><ElButton @click="adoptLatest">放弃草稿，使用最新资料</ElButton>
    </section>
    <ElAlert v-if="ready && readOnly" title="正在查看其他业务员的草稿，仅供查阅，编辑和提交由草稿创建人完成。" type="info" :closable="false" />
    <p v-if="ready && !id && !readOnly" class="small-note" role="status">{{ draftSavedAt ? `已保存至服务器 · ${dateTime(draftSavedAt)}${dirty ? ' · 有未保存修改' : ''}` : '尚未保存为草稿；可填写一部分后点击“保存草稿”，稍后从“我的草稿”继续。' }}</p>
    <ElForm v-if="ready" ref="formRef" :model="form" :disabled="saving || readOnly" label-position="top">
      <CustomerTemplates v-if="!id && !readOnly" :profile="form" :customer="customers.find(customer => customer.id === form.userId)" @apply="applyTemplate" @busy="templateBusy = $event" />
      <ElFormItem v-if="auth.isSuperAdmin" label="归属业务员">
        <ElSelect v-model="form.ownerAdminId" clearable filterable placeholder="未分配" class="full-width" @change="form.ownerConfirmed = true">
          <ElOption v-for="person in salespeople" :key="person.id" :value="person.id" :label="person.name" :disabled="person.status !== 'active' && person.id !== form.ownerAdminId" />
        </ElSelect>
        <small>管理员代建可指定业务员；仅调整归属不影响库存。</small>
      </ElFormItem>
      <ElAlert v-if="!form.ownerConfirmed" type="warning" title="原业务员已停用，请重新选择业务员或确认未分配。" :closable="false">
        <ElButton text @click="form.ownerAdminId = null; form.ownerConfirmed = true">确认设为未分配</ElButton>
      </ElAlert>
      <p v-if="!auth.isSuperAdmin" class="small-note">归属业务员：{{ auth.user?.name }}（固定为本人）</p>
      <h3>客户与收货信息</h3>
      <ElAlert v-if="customerUnavailable && !form.userId" type="warning" title="原商城客户已停用或不存在，请选择有效客户；原收货资料已保留。" :closable="false" />
      <ElFormItem
        label="商城客户"
        prop="userId"
        :rules="[{ required: true, message: '请选择客户' }]"
        ><ElSelect
          v-model="form.userId"
          filterable
          remote
          :remote-method="searchCustomers"
          :loading="customerLoading"
          placeholder="搜索客户姓名、公司或邮箱"
          class="full-width"
          ><ElOption
            v-for="c in customers"
            :key="c.id"
            :value="c.id"
            :label="`${c.name} · ${c.companyName || c.email}`" /></ElSelect
        ><small
          >可搜索已启用的商城账号；新客户请先由管理员创建商城账号。</small
        ></ElFormItem
      >
      <div class="detail-grid">
        <ElFormItem
          v-for="field in fields"
          :key="field.key"
          :label="field.label"
          :prop="field.key"
          :rules="
            field.required
              ? [
                  {
                    required: true,
                    whitespace: true,
                    message: `请填写${field.label}`,
                  },
                ]
              : []
          "
          ><ElInput v-model="form[field.key]" :maxlength="500"
        /></ElFormItem>
      </div>
      <div class="panel-title section-gap">
        <h3>商品明细</h3>
        <ElButton :disabled="lockedLines" @click="picker = true"
          >＋ 添加商品</ElButton
        >
      </div>
      <ElAlert
        :title="
          lockedLines
            ? '已取消、已发货、已完成订单保留原商品明细；可修改客户与收货资料。'
            : '后台允许欠货下单。新增扣减现货余额，修改仅按数量差额调整；实际余额以保存时为准。'
        "
        type="info"
        :closable="false"
      />
      <ElTable :data="matrixRows" empty-text="请添加颜色商品并填写至少一个尺码数量"
        ><ElTableColumn label="款号" min-width="125"
          ><template #default="{ row }"
            ><span class="product-name" :title="row.sku">{{ row.sku }}</span></template
          ></ElTableColumn
        ><ElTableColumn
          v-for="sizeCode in matrixSizes"
          :key="sizeCode"
          :label="sizeCode"
          min-width="76"
          align="center"
          ><template #default="{ row }"
            ><div class="order-size-matrix-cell">
              <ElInputNumber
                :model-value="quantityFor(row, sizeCode)"
                :min="0"
                :max="2147483647"
                :precision="0"
                :disabled="lockedLines || !sizeAvailable(row, sizeCode)"
                :controls="false"
                size="small"
                @update:model-value="setMatrixQuantity(row, sizeCode, $event)"
              />
              <small v-if="sizeAvailable(row, sizeCode)" class="order-size-stock"
                :class="{ 'is-shortage': inventoryFor(row, sizeCode).after < 0 }"
                :data-testid="`size-stock-${row.productId}-${sizeCode}`"
                :title="`当前库存 ${inventoryFor(row, sizeCode).current}；预计保存后库存，实际以保存时为准`"
              >库存 {{ inventoryFor(row, sizeCode).after }}{{ inventoryFor(row, sizeCode).after < 0 ? ' · 欠货' : '' }}</small>
              <small v-else class="order-size-stock is-unavailable">—</small>
            </div></template
        ></ElTableColumn
        ><ElTableColumn label="总件数" width="85" align="right"
          ><template #default="{ row }">{{ orderProductQuantity(form.items, row.productId) }} 件</template
        ></ElTableColumn
        ><ElTableColumn label="操作" width="70"
          ><template #default="{ row }"
            ><ElButton
              link
              type="danger"
              :disabled="lockedLines"
              @click="removeMatrixProduct(row)"
              >移除</ElButton
            ></template
          ></ElTableColumn
        ></ElTable
      >
      <section v-if="form.pendingItems.length" class="reorder-issues" data-testid="reorder-issues">
        <strong>待处理商品 · {{ form.pendingItems.length }} 项</strong>
        <p>以下商品未计入本次金额。请移除，或先移除后通过“添加商品”重新选择。</p>
        <div v-for="(item, index) in form.pendingItems" :key="index" class="inherited-attachment">
          <span>{{ item.sku || item.productName }} · {{ item.sizeCode || '未指定尺码' }} · {{ item.quantity }} 件 <small>{{ item.reason }}</small></span>
          <ElButton link type="danger" @click="form.pendingItems.splice(index, 1)">移除待处理项</ElButton>
        </div>
      </section>
      <div class="order-goods-summary" data-testid="order-goods-summary">
        <div class="order-amount-summary">
          <ElFormItem
            label="运费（USD）"
            prop="shippingFee"
            :rules="[{ validator: validateFee }]"
            ><ElInputNumber
              v-model="form.shippingFee"
              :min="0"
              :precision="2"
              controls-position="right"
          /></ElFormItem>
          <div class="order-amount-values">
            <div><span>商品金额</span><strong>{{ money(subtotal) }}</strong></div>
            <h3>订单总额 {{ money(subtotal + Number(form.shippingFee || 0)) }}</h3>
          </div>
        </div>
        <div v-if="sourceOrderId || activeDraftId" class="reorder-pricing">
          <span>{{ sourceOrderId ? '运费沿用原单，请在创建前核对。' : '草稿已按当前商品资料恢复，请在创建前核对金额及运费。' }}</span>
          <ElPopover v-if="priceChanges.length" trigger="click" placement="bottom" :width="380" :popper-style="{maxWidth:'calc(100vw - 32px)'}">
            <template #reference><ElButton link type="primary">已按最新价格更新 {{ priceChanges.length }} 项</ElButton></template>
            <div class="reorder-price-details" data-testid="reorder-price-details">
              <strong>原单／保存时单价 → 当前单价</strong>
              <p v-for="row in priceChanges" :key="`${row.productId}:${row.sizeCode}`">{{ row.sku }} · {{ row.sizeCode }}：{{ row.oldUnitPrices.map(money).join(' / ') }} → {{ money(row.unitPrice) }}</p>
            </div>
          </ElPopover>
          <span v-else>商品按当前尺码价格计算。</span>
        </div>
        <div class="order-draft-weight" data-testid="order-draft-weight">
          <div class="order-weight-heading">
            <div class="order-weight-total">
              <span class="order-weight-label">商品总重量（kg）</span>
              <span class="order-weight-value" :class="{ 'is-placeholder': weightValuePlaceholder }" role="status" aria-live="polite">{{ draftWeightText }}</span>
              <ElPopover
                v-if="!weightLoading && (weightError || weightPreview.missingWeightQuantity)"
                trigger="click"
                placement="bottom-start"
                :width="320"
                :popper-style="{ maxWidth: 'calc(100vw - 32px)' }"
              >
                <template #reference>
                  <ElButton text size="small" class="order-weight-hint" :aria-label="weightError ? '查看重量计算异常' : `查看${weightPreview.missingWeightQuantity}件未设置重量的商品`">
                    <ElIcon><InfoFilled /></ElIcon>
                    <span>{{ weightError ? '查看原因' : `${weightPreview.missingWeightQuantity} 件未设置` }}</span>
                  </ElButton>
                </template>
                <div class="order-weight-details" data-testid="order-weight-details">
                  <template v-if="weightError">
                    <strong>暂未取得重量</strong>
                    <p>{{ weightError }}；可点击“刷新重量”重试，不影响保存订单。</p>
                  </template>
                  <template v-else>
                    <strong>{{ weightPreview.missingWeightQuantity }} 件商品未设置重量</strong>
                    <p>当前重量不完整，仅统计已设置重量的商品。</p>
                    <ul>
                      <li v-for="item in weightPreview.missingItems" :key="`${item.productId}:${item.sizeCode}`">
                        <span>{{ item.sku }} · {{ item.sizeCode || '未指定尺码' }}</span><span>{{ item.quantity }} 件</span>
                      </li>
                    </ul>
                  </template>
                </div>
              </ElPopover>
            </div>
            <ElButton class="order-weight-refresh" :loading="weightLoading" :disabled="!weightItems.length" @click="refreshWeightPreview">刷新重量</ElButton>
          </div>
          <small class="order-weight-caption">按当前商品净重计算，不含包装。</small>
        </div>
      </div>
      <ElAlert v-if="inventoryImpact.some(row => row.after < 0)" title="保存后存在欠货，仍可提交。入库时会抵减欠货余额。" type="warning" :closable="false"/>
      <div v-if="id" class="detail-grid">
        <ElFormItem label="订单状态"
          ><ElSelect v-model="form.status"
            ><ElOption
              v-for="(label, value) in statusNames"
              :key="value"
              :value="value"
              :label="label" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="物流单号"
          ><ElInput v-model.trim="form.trackingNo" placeholder="发货时必填"
        /></ElFormItem>
        <ElFormItem label="付款链接"
          ><ElInput v-model.trim="form.paymentLink"
        /></ElFormItem>
      </div>
      <ElFormItem label="备注"
        ><ElInput
          v-model="form.note"
          type="textarea"
          :rows="3"
          maxlength="5000"
      /></ElFormItem>
      <ElFormItem label="备注图片（最多 9 张）"
        ><ImageUploader
          v-model="form.labelImageUrls"
          :max="remainingImageSlots"
          @busy="imageUploading = $event"
      /></ElFormItem>
      <ElFormItem v-if="form.inheritedAttachmentUrls.length" label="已保留的辅料／历史附件">
        <div class="inherited-attachments" data-testid="inherited-attachments">
          <div v-for="(url, index) in form.inheritedAttachmentUrls" :key="url" class="inherited-attachment">
            <ElImage v-if="isImage(url) && attachmentHref(url)" :src="attachmentHref(url)" :preview-src-list="form.inheritedAttachmentUrls.filter(isImage).map(attachmentHref).filter(Boolean)" fit="contain" preview-teleported />
            <a v-if="attachmentHref(url)" :href="attachmentHref(url)" target="_blank" rel="noopener">附件 {{ index + 1 }} · {{ isImage(url) ? '图片' : /\.pdf(?:[?#]|$)/i.test(url) ? 'PDF' : '文件' }}</a>
            <span v-else>附件 {{ index + 1 }}（地址暂不支持打开）</span>
            <ElButton link type="danger" @click="form.inheritedAttachmentUrls.splice(index, 1)">移除附件</ElButton>
          </div>
          <small>仅修改本订单附件清单，不删除原文件或影响来源订单。</small>
        </div>
      </ElFormItem>
      <ElFormItem label="PDF 附件"><small v-if="hasInheritedPdf">如需替换，请先移除上方保留的 PDF；历史附件可继续保留。</small><PdfAttachment v-else v-model="form.labelPdfUrl" @busy="pdfUploading = $event" /></ElFormItem>
      <ElAlert
        v-if="id && dirty"
        :title="`保存前核对：商品 ${originalCount} → ${units} 件；总额 ${money(originalTotal)} → ${money(subtotal + Number(form.shippingFee || 0))}`"
        type="warning"
        :closable="false"
      />
    </ElForm>
    <template v-if="!embedded" #footer
      ><ElButton :disabled="saving || uploading" @click="close()">取消</ElButton
      ><ElButton v-if="!id && !readOnly" :loading="saving" :disabled="!ready || uploading" @click="saveDraft">保存草稿</ElButton
      ><ElButton
        v-if="!readOnly"
        type="primary"
        :loading="saving"
        :disabled="!ready || uploading || (!!id && !dirty) || !!form.pendingItems.length || !form.ownerConfirmed"
        @click="submit"
        >{{ id ? "保存订单修改" : "创建待付款订单" }}</ElButton
      ></template
    >
  </component>
  <ProductPicker
    v-model:visible="picker"
    :model-value="[]"
    :categories="categories"
    @select="addProduct"
    @select-many="(rows) => rows.forEach(addProduct)"
  />
</template>
<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { ElDrawer, ElMessage } from "element-plus";
import { InfoFilled } from "@element-plus/icons-vue";
import ImageUploader from "./ImageUploader.vue";
import ProductPicker from "./ProductPicker.vue";
import CustomerTemplates from "./CustomerTemplates.vue";
import PdfAttachment from "./PdfAttachment.vue";
import { customerFields, customerProfile, applyCustomerProfile } from "../utils/customerTemplates";
import { compareProductCategories } from "../utils/catalogOrder";
import { useAdminAuthStore } from "../stores/auth";
import { orderProductQuantity, orderVariantInventory } from "../utils/orderQuantities";
import { formatWeightKg, orderWeightPreviewItems } from "../utils/productWeights";
import { reorderForm, reorderPriceChanges, applyReorderPrices, attachmentHref } from "../utils/orderReorder";
import {
  api,
  save,
  useDirty,
  confirm,
  productName,
  money,
  dateTime,
  statusNames,
} from "../composables/workbench";
const props = defineProps({
    open: Boolean,
    id: [Number, String],
    sourceOrderId: [Number, String],
    draftId: [Number, String],
    embedded: Boolean,
  }),
  emit = defineEmits(["update:open", "saved"]);
const form = reactive({
  userId: null,
  ownerAdminId: null,
  contactName: "",
  phone: "",
  country: "",
  contactValue: "",
  address: "",
  apartment: "",
  city: "",
  state: "",
  zip: "",
  note: "",
  labelImageUrls: [],
  labelPdfUrl: "",
  inheritedAttachmentUrls: [],
  pendingItems: [],
  ownerConfirmed: true,
  status: "pending_payment",
  trackingNo: "",
  paymentLink: "",
  shippingFee: 0,
  items: [],
});
const auth = useAdminAuthStore(), salespeople = ref([]);
const fields = customerFields;
const originalItems = ref([]);
const sourceOrderNo = ref(''), customerUnavailable = ref(false);
const activeDraftId = ref(null), draftVersion = ref(''), draftKey = ref(''), draftSavedAt = ref(''), readOnly = ref(false);
const priceChanges = computed(() => reorderPriceChanges(form.items));
const imageUploading = ref(false), pdfUploading = ref(false), templateBusy = ref(false);
const uploading = computed(() => imageUploading.value || pdfUploading.value || templateBusy.value);
const isImage = (url) =>
  /\.(jpg|jpeg|png|webp|gif|avif|bmp)(?:[?#]|$)/i.test(url);
const remainingImageSlots = computed(() => Math.max(0, 9 - form.inheritedAttachmentUrls.filter(isImage).length));
const hasInheritedPdf = computed(() => form.inheritedAttachmentUrls.some(url => /\.pdf(?:[?#]|$)/i.test(url)));
const ready = ref(false),
  loading = ref(false),
  saving = ref(false),
  error = ref(""),
  conflict = ref(false),
  latest = ref(),
  formRef = ref(),
  customers = ref([]),
  customerLoading = ref(false),
  categories = ref([]),
  picker = ref(false),
  products = reactive({}),
  version = ref(""),
  requestId = ref(""),
  status = ref(""),
  originalCount = ref(0),
  originalTotal = ref(0);
const { dirty, markClean, canLeave } = useDirty(() => form),
  lockedLines = computed(() =>
    ["cancelled", "shipped", "completed"].includes(status.value),
  ),
  subtotal = computed(
    () =>
      form.items.reduce(
        (sum, row) =>
          sum +
          Math.round(Number(row.unitPrice || 0) * 100) *
            Number(row.quantity || 0),
        0,
      ) / 100,
  ),
  units = computed(() =>
    form.items.reduce((sum, row) => sum + Number(row.quantity || 0), 0),
  );
const matrixRows = computed(() => {
  const grouped = new Map();
  for (const row of form.items) {
    if (!grouped.has(row.productId)) {
      grouped.set(row.productId, {
        productId: row.productId,
        productName: row.productName,
        sku: row.sku,
      });
    }
  }
  return [...grouped.values()].sort((left, right) => compareProductCategories(products[left.productId], products[right.productId]));
});
const weightItems = computed(() => orderWeightPreviewItems(form.items));
const emptyWeightPreview = () => ({ knownWeightGrams: "0", totalWeightGrams: "0", missingWeightQuantity: 0, missingItems: [] });
const weightPreview = ref(emptyWeightPreview()), weightLoading = ref(false), weightError = ref("");
const draftWeightText = computed(() => {
  if (weightLoading.value) return "计算中…";
  if (weightError.value) return "暂未取得重量";
  const value = weightPreview.value;
  if (value.totalWeightGrams != null) return `${formatWeightKg(value.totalWeightGrams)} kg`;
  return BigInt(value.knownWeightGrams || "0") > 0n ? `已知 ${formatWeightKg(value.knownWeightGrams)} kg` : "未设置";
});
const weightValuePlaceholder = computed(() => weightLoading.value || !!weightError.value ||
  (weightPreview.value.totalWeightGrams == null && BigInt(weightPreview.value.knownWeightGrams || "0") === 0n));
let weightSerial = 0, weightTimer, weightController;
function cancelWeightPreview() {
  ++weightSerial;
  clearTimeout(weightTimer);
  weightController?.abort();
}
async function loadWeightPreview(current, items) {
  const controller = new AbortController();
  weightController = controller;
  try {
    const result = await api("orders/weights/preview", {
      method: "POST", body: JSON.stringify({ items }), signal: controller.signal,
    });
    if (current === weightSerial && props.open) weightPreview.value = result;
  } catch (error) {
    if (current === weightSerial && error.name !== "AbortError") weightError.value = error.message;
  } finally {
    if (current === weightSerial) weightLoading.value = false;
  }
}
function refreshWeightPreview(debounce = false) {
  cancelWeightPreview();
  weightError.value = "";
  if (!props.open || !ready.value || !weightItems.value.length) {
    weightPreview.value = emptyWeightPreview();
    weightLoading.value = false;
    return;
  }
  const current = weightSerial, items = weightItems.value;
  weightLoading.value = true;
  if (debounce === true) weightTimer = setTimeout(() => loadWeightPreview(current, items), 250);
  else loadWeightPreview(current, items);
}
watch(() => [props.open, ready.value, JSON.stringify(weightItems.value)], () => refreshWeightPreview(true));
onBeforeUnmount(cancelWeightPreview);
const matrixSizes = computed(() => {
  const seen = new Set();
  const sizes = [];
  for (const row of matrixRows.value) {
    const product = products[row.productId];
    const configured = product?.sizePrices?.map((item) => item.sizeCode) || [];
    const existing = form.items
      .filter((item) => item.productId === row.productId)
      .map((item) => item.sizeCode);
    for (const sizeCode of [...configured, ...existing]) {
      if (sizeCode && !seen.has(sizeCode)) {
        seen.add(sizeCode);
        sizes.push(sizeCode);
      }
    }
  }
  return sizes;
});
function lineFor(row, sizeCode) {
  return form.items.find(
    (item) => item.productId === row.productId && item.sizeCode === sizeCode,
  );
}
function priceFor(row, sizeCode) {
  const line = lineFor(row, sizeCode);
  if (line) return Number(line.unitPrice || 0);
  return Number(
    products[row.productId]?.sizePrices?.find((item) => item.sizeCode === sizeCode)?.price || 0,
  );
}
function quantityFor(row, sizeCode) {
  return Number(lineFor(row, sizeCode)?.quantity || 0);
}
function sizeAvailable(row, sizeCode) {
  return !!lineFor(row, sizeCode) || products[row.productId]?.sizePrices?.some(size => size.sizeCode === sizeCode);
}
function setMatrixQuantity(row, sizeCode, value) {
  if (lockedLines.value || !sizeAvailable(row, sizeCode)) return;
  const next = Math.max(0, Math.min(2147483647, Math.trunc(Number(value) || 0)));
  let line = lineFor(row, sizeCode);
  if (!line && next > 0) {
    line = {
      productId: row.productId,
      productName: row.productName,
      sku: row.sku,
      sizeCode,
      quantity: 0,
      unitPrice: priceFor(row, sizeCode),
    };
    form.items.push(line);
  }
  if (line) line.quantity = next;
}
function removeMatrixProduct(row) {
  if (lockedLines.value) return;
  form.items = form.items.filter((item) => item.productId !== row.productId);
}
const inventoryImpact = computed(() => {
  const rows = new Map();
  for (const row of [...originalItems.value, ...form.items]) {
    const key = `${row.productId}:${row.sizeCode}`;
    if (!rows.has(key)) rows.set(key, {...row, before: 0, next: 0});
  }
  for (const row of originalItems.value) rows.get(`${row.productId}:${row.sizeCode}`).before += Number(row.quantity || 0);
  for (const row of form.items) rows.get(`${row.productId}:${row.sizeCode}`).next += Number(row.quantity || 0);
  return [...rows.values()].sort((a, b) => compareProductCategories(products[a.productId], products[b.productId])).map(row => {
    const stock = products[row.productId]?.sizePrices?.find(s => s.sizeCode === row.sizeCode)?.stock;
    return {...row, ...orderVariantInventory(stock, row.before, row.next, status.value, form.status)};
  });
});
function inventoryFor(row, sizeCode) {
  const impact = inventoryImpact.value.find(item => item.productId === row.productId && item.sizeCode === sizeCode);
  if (impact) return impact;
  const stock = products[row.productId]?.sizePrices?.find(item => item.sizeCode === sizeCode)?.stock;
  return orderVariantInventory(stock);
}
let serial = 0,
  customerSerial = 0;
async function searchCustomers(keyword = "") {
  const current = ++customerSerial;
  customerLoading.value = true;
  try {
    const result = await api(
      "orders/customers?" +
        new URLSearchParams({ page: 1, pageSize: 100, keyword }),
    );
    if (current === customerSerial) {
      const chosen = customers.value.find((c) => c.id === form.userId);
      customers.value = result.items;
      if (chosen && !customers.value.some((c) => c.id === chosen.id))
        customers.value.unshift(chosen);
    }
  } catch (e) {
    if (current === customerSerial) error.value = e.message;
  } finally {
    if (current === customerSerial) customerLoading.value = false;
  }
}
async function populate(item) {
  originalItems.value = item.items.map(row => ({...row}));
  version.value = item.version;
  status.value = item.status;
  originalCount.value = item.itemCount;
  originalTotal.value = item.totalAmount;
  Object.assign(
    form,
    Object.fromEntries(
      Object.keys(form)
        .filter((k) => k !== "items")
        .map((k) => [k, item[k] ?? ""]),
    ),
    {
      address: item.address || item.shippingAddress || "",
      labelImageUrls: [], labelPdfUrl: '',
      inheritedAttachmentUrls: [...new Set([...(item.labelImageUrls || []), item.labelPdfUrl].filter(Boolean))],
      pendingItems: [], ownerConfirmed: true,
      items: item.items.map((row) => ({ ...row })),
    },
  );
  if (!customers.value.some((c) => c.id === item.userId))
    customers.value.unshift({
      id: item.userId,
      name: item.userName,
      companyName: item.companyName,
      email: item.userEmail,
    });
  markClean();
  ready.value = true;
  await Promise.all(
    [...new Set(item.items.map((r) => r.productId))].map(async (id) => {
      try {
        products[id] = (await api(`inventory/${id}`)).product;
      } catch {}
    }),
  );
}
watch(
  () => [props.open, props.id, props.sourceOrderId, props.draftId],
  async ([open, id, sourceId, savedId]) => {
    const current = ++serial;
    if (!open) { ++customerSerial; return; }
    loading.value = true;
    ready.value = false;
    imageUploading.value = false; pdfUploading.value = false; templateBusy.value = false;
    error.value = "";
    conflict.value = false;
    latest.value = null;
    sourceOrderNo.value = ''; customerUnavailable.value = false;
    activeDraftId.value = null; draftVersion.value = ''; draftSavedAt.value = ''; readOnly.value = false;
    draftKey.value = crypto.randomUUID();
    Object.keys(products).forEach(key => delete products[key]);
    customers.value = [];
    try {
      const catalog = await api("catalog-options");
      if (current !== serial) return;
      categories.value = catalog.items;
      if (auth.isSuperAdmin) {
        const people = await api("salespeople");
        if (current !== serial) return;
        salespeople.value = people.items;
      }
      if (id) {
        const item = (await api(`orders/${id}`)).order;
        if (current !== serial) return;
        await populate(item);
      } else {
        Object.assign(form, {
          userId: null,
          ownerAdminId: null,
          contactName: "",
          phone: "",
          country: "",
          contactValue: "",
          address: "",
          apartment: "",
          city: "",
          state: "",
          zip: "",
          note: "",
          labelImageUrls: [],
          labelPdfUrl: "",
          inheritedAttachmentUrls: [], pendingItems: [], ownerConfirmed: true,
          status: "pending_payment",
          trackingNo: "",
          paymentLink: "",
          shippingFee: 0,
          items: [],
        });
        originalItems.value = [];
        status.value = "pending_payment";
        requestId.value = crypto.randomUUID();
        markClean();
        if (savedId) {
          const result = await api(`orders/drafts/${savedId}`);
          if (current !== serial) return;
          Object.assign(form, reorderForm({...result, issues:result.draft.pendingItems, ownerNeedsConfirmation:!result.draft.ownerConfirmed}));
          form.labelImageUrls = [...result.draft.labelImageUrls]; form.labelPdfUrl = result.draft.labelPdfUrl;
          sourceOrderNo.value = result.sourceOrderNo;
          customerUnavailable.value = result.customerUnavailable;
          result.products.forEach(product => { products[product.id] = product; });
          if (result.customer && !result.customerUnavailable) customers.value = [result.customer];
          activeDraftId.value = result.id; draftVersion.value = result.version;
          draftSavedAt.value = result.updatedAt; requestId.value = result.submitRequestId;
          readOnly.value = !result.canEdit;
          markClean();
        } else if (sourceId) {
          const result = await api(`orders/${sourceId}/reorder-draft`);
          if (current !== serial) return;
          Object.assign(form, reorderForm(result));
          sourceOrderNo.value = result.sourceOrderNo;
          customerUnavailable.value = result.customerUnavailable;
          result.products.forEach(product => { products[product.id] = product; });
          if (result.customer && !result.customerUnavailable) customers.value = [result.customer];
        }
        ready.value = true;
      }
      await searchCustomers();
    } catch (e) {
      if (current === serial) error.value = e.message;
    } finally {
      if (current === serial) loading.value = false;
    }
  },
  { immediate: true },
);
function sizeOptions(row) {
  const sizes = products[row.productId]?.sizePrices || [];
  return sizes.some((s) => s.sizeCode === row.sizeCode)
    ? sizes
    : [...sizes, { sizeCode: row.sizeCode }];
}
async function applyTemplate(item) {
  if (props.id || saving.value || imageUploading.value || pdfUploading.value) return;
  const current = customerProfile(form);
  const hasCustomerInfo = current.userId || current.labelImageUrls.length || Object.values(current).some(value => typeof value === 'string' && value.trim());
  if (hasCustomerInfo && !(await confirm('填入模板将替换当前客户资料、备注及附件，商品明细和金额保持不变。是否继续？'))) return;
  applyCustomerProfile(form, item.profile);
  form.inheritedAttachmentUrls = [];
  if (!customers.value.some(customer => customer.id === item.customer.id)) customers.value.unshift({ ...item.customer });
  formRef.value?.clearValidate();
  ElMessage.success(`已填入客户模板：${item.name}`);
}
function addProduct(product) {
  if (!product.sizePrices?.length) {
    ElMessage.warning("该商品尚未配置尺码");
    return;
  }
  products[product.id] = product;
  const existingSizes = new Set(
    form.items
      .filter((row) => row.productId === product.id)
      .map((row) => row.sizeCode),
  );
  const missingSizes = product.sizePrices.filter(
    (size) => !existingSizes.has(size.sizeCode),
  );
  if (!missingSizes.length) {
    ElMessage.info("该商品所有尺码均已添加，请直接调整数量");
    return;
  }
  if (form.items.length + missingSizes.length > 500) {
    ElMessage.warning("最多 500 个尺码行");
    return;
  }
  form.items.push(
    ...missingSizes.map((size) => ({
      productId: product.id,
      productName: productName(product),
      sku: product.sku,
      sizeCode: size.sizeCode,
      quantity: 0,
      unitPrice: Number(size.price || 0),
    })),
  );
  ElMessage.success(
    `已添加 ${productName(product)} 的 ${missingSizes.length} 个尺码，请填写订购数量`,
  );
}
function selectSize(row) {
  const size = products[row.productId]?.sizePrices.find(
    (s) => s.sizeCode === row.sizeCode,
  );
  if (size) row.unitPrice = size.price;
}
function validateFee(_r, value, callback) {
  callback(
    typeof value === "number" && Number.isFinite(value) && value >= 0
      ? undefined
      : new Error("请填写非负运费"),
  );
}
async function canClose() {
  if (saving.value || uploading.value) return false;
  if (!readOnly.value && !(await canLeave())) return false;
  markClean();
  return true;
}
defineExpose({ submit, canClose, saving, uploading, ready, dirty });
async function close(done) {
  if (saving.value || uploading.value) return;
  if (readOnly.value || await canLeave()) {
    markClean();
    emit("update:open", false);
    if (typeof done === "function") done();
  }
}
async function submit() {
  if (
    readOnly.value ||
    saving.value ||
    uploading.value ||
    !(await formRef.value.validate().catch(() => false))
  )
    return;
  if (form.pendingItems.length || !form.ownerConfirmed) {
    error.value = '请先处理异常商品并确认业务员归属';
    return;
  }
  const invalidRow = form.items.find(
    (r) =>
      !Number.isInteger(r.quantity) ||
      r.quantity < 0 ||
      typeof r.unitPrice !== "number" ||
      !Number.isFinite(r.unitPrice) ||
      r.unitPrice < 0,
  );
  const items = form.items.filter((r) => r.quantity > 0);
  if (invalidRow || !items.length) {
    error.value = "请至少填写一个尺码，并确保数量为非负整数、单价为非负金额";
    return;
  }
  if (
    new Set(items.map((r) => `${r.productId}:${r.sizeCode}`)).size !==
    items.length
  ) {
    error.value = "同一商品尺码不能重复，请合并数量";
    return;
  }
  if (
    !(await confirm(
      `${props.id ? "保存订单修改" : "创建待付款订单"}：${units.value} 件，总额 ${money(subtotal.value + Number(form.shippingFee))}。${props.sourceOrderId ? `运费 ${money(form.shippingFee)} 沿用原单，请确认。` : ''}保存后同步调整现货库存。`,
    ))
  )
    return;
  saving.value = true;
  error.value = "";
  try {
    const payload = {
      ...form,
      ...(props.sourceOrderId ? { sourceOrderId: props.sourceOrderId } : {}),
      ...(activeDraftId.value ? {draftId:activeDraftId.value, draftVersion:draftVersion.value} : {}),
      ownerAdminId: auth.isSuperAdmin ? (form.ownerAdminId || null) : auth.user.id,
      items: items.map(({ productId, sizeCode, quantity, unitPrice }) => ({
        productId,
        sizeCode,
        quantity,
        unitPrice,
      })),
      ...(props.id
        ? { version: version.value }
        : { requestId: requestId.value }),
    };
    const result = await save(
      props.id ? `orders/${props.id}/details` : "orders",
      payload,
      props.id ? "PUT" : "POST",
    );
    markClean();
    emit("update:open", false);
    emit("saved", result.order?.id);
    ElMessage.success(props.id ? "订单修改已保存" : "订单已创建");
  } catch (e) {
    error.value = e.message;
    if (e.data?.code === 'reorder_price_changed') {
      applyReorderPrices(form.items, products, e.data.changes || []);
      ElMessage.warning(e.message);
    }
    conflict.value = !!props.id && e.status === 409;
  } finally {
    saving.value = false;
  }
}
async function saveDraft() {
  if (props.id || readOnly.value || saving.value || uploading.value || !ready.value) return;
  saving.value = true; error.value = '';
  try {
    const result = await save(activeDraftId.value ? `orders/drafts/${activeDraftId.value}` : 'orders/drafts', {
      draftKey:draftKey.value, version:draftVersion.value, submitRequestId:requestId.value,
      draft:{...form, sourceOrderId:props.sourceOrderId || null},
    }, activeDraftId.value ? 'PUT' : 'POST');
    activeDraftId.value = result.id; draftVersion.value = result.version;
    draftSavedAt.value = result.updatedAt; requestId.value = result.submitRequestId;
    markClean(); ElMessage.success('草稿已保存，可从“我的草稿”继续编辑');
  } catch(e) { error.value = e.message; }
  finally { saving.value = false; }
}
async function readLatest() {
  try {
    latest.value = (await api(`orders/${props.id}`)).order;
  } catch (e) {
    error.value = e.message;
  }
}
async function adoptLatest() {
  if (await confirm("放弃草稿，使用线上最新订单？")) {
    await populate(latest.value);
    latest.value = null;
    conflict.value = false;
    error.value = "";
  }
}
</script>
<style scoped>
.order-size-stock { display: block; color: var(--muted); font-size: 11px; line-height: 1.5; font-weight: 400; white-space: normal; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.order-size-stock.is-shortage { color: var(--el-color-danger); }
.order-size-stock.is-unavailable { color: #a8abb2; }

.reorder-pricing { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; color: #64748b; font-size: 12px; padding: 0 0 12px; }
.reorder-price-details { max-height: 240px; overflow-y: auto; font-size: 12px; }
.reorder-issues { margin-top: 12px; padding: 12px; background: #fff7ed; border-radius: 6px; color: #9a3412; font-size: 13px; }
.reorder-issues p { margin: 6px 0; }
.inherited-attachments { width: 100%; }
.inherited-attachment { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid #e8edf3; }
.inherited-attachment .el-image { width: 54px; height: 54px; }
.inherited-attachment > .el-button { margin-left: auto; }
.inherited-attachment small { display: block; color: #b45309; }
.order-goods-summary {
  padding: 16px 8px;
  color: var(--muted);
  border-bottom: 1px solid var(--line);
}
.order-amount-summary, .order-weight-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.order-amount-summary :deep(.el-form-item) { margin-bottom: 0; }
.order-amount-values { margin-left: auto; text-align: right; }
.order-amount-values > div { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.order-amount-values > div { justify-content: flex-end; }
.order-amount-values h3 { margin: 10px 0 0; color: var(--text); }
.order-amount-values strong {
  color: var(--text);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}
.order-draft-weight { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--line); }
.order-weight-heading { align-items: center; gap: 8px 16px; }
.order-weight-total { display: flex; flex: 1; min-width: 0; align-items: center; flex-wrap: wrap; gap: 6px 12px; }
.order-weight-label { white-space: nowrap; }
.order-weight-value { color: var(--text); font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.order-weight-value.is-placeholder { color: var(--muted); font-size: 12px; font-weight: 400; }
.order-weight-hint { height: 28px; margin: 0; padding: 4px 6px; color: #b45309; font-size: 12px; font-weight: 400; }
.order-weight-hint :deep(.el-icon) { margin-right: 4px; font-size: 13px; }
.order-weight-hint:hover, .order-weight-hint:focus-visible { color: #92400e; background: #fffbeb; }
.order-weight-refresh { flex-shrink: 0; }
.order-weight-caption { display: block; margin-top: 4px; font-size: 12px; line-height: 1.6; }
.order-weight-details { color: #334155; font-size: 12px; line-height: 1.6; }
.order-weight-details > strong { font-size: 13px; font-weight: 600; }
.order-weight-details p { margin: 6px 0 0; color: #64748b; overflow-wrap: anywhere; }
.order-weight-details ul { display: grid; gap: 8px; margin: 12px 0 0; padding: 12px 0 0; max-height: 200px; overflow-y: auto; list-style: none; border-top: 1px solid #e8edf3; }
.order-weight-details li { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.order-weight-details li > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.order-weight-details li > span:last-child { flex-shrink: 0; color: #b45309; font-variant-numeric: tabular-nums; }
@media (max-width: 520px) {
  .order-goods-summary { padding: 14px 0; }
  .order-weight-total { flex-basis: 100%; }
  .order-weight-refresh { margin-left: auto; }
}
</style>
