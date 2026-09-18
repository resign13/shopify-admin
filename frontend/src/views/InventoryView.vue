<template>
  <PageHeader
    title="库存管理"
    description="从合同未送、待入库到现货，清晰掌握每个尺码的到货进度。"
    eyebrow="INVENTORY / 商品与库存"
    ><template v-if="canEdit"
      ><ElButton :loading="exporting" @click="exportFile">导出库存</ElButton
      ><ElButton type="primary" :loading="importing" @click="input.click()"
        >导入库存</ElButton
      ><input
        ref="input"
        type="file"
        accept=".xlsx"
        hidden
        @change="previewFile" /></template
  ></PageHeader>
  <div
    class="metric-grid"
    :style="{ gridTemplateColumns: `repeat(${canEdit ? 5 : 3},minmax(0,1fr))` }"
  >
    <div class="metric">
      <span>颜色 SKU 数</span><strong>{{ list.total }}</strong>
    </div>
    <div class="metric">
      <span>当前库存合计</span><strong>{{ list.summary.stock || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>合同未送合计</span
      ><strong>{{ list.summary.contractPending || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>待入库合计</span
      ><strong>{{ list.summary.pendingInbound || 0 }}</strong>
    </div>
    <div class="metric">
      <span>零库存尺码数</span
      ><strong>{{ list.summary.zeroSizes || 0 }}</strong>
    </div>
  </div>
  <section class="panel">
    <form class="filters" @submit.prevent="apply">
      <ElInput
        v-model="filters.keyword"
        clearable
        placeholder="商品名、款式、SKU、颜色"
      /><ElSelect v-model="filters.category" clearable placeholder="全部分类"
        ><ElOption
          v-for="c in categories"
          :key="c.key"
          :value="c.key"
          :label="c.labels?.zh || c.key" /></ElSelect
      ><ElButton native-type="submit" type="primary">查询</ElButton
      ><ElButton @click="reset">重置</ElButton
      ><span class="small-note">汇总和导出覆盖全部筛选结果</span>
    </form>
    <DataTable
      ref="inventoryTable"
      expandable
      :expanded-keys="expandedKeys"
      @expand-change="(_, rows) => expandedKeys = rows.map(row => row.id)"
      storage-key="inventory-v2"
      :rows="list.rows"
      :columns="columns"
      :total="list.total"
      :page="list.query.page"
      :page-size="list.query.pageSize"
      :loading="list.loading"
      :error="list.error"
      @retry="list.load"
      @sort-change="list.sort"
      @page="list.query.page = $event"
      @page-size="list.query = { ...list.query, page: 1, pageSize: $event }"
      ><template #toolbar><ElButton :disabled="list.loading || !list.rows.length" @click="toggleAllSizes">{{ allSizesExpanded ? "一键收起" : "一键展开" }}</ElButton></template><template #name="{ row }"
        ><div class="product-cell">
          <ProductImage :src="row.image" :alt="productName(row)" />
          <div>
            <span class="product-name" :title="productName(row)">{{
              shortName(row)
            }}</span
            ><small class="sku" :title="row.sku">{{ row.sku }}</small
            ><small
              >{{ row.colorName }} · {{ row.categoryLabel }} ·
              <a href="#" @click.prevent="inventoryTable.toggleExpansion(row)"
                >{{ row.sizePrices.length }} 个尺码，查看明细</a
              ></small
            >
          </div>
        </div></template
      ><template #expanded="{ row }"
        ><div class="inventory-expanded">
          <div class="panel-title">
            <strong>真实尺码明细</strong
            ><span class="small-note">现货可销售；待入库包含在合同未送中</span>
          </div>
          <div class="stock-grid">
            <div
              v-for="size in row.sizePrices"
              :key="size.sizeCode"
              class="stock-cell"
            >
              <strong :title="'原始尺码：' + size.sizeCode">{{ inventorySizeLabel(size.sizeCode) }}</strong>
              <div class="stock-line">
                <span>现货</span
                ><b :class="{ negative: size.stock === 0 }">{{ size.stock }}</b>
              </div>
              <template v-if="canEdit"
                ><div class="stock-line">
                  <span>合同未送</span><b>{{ size.contractPending }}</b>
                </div>
                <div class="stock-line inbound">
                  <span>待入库</span><b>{{ size.pendingInbound }}</b>
                </div></template
              >
            </div>
          </div>
        </div></template
      ><template #pending="{ row }">{{
        total(row, "contractPending")
      }}</template
      ><template #inbound="{ row }"
        ><ElTag :type="total(row, 'pendingInbound') ? 'warning' : 'info'">{{
          total(row, "pendingInbound")
        }}</ElTag></template
      ><template #actions="{ row }"
        ><ElButton link type="primary" @click="edit(row)">登记数量</ElButton
        ><ElButton
          link
          type="primary"
          :disabled="!total(row, 'pendingInbound')"
          @click="prepareReceipt(row)"
          >一键入库</ElButton
        ></template
      ></DataTable
    >
  </section>
  <ElDrawer
    v-model="editing"
    title="登记库存与待入库"
    size="680px"
    :before-close="close"
    ><template v-if="product"
      ><h3>{{ productName(product) }}</h3>
      <p class="small-note">{{ product.sku }} · {{ product.colorName }}</p>
      <ElAlert
        title="待入库包含在合同未送中。登记不会增加现货；一键入库后才增加现货并减少合同未送。"
        type="info"
        :closable="false"
      /><ElTable :data="draft"
        ><ElTableColumn prop="sizeCode" :formatter="row => inventorySizeLabel(row.sizeCode)" label="真实尺码" /><ElTableColumn
          label="当前库存"
          min-width="155"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.stock"
              :min="0"
              :precision="0"
              controls-position="right"
            /><small style="display: block"
              >原值 {{ row.originalStock }} · 变化
              {{ delta(row.stock, row.originalStock) }}</small
            ></template
          ></ElTableColumn
        ><ElTableColumn label="合同未送" min-width="155"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.contractPending"
              :min="0"
              :precision="0"
              controls-position="right"
            /><small style="display: block"
              >原值 {{ row.originalPending }} · 变化
              {{ delta(row.contractPending, row.originalPending) }}</small
            ></template
          ></ElTableColumn
        ><ElTableColumn label="待入库" min-width="155"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.pendingInbound"
              :min="0"
              :precision="0"
              controls-position="right"
            /><small style="display: block"
              >原值 {{ row.originalInbound }} · 变化
              {{ delta(row.pendingInbound, row.originalInbound) }}</small
            ></template
          ></ElTableColumn
        ></ElTable
      ><ElAlert v-if="error" :title="error" type="error" :closable="false"
        ><ElButton v-if="conflict" text @click="readLatest"
          >读取最新数据（保留草稿）</ElButton
        ></ElAlert
      >
      <div v-if="latest" class="section-gap">
        <h3>线上最新数量</h3>
        <p v-for="s in latest.sizePrices" :key="s.sizeCode">
          {{ inventorySizeLabel(s.sizeCode) }}：库存 {{ s.stock }} / 合同未送
          {{ s.contractPending }} / 待入库 {{ s.pendingInbound }}
        </p>
        <ElButton @click="adoptLatest">使用最新数据重新编辑</ElButton>
      </div></template
    ><template #footer
      ><ElButton :disabled="saving" @click="close()">取消</ElButton
      ><ElButton
        type="primary"
        :disabled="!dirty"
        :loading="saving"
        @click="submit"
        >保存修改</ElButton
      ></template
    ></ElDrawer
  >
  <ElDrawer
    v-model="previewOpen"
    title="库存导入"
    size="860px"
    :close-on-click-modal="false"
    :before-close="closeImport"
    ><ElSteps
      :active="importResult ? 3 : preview ? 1 : 0"
      finish-status="success"
      simple
      ><ElStep title="上传文件" /><ElStep title="校验预览" /><ElStep
        title="确认更新" /><ElStep title="结果"
    /></ElSteps>
    <p class="small-note section-gap">
      {{ importFile?.name }} · 上传不会直接修改库存
    </p>
    <ElAlert
      v-if="importError"
      :title="importError"
      type="error"
      :closable="false"
    /><ElResult
      v-if="importResult"
      icon="success"
      title="库存导入完成"
      :sub-title="`实际更新 ${importResult.updatedProducts} 个商品、${importResult.updatedRows} 个尺码、${importResult.updatedFields} 个字段`"
    />
    <template v-else-if="preview"
      ><div class="batch-bar">
        商品 {{ preview.summary.productCount }} · 尺码行
        {{ preview.summary.rowCount }} · 待改行
        {{ preview.summary.changedRowCount }} · 错误 {{ preview.errors.length }}
      </div>
      <ElRadioGroup
        v-model="previewFilter"
        class="section-gap"
        @change="previewPage = 1"
        ><ElRadioButton value="all">全部</ElRadioButton
        ><ElRadioButton value="stock">库存变化</ElRadioButton
        ><ElRadioButton value="pending">合同未送变化</ElRadioButton
        ><ElRadioButton value="inbound">待入库变化</ElRadioButton
        ><ElRadioButton value="errors">错误</ElRadioButton></ElRadioGroup
      ><ElTable
        :data="previewRows.slice((previewPage - 1) * 25, previewPage * 25)"
        class="section-gap"
        ><ElTableColumn
          v-if="previewFilter === 'errors'"
          prop="row"
          label="行号"
          width="70"
        /><ElTableColumn
          v-if="previewFilter === 'errors'"
          prop="message"
          label="错误原因"
        /><template v-else
          ><ElTableColumn label="商品 / SKU" min-width="220"
            ><template #default="{ row }"
              >{{ row.title
              }}<small style="display: block">{{ row.sku }}</small></template
            ></ElTableColumn
          ><ElTableColumn
            prop="sizeCode" :formatter="row => inventorySizeLabel(row.sizeCode)"
            label="尺码"
            width="90"
          /><ElTableColumn label="库存"
            ><template #default="{ row }"
              ><span :class="{ positive: row.stockChanged }"
                >{{ row.originalStock }} → {{ row.stock }}</span
              ></template
            ></ElTableColumn
          ><ElTableColumn label="合同未送"
            ><template #default="{ row }"
              ><span :class="{ positive: row.contractPendingChanged }"
                >{{ row.originalContractPending }} →
                {{ row.contractPending }}</span
              ></template
            ></ElTableColumn
          ><ElTableColumn label="待入库"
            ><template #default="{ row }"
              ><span :class="{ positive: row.pendingInboundChanged }"
                >{{ row.originalPendingInbound ?? "保持" }} →
                {{ row.pendingInbound ?? "保持" }}</span
              ></template
            ></ElTableColumn
          ></template
        ></ElTable
      ><ElPagination
        v-model:current-page="previewPage"
        :page-size="25"
        :total="previewRows.length"
        layout="total,prev,pager,next"
        class="section-gap" /><ElAlert
        v-if="preview.errors.length"
        title="请修正全部错误后重新上传；本次不会写入任何库存。"
        type="error"
        :closable="false" /></template
    ><template #footer
      ><ElButton :disabled="importing" @click="closeImport()">{{
        importResult ? "完成" : "取消"
      }}</ElButton
      ><ElButton
        v-if="!importResult"
        type="primary"
        :loading="importing"
        :disabled="!preview || !!preview.errors.length"
        @click="confirmImport"
        >确认更新全部有效行</ElButton
      ></template
    ></ElDrawer
  >
  <ElDialog
    v-model="receiptOpen"
    title="确认一键入库"
    width="680px"
    :close-on-click-modal="false"
    :before-close="closeReceipt"
    ><template v-if="receipt"
      ><p>
        本次将为 <strong>{{ productName(receipt) }}</strong> 入库
        <strong>{{ total(receipt, "pendingInbound") }}</strong> 件。
      </p>
      <ElAlert
        title="现货增加、合同未送等量减少、待入库清零；各尺码整笔提交。"
        type="info"
        :closable="false" /><ElTable
        :data="receipt.sizePrices.filter((s) => s.pendingInbound > 0)"
        ><ElTableColumn prop="sizeCode" :formatter="row => inventorySizeLabel(row.sizeCode)" label="尺码" /><ElTableColumn
          prop="pendingInbound"
          label="本次入库"
          align="right"
        /><ElTableColumn label="现货"
          ><template #default="{ row }"
            >{{ row.stock }} → {{ row.stock + row.pendingInbound }}</template
          ></ElTableColumn
        ><ElTableColumn label="合同未送"
          ><template #default="{ row }"
            >{{ row.contractPending }} →
            {{ row.contractPending - row.pendingInbound }}</template
          ></ElTableColumn
        ></ElTable
      ><ElAlert
        v-if="receiptError"
        :title="receiptError"
        type="error"
        :closable="false" /></template
    ><template #footer
      ><ElButton :disabled="receiving" @click="receiptOpen = false"
        >取消</ElButton
      ><ElButton
        type="primary"
        :loading="receiving"
        :disabled="!receipt || !total(receipt, 'pendingInbound')"
        @click="receive"
        >确认入库</ElButton
      ></template
    ></ElDialog
  >
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { inventorySizeLabel } from "../utils/inventorySizes";
import { ElMessage } from "element-plus";
import { useAdminAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import ProductImage from "../components/ProductImage.vue";
import {
  api,
  save,
  useList,
  useDirty,
  download,
  notifyError,
  confirm,
  productName,
  shortName,
} from "../composables/workbench";
const auth = useAdminAuthStore(),
  canEdit = computed(() => auth.userRole !== "customer"),
  list = useList("inventory"),
  categories = ref([]),
  filters = reactive({
    keyword: list.query.keyword || "",
    category: list.query.category || "",
  });
const inventoryTable = ref();
const expandedKeys = ref([]);
const allSizesExpanded = computed(() => list.rows.length > 0 && list.rows.every(row => expandedKeys.value.includes(row.id)));
function toggleAllSizes() {
  expandedKeys.value = allSizesExpanded.value ? [] : list.rows.map(row => row.id);
}
watch(() => list.rows, () => { expandedKeys.value = []; });
const total = (row, field) =>
  row.sizePrices.reduce((sum, size) => sum + Number(size[field] || 0), 0);
const columns = computed(() => [
  { prop: "name", label: "商品 / 颜色 SKU", width: 300 },
  {
    prop: "stock",
    label: "现货库存",
    width: 100,
    numeric: true,
    sortable: true,
  },
  ...(canEdit.value
    ? [
        { prop: "pending", label: "合同未送", width: 100, numeric: true },
        { prop: "inbound", label: "待入库", width: 100, numeric: true },
        { prop: "actions", label: "操作", width: 160 },
      ]
    : []),
]);
const editing = ref(false),
  product = ref(),
  draft = ref([]),
  error = ref(""),
  saving = ref(false),
  latest = ref(),
  conflict = ref(false),
  input = ref(),
  exporting = ref(false);
const { dirty, markClean, canLeave } = useDirty(() => draft.value);
function delta(a, b) {
  const n = Number(a) - b;
  return n > 0 ? "+" + n : String(n);
}
function populate(item) {
  product.value = item;
  draft.value = item.sizePrices.map((s) => ({
    ...s,
    originalStock: s.stock,
    originalPending: s.contractPending,
    originalInbound: s.pendingInbound,
  }));
  markClean();
  error.value = "";
  conflict.value = false;
  latest.value = null;
}
async function edit(row) {
  try {
    populate((await api(`inventory/${row.id}`)).product);
    editing.value = true;
  } catch (e) {
    notifyError(e);
  }
}
async function close(done) {
  if (saving.value) return;
  if (await canLeave()) {
    markClean();
    editing.value = false;
    if (typeof done === "function") done();
  }
}
async function apply() {
  if (await canLeave()) list.apply(filters);
}
async function reset() {
  if (await canLeave()) {
    Object.assign(filters, { keyword: "", category: "" });
    list.apply(filters);
  }
}
async function submit() {
  if (saving.value) return;
  if (
    draft.value.some(
      (s) =>
        !Number.isInteger(s.stock) ||
        s.stock < 0 ||
        !Number.isInteger(s.contractPending) ||
        s.contractPending < 0 ||
        !Number.isInteger(s.pendingInbound) ||
        s.pendingInbound < 0 ||
        s.pendingInbound > s.contractPending,
    )
  ) {
    error.value = "数量必须为非负整数，待入库不能超过合同未送";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await save(`inventory/${product.value.id}`, {
      version: product.value.version,
      sizeStocks: Object.fromEntries(
        draft.value
          .filter((s) => s.stock !== s.originalStock)
          .map((s) => [s.sizeCode, s.stock]),
      ),
      contractPendingBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.contractPending !== s.originalPending)
          .map((s) => [s.sizeCode, s.contractPending]),
      ),
      pendingInboundBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.pendingInbound !== s.originalInbound)
          .map((s) => [s.sizeCode, s.pendingInbound]),
      ),
    });
    markClean();
    editing.value = false;
    ElMessage.success("库存已更新");
    list.load();
  } catch (e) {
    error.value = e.message;
    conflict.value = e.status === 409;
  } finally {
    saving.value = false;
  }
}
async function readLatest() {
  try {
    latest.value = (await api(`inventory/${product.value.id}`)).product;
  } catch (e) {
    notifyError(e);
  }
}
async function adoptLatest() {
  if (await confirm("放弃当前草稿，使用最新数量？")) populate(latest.value);
}
async function exportFile() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    await download(
      "inventory/export?" +
        new URLSearchParams({ ...list.query, view: "workbench" }),
      "当前库存.xlsx",
    );
  } catch (e) {
    notifyError(e);
  } finally {
    exporting.value = false;
  }
}
const previewOpen = ref(false),
  preview = ref(),
  importFile = ref(),
  importing = ref(false),
  importError = ref(""),
  importResult = ref(),
  previewFilter = ref("all"),
  previewPage = ref(1);
const previewRows = computed(() =>
  !preview.value
    ? []
    : previewFilter.value === "errors"
      ? preview.value.errors
      : preview.value.rows.filter(
          (r) =>
            previewFilter.value === "all" ||
            (previewFilter.value === "stock"
              ? r.stockChanged
              : previewFilter.value === "inbound"
                ? r.pendingInboundChanged
                : r.contractPendingChanged),
        ),
);
async function previewFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.error("文件不能超过 10 MB");
    return;
  }
  importFile.value = file;
  preview.value = null;
  importResult.value = null;
  importError.value = "";
  previewOpen.value = true;
  importing.value = true;
  previewFilter.value = "all";
  previewPage.value = 1;
  try {
    const body = new FormData();
    body.append("file", file);
    preview.value = await api("inventory/import/preview", {
      method: "POST",
      body,
    });
    if (preview.value.errors.length) previewFilter.value = "errors";
  } catch (e) {
    importError.value = e.message;
  } finally {
    importing.value = false;
  }
}
async function confirmImport() {
  if (
    importing.value ||
    !(await confirm(
      `将处理 ${preview.value.summary.rowCount} 个尺码行，只修改相对导出原值发生变化的字段。`,
      "确认导入",
    ))
  )
    return;
  importing.value = true;
  try {
    const body = new FormData();
    body.append("file", importFile.value);
    body.append("fileHash", preview.value.fileHash);
    importResult.value = await api("inventory/import/confirm", {
      method: "POST",
      body,
    });
    list.load();
  } catch (e) {
    importError.value = e.message;
  } finally {
    importing.value = false;
  }
}
function closeImport(done) {
  if (importing.value) return;
  previewOpen.value = false;
  if (typeof done === "function") done();
}
const receipt = ref(),
  receiptOpen = ref(false),
  receiving = ref(false),
  receiptError = ref(""),
  receiptRequest = ref("");
async function prepareReceipt(row) {
  try {
    receipt.value = (await api(`inventory/${row.id}`)).product;
    receiptRequest.value = crypto.randomUUID();
    receiptError.value = "";
    receiptOpen.value = true;
  } catch (e) {
    notifyError(e);
  }
}
function closeReceipt(done) {
  if (!receiving.value) done();
}
async function receive() {
  if (receiving.value) return;
  receiving.value = true;
  receiptError.value = "";
  try {
    const result = await save(
      `inventory/${receipt.value.id}/receive`,
      { version: receipt.value.version, requestId: receiptRequest.value },
      "POST",
    );
    receiptOpen.value = false;
    ElMessage.success(
      `入库完成：${result.receivedSizes} 个尺码，共 ${result.receivedUnits} 件`,
    );
    list.load();
  } catch (e) {
    receiptError.value = e.message;
  } finally {
    receiving.value = false;
  }
}
onMounted(async () => {
  try {
    categories.value = (await api("catalog-options")).items;
  } catch (e) {
    notifyError(e);
  }
});
</script>

<style scoped>
.inventory-expanded {
  padding: 18px 24px;
  background: #f8fafc;
}
.inventory-expanded .stock-grid {
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
}
.stock-cell {
  background: white;
  padding: 12px;
}
.stock-cell strong {
  font-size: 13px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}
.stock-line {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  margin-top: 8px;
}
.stock-line span {
  color: var(--muted);
}
.stock-line.inbound b {
  color: #b45309;
}
</style>
