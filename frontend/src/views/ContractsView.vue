<template>
  <PageHeader
    title="合同管理"
    mobile-title="采购合同"
    :mobile-description="`${list.total} 份合同`"
    description="从现有商品创建采购合同，按真实尺码登记合同未送。"
    eyebrow="ORDERS / 订单业务"
    ><MobileActionMenu v-if="isPhone" icon-only label="合同操作"><ElButton @click="start">新建采购合同</ElButton><ElButton @click="mobileListTools = !mobileListTools">{{ mobileListTools ? '收起列表设置' : '列表设置' }}</ElButton></MobileActionMenu><ElButton v-else type="primary" @click="start">＋ 新建合同</ElButton></PageHeader
  >
  <section class="panel goods-list-panel">
    <MobileGoodsSearch v-if="isPhone" v-model="keyword" placeholder="搜索合同号、工厂或款号" @submit="list.apply({ keyword })" />
    <div v-if="isPhone" class="mobile-goods-heading"><span>合同记录</span><small>按创建时间排列</small></div>
    <form v-else class="filters" @submit.prevent="list.apply({ keyword })">
      <ElInput
        v-model="keyword"
        clearable
        placeholder="搜索合同编号、工厂、款号或 SKU"
      /><ElButton native-type="submit">查询</ElButton>
    </form>
    <DataTable
      storage-key="contracts"
      :mobile-actions="false"
      :mobile-tools="mobileListTools"
      :rows="list.rows"
      :columns="columns"
      :total="list.total"
      :page="Number(list.query.page)"
      :page-size="Number(list.query.pageSize)"
      :loading="list.loading"
      :error="list.error"
      @retry="list.load"
      @page="list.query.page = $event"
      @page-size="list.apply({ pageSize: $event })"
    >
      <template #mobile-card="{ row }"><MobileGoodsCard :title="row.factoryName" :eyebrow="row.contractNo" @open="show(row)"><template #badge><ElTag :type="row.cancelled ? 'info' : 'success'" size="small">{{ row.cancelled ? '已取消' : '有效' }}</ElTag></template><template #footer><span>交货 {{ row.deliveryDate }}</span><strong class="mobile-goods-count">{{ row.quantity.toLocaleString() }}<small> 件</small></strong></template><template #actions><MobileActionMenu label="更多"><ElButton @click="show(row)">合同详情</ElButton><ElButton :loading="exporting === row.id" @click="exportFile(row)">导出合同 Excel</ElButton></MobileActionMenu></template></MobileGoodsCard></template>
      <template #cancelled="{row}">{{row.cancelled ? "已取消" : "有效"}}</template>
      <template #createdAt="{ row }">{{ dateTime(row.createdAt) }}</template>
      <template #actions="{ row }"
        ><ElButton link type="primary" @click="show(row)">合同详情</ElButton
        ><ElButton
          link
          type="primary"
          :loading="exporting === row.id"
          @click="exportFile(row)"
          >导出</ElButton
        ></template
      >
    </DataTable>
  </section>
  <ElDrawer
    v-model="open"
    :title="detail ? detail.contractNo + ' · 合同详情' : editingId ? '修改采购合同' : '新建采购合同'"
    size="min(1040px, 96vw)"
    :before-close="close"
  >
    <template v-if="!detail">
      <nav v-if="isPhone" class="mobile-contract-steps" aria-label="合同步骤"><span v-for="(label,index) in ['工厂与交期','商品与数量','确认合同']" :key="label" :class="{ active: step === index, done: step > index }"><b>{{ step > index ? '✓' : index+1 }}</b>{{ label }}</span></nav>
      <ElSteps v-else :active="step" finish-status="success" simple
        ><ElStep title="工厂与交期" /><ElStep title="商品与数量" /><ElStep
          title="确认合同"
      /></ElSteps>
      <ElForm v-if="step === 0" label-position="top" class="section-gap">
        <ElFormItem label="甲方（必填）"
          ><ElInput v-model.trim="form.partyA" maxlength="200"
        /></ElFormItem>
        <ElFormItem label="乙方 / 工厂名称（必填）"
          ><ElInput v-model.trim="form.partyB" maxlength="200"
        /></ElFormItem>
        <ElFormItem label="合同号（必填）"
          ><ElInput v-model.trim="form.contractNo" maxlength="100"
        /></ElFormItem>
        <ElFormItem label="交货时间（必填）"
          ><ElDatePicker
            v-model="form.deliveryDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择交货日期"
        /></ElFormItem>
        <ElFormItem label="合同备注"
          ><ElInput
            v-model="form.note"
            type="textarea"
            :rows="3"
            maxlength="5000"
            show-word-limit
        /></ElFormItem>
        <ElFormItem label="备注附件（最多9张）"
          ><ImageUploader purpose="contract"
            v-model="form.attachments"
            :max="9"
            @busy="busy.attachments = $event"
        /></ElFormItem>
      </ElForm>
      <div v-if="step === 1" class="section-gap">
        <ElButton @click="picker = true">选择已有商品</ElButton
        ><span class="small-note">
          每个颜色独立登记，最多 100 个商品；数量为本合同新增数量。</span
        >
      </div>
      <ElAlert
        v-if="step === 2"
        class="section-gap"
        type="info"
        :closable="false"
        :title="editingId ? '保存后按本次增减数量同步合同未送；当前库存不变。' : '确认创建后，以下数量将累加到对应商品的合同未送；当前库存和合格数量保持不变。'"
      />
    </template>
    <ElAlert
      v-if="detail?.cancelled"
      title="合同已取消，合同未送已回退"
      type="info"
      :closable="false"
    />
    <div v-if="detail || step === 2" class="contract-summary">
      <strong
        >{{ current.partyA }} /
        {{ current.partyB || current.factoryName }}</strong
      ><span>交货时间：{{ current.deliveryDate }}</span
      ><span>{{ current.items.length }} 个颜色商品 · {{ total }} 件</span>
      <p v-if="current.note">{{ current.note }}</p>
    </div>
    <template v-if="detail || step > 0">
      <ElEmpty v-if="!current.items.length" description="请选择合同商品" />
      <article
        v-for="(item, index) in current.items"
        :key="item.productId"
        class="contract-item"
      >
        <header>
          <div>
            <strong :title="item.title">{{ item.title }}</strong
            ><small
              >款号 {{ item.productCode }} · {{ item.sku }} ·
              {{ item.colorName }}</small
            >
          </div>
          <ElButton
            v-if="!detail && step === 1"
            link
            type="danger"
            @click="form.items.splice(index, 1)"
            >移除</ElButton
          >
        </header>
        <ElInput
          v-if="!detail && step === 1"
          v-model="item.colorCode"
          placeholder="填写色号"
          maxlength="100"
        />
        <div class="size-grid">
          <label
            v-for="size in detail
              ? item.displayQuantities
                ? standardSizes
                : item.sizes
              : standardSizes"
            :key="size"
            ><span>{{ size }}</span
            ><ElInputNumber
              v-if="!detail && step === 1"
              v-model="item.quantities[size]"
              :min="0"
              :max="2147483647"
              :precision="0"
              controls-position="right"
            /><b v-else>{{
              (item.displayQuantities || item.quantities)[size] || 0
            }}</b></label
          >
        </div>
        <div class="small-note">数量合计：{{ sum(item) }} 件</div>
      </article>
    </template>
    <div v-if="detail || step > 0" class="contract-images">
      <section
        v-for="[key, label] in [
          ['styleImage', '统一款式图'],
          ['sizeChartImage', '统一尺码表'],
        ]"
        :key="key"
      >
        <h4>{{ label }}</h4>
        <ImageUploader purpose="contract"
          v-if="!detail && step === 1"
          :model-value="form[key] ? [form[key]] : []"
          :max="1"
          @update:model-value="form[key] = $event[0] || ''"
          @busy="busy[key] = $event"
        />
        <ElImage
          v-else-if="current[key]"
          :src="imageUrl(current[key], 640)"
          :preview-src-list="[current[key]]"
          fit="contain"
          preview-teleported
        />
      </section>
    </div>
    <ElAlert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="section-gap"
    />
    <template #footer
      ><ElButton :disabled="saving || uploading" @click="close()">{{
        detail ? "关闭" : "取消"
      }}</ElButton
      ><template v-if="!detail"
        ><ElButton
          v-if="step > 0"
          :disabled="saving || uploading"
          @click="step--"
          >上一步</ElButton
        ><ElButton
          v-if="step < 2"
          type="primary"
          :disabled="uploading"
          @click="next"
          >下一步</ElButton
        ><ElButton v-else type="primary" :loading="saving" @click="submit"
          >{{ editingId ? '保存修改' : '确认创建' }} · {{ total }} 件</ElButton
        ></template
      ><ElButton v-if="detail && !detail.cancelled" @click="editContract"
        >修改合同</ElButton
      >
      <ElButton
        v-if="detail && !detail.cancelled"
        type="danger"
        :loading="saving"
        @click="cancelContract"
        >取消合同</ElButton
      >
      <ElButton
        v-if="detail"
        type="primary"
        :loading="exporting === detail.id"
        @click="exportFile(detail)"
        >导出合同 Excel</ElButton
      ></template
    >
  </ElDrawer>
  <ProductPicker
    v-model:visible="picker"
    :model-value="form.items.map((i) => i.productId)"
    :categories="categories"
    @select="add"
    @select-many="addMany"
  />
</template>
<script setup>
import { errorMessage } from '../utils/adminErrors.js';
import { useResponsive } from '../composables/responsive';
import MobileActionMenu from '../components/MobileActionMenu.vue';
import MobileGoodsCard from '../components/mobile-goods/MobileGoodsCard.vue';
import MobileGoodsSearch from '../components/mobile-goods/MobileGoodsSearch.vue';
import { computed, reactive, ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import ProductPicker from "../components/ProductPicker.vue";
import ImageUploader from "../components/ImageUploader.vue";
import { imageUrl } from "../utils/imageUrl";
import { compareProductCategories } from "../utils/catalogOrder";
import {
  api,
  save,
  download,
  useList,
  useDirty,
  dateTime,
  productName,
  notifyError,
  confirm,
} from "../composables/workbench";
const { isPhone } = useResponsive();
const mobileListTools = ref(false);
const standardSizes = ["S", "M", "L", "XL", "XXL"];
const editingId = ref(null);
const productInfo = reactive({});
const list = useList("contracts", { keyword: "" }),
  keyword = ref(list.query.keyword),
  open = ref(false),
  step = ref(0),
  detail = ref(null),
  picker = ref(false),
  saving = ref(false),
  exporting = ref(null),
  error = ref(""),
  categories = ref([]),
  busy = reactive({});
const form = reactive({
  requestId: "",
  partyA: "",
  partyB: "",
  contractNo: "",
  styleImage: "",
  sizeChartImage: "",
  attachments: [],
  deliveryDate: "",
  note: "",
  items: [],
});
const { markClean, canLeave } = useDirty(() => form);
const current = computed(() => detail.value || form),
  sum = (item) =>
    Object.values(item.quantities).reduce((n, v) => n + Number(v || 0), 0),
  total = computed(() => current.value.items.reduce((n, i) => n + sum(i), 0)),
  uploading = computed(() => Object.values(busy).some(Boolean));

const columns = [
  { prop: "contractNo", label: "合同编号", width: 145 },
  { prop: "factoryName", label: "工厂名称", minWidth: 180 },
  { prop: "deliveryDate", label: "交货时间", width: 125 },
  { prop: "cancelled", label: "状态", width: 80 },
  { prop: "quantity", label: "数量", width: 100 },
  { prop: "createdAt", label: "创建时间", minWidth: 165 },
  { prop: "creatorName", label: "创建人", width: 120 },
  { prop: "actions", label: "操作", width: 160 },
];
function start() {
  editingId.value = null;
  Object.assign(form, {
    requestId: crypto.randomUUID(),
    styleImage: "",
    sizeChartImage: "",
    attachments: [],
    partyA: "",
    partyB: "",
    contractNo: "",
    deliveryDate: "",
    note: "",
    items: [],
  });
  Object.keys(busy).forEach((k) => delete busy[k]);
  detail.value = null;
  step.value = 0;
  error.value = "";
  markClean();
  open.value = true;
}
async function close(done) {
  if (saving.value || uploading.value) return;
  if (await canLeave()) {
    markClean();
    open.value = false;
    if (typeof done === "function") done();
  }
}
async function add(row) {
  try {
    if (form.items.some((i) => i.productId === row.id)) return;
    if (form.items.length >= 100) throw Error("每份合同最多 100 个商品");
    const result = await api("products/" + row.id);
    const p = result.product;
    if (!p?.sizePrices?.length) throw Error("该商品没有尺码，请先完善商品资料");
    productInfo[p.id] = p;
    if (form.items.some((i) => i.productId === p.id)) return;
    form.items.push({
      productId: p.id,
      productCode: p.productCode || p.sku,
      sku: p.sku,
      title: productName(p),
      colorName: p.colorName,
      colorCode: p.colorName || "",
      image: p.image || "",
      sizeChartImage: p.sizeChartImage || "",
      sizes: standardSizes,
      actualSizes: p.sizePrices.map((s) => s.sizeCode),
      sizeMapping: Object.fromEntries(
        standardSizes.map((s) => [
          s,
          p.sizePrices.find((r) => r.sizeCode.toUpperCase() === s)?.sizeCode ||
            "",
        ]),
      ),
      quantities: Object.fromEntries(standardSizes.map((s) => [s, 0])),
    });
    form.items.sort((a, b) => compareProductCategories(productInfo[a.productId], productInfo[b.productId]));
  } catch (e) {
    notifyError(e);
  }
}
async function addMany(rows) {
  for (const row of rows) await add(row);
}
function next() {
  error.value = "";
  if (
    step.value === 0 &&
    (!form.partyA || !form.partyB || !form.contractNo || !form.deliveryDate)
  ) {
    error.value = "请填写甲方、乙方、合同号和交货日期";
    return;
  }
  if (step.value === 1) {
    for (const item of form.items) {
      const selected = Object.values(item.sizeMapping).filter(Boolean);
      if (
        new Set(selected).size !== selected.length ||
        standardSizes.some(
          (s) => item.quantities[s] > 0 && !item.sizeMapping[s],
        )
      ) {
        error.value = "所填数量的尺码在商品中不存在或对应关系重复，请先完善商品尺码资料";
        return;
      }
    }
    if (
      !form.items.length ||
      form.items.some(
        (i) =>
          sum(i) <= 0 ||
          Object.values(i.quantities).some(
            (n) => !Number.isSafeInteger(n) || n < 0,
          ),
      )
    ) {
      error.value = "每个商品至少填写一个尺码数量，数量须为非负整数";
      return;
    }
  }
  if (step.value === 1 && (!form.styleImage || !form.sizeChartImage)) {
    error.value = "请上传统一款式图和统一尺码表";
    return;
  }
  step.value++;
}
async function submit() {
  if (saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await save(
      editingId.value ? `contracts/${editingId.value}` : "contracts",
      form,
      editingId.value ? "PUT" : "POST",
    );
    detail.value = result.item;
    markClean();
    ElMessage.success("合同已保存，合同未送数量已同步");
    await list.load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}
async function show(row) {
  try {
    detail.value = (await api("contracts/" + row.id)).item;
    error.value = "";
    markClean();
    open.value = true;
  } catch (e) {
    notifyError(e);
  }
}
async function editContract() {
  try {
    const source = detail.value;
    const draft = JSON.parse(JSON.stringify(source));
    for (const item of draft.items) {
      const p = (await api(`products/${item.productId}`)).product;
      productInfo[p.id] = p;
      item.actualSizes = p.sizePrices.map((s) => s.sizeCode);
      if (item.displayQuantities) {
        item.quantities = { ...item.displayQuantities };
      } else {
        const previous = { ...item.quantities };
        item.sizeMapping = Object.fromEntries(
          standardSizes.map((s) => [
            s,
            item.actualSizes.find((a) => a.toUpperCase() === s) || "",
          ]),
        );
        for (const actual of Object.keys(previous).filter(
          (a) => previous[a] && !Object.values(item.sizeMapping).includes(a),
        )) {
          const label = standardSizes.find(
            (s) =>
              !item.sizeMapping[s] &&
              actual
                .toUpperCase()
                .split(/[^A-Z]+/)
                .includes(s),
          );
          if (!label)
            throw Error(`旧合同包含 ${actual}，请先核对该尺码的标准对应关系`);
          item.sizeMapping[label] = actual;
        }
        item.quantities = Object.fromEntries(
          standardSizes.map((s) => [s, previous[item.sizeMapping[s]] || 0]),
        );
      }
      item.displayQuantities = null;
      item.sizes = [...standardSizes];
    }
    draft.items.sort((a, b) => compareProductCategories(productInfo[a.productId], productInfo[b.productId]));
    Object.assign(form, draft, { requestId: crypto.randomUUID() });
    editingId.value = source.id;
    detail.value = null;
    step.value = 0;
    error.value = "";
    markClean();
  } catch (e) {
    notifyError(e);
  }
}
async function cancelContract() {
  if (!(await confirm("取消后会回退合同未送数量，确定继续？", "取消合同")))
    return;
  if (saving.value) return;
  saving.value = true;
  try {
    const r = await save(
      `contracts/${detail.value.id}/cancel`,
      { revision: detail.value.revision },
      "POST",
    );
    detail.value = r.item;
    ElMessage.success("合同已取消");
    await list.load();
  } catch (e) {
    notifyError(e);
  } finally {
    saving.value = false;
  }
}
async function exportFile(row) {
  if (exporting.value) return;
  exporting.value = row.id;
  try {
    await download(
      `contracts/${row.id}/export`,
      `购买合同-${row.contractNo}.xlsx`,
    );
  } catch (e) {
    notifyError(e);
  } finally {
    exporting.value = null;
  }
}
onMounted(async () => {
  try {
    categories.value = (await api("catalog-options")).items || [];
  } catch (e) {
    notifyError(e);
  }
});
</script>
<style scoped>
.contract-summary {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  padding: 20px 0;
  color: #475467;
}
.contract-summary p {
  width: 100%;
  white-space: pre-wrap;
  margin: 0;
}
.contract-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  margin-top: 16px;
  min-width: 0;
}
.contract-item header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.contract-item header div {
  min-width: 0;
}
.contract-item strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.contract-item small {
  display: block;
  overflow-wrap: anywhere;
  color: #667085;
  margin-top: 6px;
}
.size-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(135px, 1fr));
  gap: 12px;
  margin: 18px 0;
}
.size-grid label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.size-grid span {
  overflow-wrap: anywhere;
}
.size-grid .el-input-number {
  width: 100%;
}
.contract-images {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  margin-top: 16px;
}
.contract-images section {
  min-width: 0;
}
.contract-images h4 {
  font-size: 13px;
  color: #667085;
}
.contract-images .el-image {
  width: 100%;
  height: 200px;
}
.contract-summary strong {
  color: #1f2937;
}
</style>

<style scoped src="../components/mobile-goods/mobileGoods.css"></style>
<style scoped>
@media(max-width:767px){.mobile-contract-steps{display:flex;gap:7px;padding:6px;border:1px solid #e8eef7;border-radius:13px;background:#fff;margin-bottom:18px}.mobile-contract-steps>span{display:flex;flex:1;gap:5px;align-items:center;justify-content:center;min-width:0;padding:8px 3px;font-size:10px;white-space:nowrap;color:#98a6bb;border-radius:9px}.mobile-contract-steps b{display:grid;place-items:center;flex:0 0 17px;width:17px;height:17px;border-radius:6px;background:#f0f3f8;font-size:10px;font-weight:500}.mobile-contract-steps .active{background:#edf3ff;color:#2f69eb}.mobile-contract-steps .active b{background:#2f69eb;color:#fff}.mobile-contract-steps .done b{background:#eaf6f1;color:#258d6f}.contract-summary{padding:16px 0;gap:10px;font-size:12px}.contract-item{padding:15px;border-radius:15px;border-color:#e7edf6}.contract-item strong{white-space:normal;font-size:13px}.contract-item small{font-size:10px}.size-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}.size-grid label{font-size:11px;color:#8394ad}.contract-images{grid-template-columns:1fr;gap:14px}.contract-images .el-image{height:190px}.contract-images h4{font-size:12px}.contract-item .el-input-number{width:100%}}
</style>
