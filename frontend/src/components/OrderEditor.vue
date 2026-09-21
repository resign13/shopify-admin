<template>
  <component
    :is="embedded ? 'div' : ElDrawer"
    :model-value="open"
    :title="id ? '订单详情' : '新增订单'"
    size="900px"
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
    <ElForm v-if="ready" ref="formRef" :model="form" :disabled="saving" label-position="top">
      <h3>客户与收货信息</h3>
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
                :disabled="lockedLines"
                controls-position="right"
                size="small"
                @update:model-value="setMatrixQuantity(row, sizeCode, $event)"
              />
              <small v-if="lineFor(row, sizeCode)" class="order-size-price">
                {{ money(lineFor(row, sizeCode).unitPrice) }} / 件
              </small>
            </div></template
        ></ElTableColumn
        ><ElTableColumn label="小计" width="105" align="right"
          ><template #default="{ row }">{{ money(matrixRowSubtotal(row)) }}</template
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
      <ElTable :data="inventoryImpact" size="small" empty-text="添加商品后显示库存变化">
        <ElTableColumn prop="sku" label="库存核对 / SKU"/><ElTableColumn prop="sizeCode" label="尺码"/>
        <ElTableColumn prop="current" label="当前余额"/><ElTableColumn prop="change" label="此次库存增减"/>
        <ElTableColumn label="预计保存后余额"><template #default="{row}"><ElTag :type="row.after < 0 ? 'danger' : 'info'">{{ row.after }}{{ row.after < 0 ? ' · 欠货' : '' }}</ElTag></template></ElTableColumn>
      </ElTable>
      <ElAlert v-if="inventoryImpact.some(row => row.after < 0)" title="保存后存在欠货，仍可提交。入库时会抵减欠货余额。" type="warning" :closable="false"/>
      <div class="detail-grid section-gap">
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
        <div class="numeric">
          <small>商品金额 {{ money(subtotal) }}</small>
          <h3 class="section-gap">
            订单总额 {{ money(subtotal + Number(form.shippingFee || 0)) }}
          </h3>
        </div>
      </div>
      <div v-if="id" class="detail-grid">
        <ElFormItem label="订单状态"
          ><ElSelect v-model="form.status"
            ><ElOption
              v-for="(label, value) in statusNames"
              :key="value"
              :value="value"
              :label="label" :disabled="statusDisabled(value)" /></ElSelect
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
          :max="9"
          @busy="uploading = $event"
      /></ElFormItem>
      <ElAlert
        v-if="id && dirty"
        :title="`保存前核对：商品 ${originalCount} → ${units} 件；总额 ${money(originalTotal)} → ${money(subtotal + Number(form.shippingFee || 0))}`"
        type="warning"
        :closable="false"
      />
    </ElForm>
    <template v-if="!embedded" #footer
      ><ElButton :disabled="saving || uploading" @click="close()">取消</ElButton
      ><ElButton
        type="primary"
        :loading="saving"
        :disabled="!ready || uploading || (!!id && !dirty)"
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
import { computed, reactive, ref, watch } from "vue";
import { ElDrawer, ElMessage } from "element-plus";
import ImageUploader from "./ImageUploader.vue";
import ProductPicker from "./ProductPicker.vue";
import {
  api,
  save,
  useDirty,
  confirm,
  productName,
  money,
  statusNames,
} from "../composables/workbench";
const props = defineProps({
    open: Boolean,
    id: [Number, String],
    embedded: Boolean,
  }),
  emit = defineEmits(["update:open", "saved"]);
const form = reactive({
  userId: null,
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
  status: "pending_payment",
  trackingNo: "",
  paymentLink: "",
  shippingFee: 0,
  items: [],
});
const fields = [
  { key: "contactName", label: "收货人", required: true },
  { key: "phone", label: "联系电话", required: true },
  { key: "country", label: "国家", required: true },
  { key: "contactValue", label: "联系邮箱" },
  { key: "address", label: "详细地址", required: true },
  { key: "apartment", label: "公寓 / 房间" },
  { key: "city", label: "城市" },
  { key: "state", label: "州 / 省" },
  { key: "zip", label: "邮编" },
];
const originalItems = ref([]);
const uploading = ref(false);
const isImage = (url) =>
  /\.(jpg|jpeg|png|webp|gif|avif|bmp)(?:[?#]|$)/i.test(url);
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
  return [...grouped.values()];
});
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
function setMatrixQuantity(row, sizeCode, value) {
  if (lockedLines.value) return;
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
function matrixRowSubtotal(row) {
  return matrixSizes.value.reduce((sum, sizeCode) => {
    const line = lineFor(row, sizeCode);
    return sum + Number(line?.quantity || 0) * Number(line?.unitPrice || 0);
  }, 0);
}
function removeMatrixProduct(row) {
  if (lockedLines.value) return;
  form.items = form.items.filter((item) => item.productId !== row.productId);
}
function statusDisabled(value) {
  if (status.value === 'cancelled' || status.value === 'completed') return value !== status.value;
  return status.value === 'shipped' && !['shipped','completed'].includes(value);
}
const inventoryImpact = computed(() => {
  const rows = new Map();
  for (const row of [...originalItems.value, ...form.items]) {
    const key = `${row.productId}:${row.sizeCode}`;
    if (!rows.has(key)) rows.set(key, {...row, before: 0, next: 0});
  }
  for (const row of originalItems.value) rows.get(`${row.productId}:${row.sizeCode}`).before += Number(row.quantity || 0);
  for (const row of form.items) rows.get(`${row.productId}:${row.sizeCode}`).next += Number(row.quantity || 0);
  return [...rows.values()].map(row => {
    const stock = products[row.productId]?.sizePrices?.find(s => s.sizeCode === row.sizeCode)?.stock;
    const change = lockedLines.value ? 0 : form.status === 'cancelled' ? row.before : row.before - row.next;
    return {...row, current: stock ?? '待刷新', change: change > 0 ? `+${change}` : change, after: stock == null ? '待刷新' : stock + change};
  });
});
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
      labelImageUrls: (item.labelImageUrls || []).filter(isImage),
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
  () => [props.open, props.id],
  async ([open, id]) => {
    if (!open) return;
    const current = ++serial;
    loading.value = true;
    ready.value = false;
    uploading.value = false;
    error.value = "";
    conflict.value = false;
    latest.value = null;
    try {
      categories.value = (await api("catalog-options")).items;
      if (id) {
        const item = (await api(`orders/${id}`)).order;
        if (current !== serial) return;
        await populate(item);
      } else {
        Object.assign(form, {
          userId: null,
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
        ready.value = true;
      }
      await searchCustomers();
    } catch (e) {
      error.value = e.message;
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
  if (!(await canLeave())) return false;
  markClean();
  return true;
}
defineExpose({ submit, canClose, saving, uploading, ready, dirty });
async function close(done) {
  if (saving.value || uploading.value) return;
  if (await canLeave()) {
    markClean();
    emit("update:open", false);
    if (typeof done === "function") done();
  }
}
async function submit() {
  if (
    saving.value ||
    uploading.value ||
    !(await formRef.value.validate().catch(() => false))
  )
    return;
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
      `${props.id ? "保存订单修改" : "创建待付款订单"}：${units.value} 件，总额 ${money(subtotal.value + Number(form.shippingFee))}。保存后同步调整现货库存。`,
    ))
  )
    return;
  saving.value = true;
  error.value = "";
  try {
    const payload = {
      ...form,
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
    conflict.value = e.status === 409;
  } finally {
    saving.value = false;
  }
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
