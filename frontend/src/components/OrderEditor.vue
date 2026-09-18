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
            : '保存时校验实际库存，新增订单扣减库存，修改数量仅按差额调整。合同未送和待入库不受影响。'
        "
        type="info"
        :closable="false"
      />
      <ElTable :data="form.items" empty-text="请添加商品并选择真实尺码"
        ><ElTableColumn label="商品 / SKU" min-width="190"
          ><template #default="{ row }"
            ><span class="product-name" :title="row.productName">{{
              row.productName
            }}</span
            ><small>{{ row.sku }}</small></template
          ></ElTableColumn
        ><ElTableColumn label="真实尺码" width="135"
          ><template #default="{ row }"
            ><ElSelect
              v-model="row.sizeCode"
              :disabled="lockedLines"
              @change="selectSize(row)"
              ><ElOption
                v-for="s in sizeOptions(row)"
                :key="s.sizeCode"
                :value="s.sizeCode"
                :label="s.sizeCode" /></ElSelect></template></ElTableColumn
        ><ElTableColumn label="数量" width="130"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.quantity"
              :min="1"
              :max="2147483647"
              :precision="0"
              :disabled="lockedLines"
              controls-position="right"
              style="width: 110px" /></template></ElTableColumn
        ><ElTableColumn label="单价（USD）" width="140"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.unitPrice"
              :min="0"
              :precision="2"
              :disabled="lockedLines"
              controls-position="right"
              style="width: 120px" /></template></ElTableColumn
        ><ElTableColumn label="小计" width="100" align="right"
          ><template #default="{ row }">{{
            money(row.quantity * row.unitPrice)
          }}</template></ElTableColumn
        ><ElTableColumn label="操作" width="65"
          ><template #default="{ $index }"
            ><ElButton
              link
              type="danger"
              :disabled="lockedLines"
              @click="form.items.splice($index, 1)"
              >移除</ElButton
            ></template
          ></ElTableColumn
        ></ElTable
      >
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
        products[id] = (await api(`products/${id}`)).product;
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
  if (form.items.length >= 500) {
    ElMessage.warning("最多 500 个尺码行");
    return;
  }
  if (!product.sizePrices?.length) {
    ElMessage.warning("该商品尚未配置尺码");
    return;
  }
  products[product.id] = product;
  const size = product.sizePrices.find(
    (s) =>
      !form.items.some(
        (r) => r.productId === product.id && r.sizeCode === s.sizeCode,
      ),
  );
  if (!size) {
    ElMessage.info("该商品所有尺码均已添加，请直接调整数量");
    return;
  }
  form.items.push({
    productId: product.id,
    productName: productName(product),
    sku: product.sku,
    sizeCode: size.sizeCode,
    quantity: 1,
    unitPrice: size.price,
  });
  ElMessage.success("已添加商品，可继续选择其他商品或尺码");
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
  if (
    !form.items.length ||
    form.items.some(
      (r) =>
        !Number.isInteger(r.quantity) ||
        r.quantity < 1 ||
        typeof r.unitPrice !== "number" ||
        !Number.isFinite(r.unitPrice) ||
        r.unitPrice < 0,
    )
  ) {
    error.value = "请添加商品，并填写有效的正整数数量和非负单价";
    return;
  }
  if (
    new Set(form.items.map((r) => `${r.productId}:${r.sizeCode}`)).size !==
    form.items.length
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
      items: form.items.map(({ productId, sizeCode, quantity, unitPrice }) => ({
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
