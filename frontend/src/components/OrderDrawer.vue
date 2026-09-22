<template>
  <ElDrawer
    :model-value="open"
    :title="order ? `订单详情 · ${order.orderNo}` : '订单详情'"
    size="800px"
    :before-close="close"
    ><ElSkeleton v-if="loading" :rows="10" animated /><template v-if="order">
      <OrderEditor
        v-if="fullEditing"
        ref="editor"
        :open="true"
        :id="id"
        embedded
        @saved="detailsSaved"
      />
      <template v-else
        ><div class="detail-section">
          <div class="panel-title">
            <h3>客户与收货信息</h3>
            <ElTag>{{ statusNames[order.status] }}</ElTag>
          </div>
          <div class="detail-grid">
            <div>
              <span>业务员</span>
              <p>{{ order.userName }} / {{ order.companyName || "—" }}</p>
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
          </div>
        </div>
        <div class="detail-section">
          <h3>商品明细 · {{ order.itemCount }} 件</h3>
          <ElTable :data="order.items"
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
              width="70"
              align="right"
            /><ElTableColumn label="单价" width="85" align="right"
              ><template #default="{ row }">{{
                money(row.unitPrice)
              }}</template></ElTableColumn
            ><ElTableColumn label="金额" width="95" align="right"
              ><template #default="{ row }">{{
                money(row.totalPrice)
              }}</template></ElTableColumn
            ></ElTable
          >
          <div class="detail-grid section-gap">
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
              ><ElSelect v-model="form.status"
                ><ElOption
                  v-for="(label, value) in statusNames"
                  :key="value"
                  :value="value"
                  :label="label" :disabled="['cancelled','completed'].includes(order.status) ? value !== order.status : order.status === 'shipped' && !['shipped','completed'].includes(value)" /></ElSelect></ElFormItem
            ><ElFormItem
              label="运费（USD）"
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
            ><ElFormItem label="付款链接"
              ><ElInput
                v-model.trim="form.paymentLink"
                :disabled="warehouseStatusOnly"
                placeholder="填写付款地址"
            /></ElFormItem></div
        ></ElForm>
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
        <div v-if="latest" class="panel">
          <h3>线上最新数据</h3>
          <p>
            状态：{{ statusNames[latest.status] }}；运费：{{
              money(latest.shippingFee)
            }}；物流：{{ latest.trackingNo || "—" }}
          </p>
          <ElButton @click="useLatest">放弃草稿并使用最新数据</ElButton>
        </div>
        <RouterLink
          v-if="auth.can('audit-logs')"
          :to="{
            path: '/audit-logs',
            query: { module: 'orders', objectId: order.id },
          }"
          class="small-note"
          >查看此订单操作日志 →</RouterLink
        ></template
      ></template
    ><template #footer>
      <ElButton
        v-if="!editing && !warehouseStatusOnly"
        :disabled="loading || !order"
        @click="editDetails"
        >修改订单资料</ElButton
      >
      <ElButton
        v-if="!editing && warehouseStatusOnly"
        :disabled="loading || !order"
        @click="editDetails"
        >修改订单状态</ElButton
      >
      <ElButton v-if="editing" :disabled="busy" @click="cancelEdit"
        >取消修改</ElButton
      >
      <ElButton
        v-if="!warehouseStatusOnly"
        :disabled="busy || !order || (fullEditing ? editor?.dirty : dirty)"
        @click="exportInvoice"
        >导出订单详情</ElButton
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
    </template></ElDrawer
  >
</template>
<script setup>
import { computed, reactive, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { ElMessage } from "element-plus";
import OrderEditor from "./OrderEditor.vue";
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
  money,
  dateTime,
  confirm,
} from "../composables/workbench";
const props = defineProps({ open: Boolean, id: [Number, String] }),
  emit = defineEmits(["update:open", "saved"]),
  auth = useAdminAuthStore();
const editing = ref(false),
  editor = ref();
const fullEditing = computed(
  () => editing.value && ["admin", "sales"].includes(auth.userRole),
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
    shippingFee: 0,
    trackingNo: "",
    paymentLink: "",
  }),
  formRef = ref(),
  error = ref(""),
  conflict = ref(false),
  latest = ref();
const { dirty, markClean, canLeave } = useDirty(() => form);
function populate(item) {
  editing.value = false;
  order.value = item;
  Object.assign(form, {
    status: item.status,
    shippingFee: item.shippingFee,
    trackingNo: item.trackingNo,
    paymentLink: item.paymentLink,
  });
  markClean();
  error.value = "";
  conflict.value = false;
  latest.value = null;
}
watch(
  () => [props.open, props.id],
  async ([open, id]) => {
    if (!open || !id) return;
    editing.value = false;
    loading.value = true;
    order.value = null;
    try {
      populate((await api(`orders/${id}`)).order);
    } catch (e) {
      error.value = e.message;
      notifyError(e);
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);
const changes = computed(() => {
  if (!order.value) return [];
  const labels = {
    status: "状态",
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
  saving.value = true;
  error.value = "";
  try {
    await save(`orders/${props.id}`, { ...form, version: order.value.version });
    populate((await api(`orders/${props.id}`)).order);
    ElMessage.success("订单已保存");
    emit("saved");
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
  populate(order.value);
}
async function detailsSaved() {
  try {
    populate((await api(`orders/${props.id}`)).order);
    emit("saved");
  } catch (e) {
    notifyError(e);
  }
}
async function exportInvoice() {
  try {
    await download(
      `orders/${props.id}/invoice`,
      `订单详情-${order.value.orderNo}.xlsx`,
    );
  } catch (e) {
    notifyError(e);
  }
}
</script>
