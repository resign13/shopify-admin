<template>
  <PageHeader
    title="库存管理"
    description="商品按分类顺序展示，采购入库与独立临时入库分开登记，清晰掌握尺码到货进度。"
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
    :style="{ gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))' }"
  >
    <div class="metric">
      <span>颜色 SKU 数</span><strong>{{ list.total }}</strong>
    </div>
    <div class="metric">
      <span>现货余额合计</span><strong>{{ list.summary.stock || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric"><span>可用现货</span><strong>{{ list.summary.availableStock || 0 }}</strong></div>
    <div v-if="canEdit" class="metric"><span>欠货件数 / 尺码数</span><strong class="negative">{{ list.summary.shortageUnits || 0 }} / {{ list.summary.shortageSizeCount || 0 }}</strong></div>
    <div v-if="canEdit" class="metric">
      <span>合同未送合计</span
      ><strong>{{ list.summary.contractPending || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>待验货合计</span
      ><strong>{{ list.summary.pendingInspection || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>待入库合计</span
      ><strong>{{ list.summary.pendingInbound || 0 }}</strong>
    </div>
    <div class="metric">
      <span>零库存尺码数</span
      ><strong>{{ list.summary.zeroSizes || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>临时待入库合计</span><strong>{{ list.summary.temporaryInbound || 0 }}</strong>
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
      ><ElSelect v-if="canEdit" v-model="filters.stock" clearable placeholder="全部库存"><ElOption label="欠货" value="backordered"/><ElOption label="有可用现货" value="available"/><ElOption label="无可用现货" value="empty"/></ElSelect><ElButton native-type="submit" type="primary">查询</ElButton
      ><ElButton @click="reset">重置</ElButton
      ><span class="small-note">汇总和导出覆盖全部筛选结果</span>
    </form>
    <DataTable
      ref="inventoryTable"
      expandable
      :expanded-keys="expandedKeys"
      @expand-change="(_, rows) => (expandedKeys = rows.map((row) => row.id))"
      storage-key="inventory-v2"
      :rows="orderedRows"
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
      ><template #toolbar
        ><span class="small-note">分类顺序优先，表头排序仅调整同类商品</span><ElButton
          :disabled="list.loading || !list.rows.length"
          @click="toggleAllSizes"
          >{{ allSizesExpanded ? "一键收起" : "一键展开" }}</ElButton
        ></template
      ><template #name="{ row }"
        ><div class="product-cell">
          <ProductImage :src="row.image" :alt="productName(row)" />
          <div>
            <span class="product-name" :title="productName(row)">{{
              shortName(row)
            }}</span
            ><small class="sku" :title="row.sku">{{ row.sku }}</small><ElTag v-if="canEdit && row.shortageUnits" type="danger">欠货 {{ row.shortageUnits }} 件 · {{ row.shortageSizeCount }} 个尺码</ElTag><ElTag v-if="canEdit && row.isActive === false" type="info">已下架</ElTag
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
            ><span class="small-note"
              >现货余额可为负数，表示欠货；到货后入库抵减欠货</span
            >
          </div>
          <div class="stock-grid">
            <div
              v-for="size in row.sizePrices"
              :key="size.sizeCode"
              class="stock-cell"
            >
              <strong :title="'原始尺码：' + size.sizeCode">{{
                inventorySizeLabel(size.sizeCode)
              }}</strong>
              <div class="stock-line">
                <span>现货</span
                ><b :class="{ negative: size.stock <= 0 }">{{ size.stock }}</b>
              </div>
              <template v-if="canEdit"
                ><div class="stock-line">
                  <span>合同未送</span><b>{{ size.contractPending }}</b>
                </div>
                <div class="stock-line inbound">
                  <span>待验货</span><b>{{ size.pendingInspection || 0 }}</b
                  ><span>待入库</span><b>{{ size.pendingInbound }}</b>
                </div><div class="stock-line temporary"><span>临时待入库</span><b>{{ size.temporaryInbound || 0 }}</b></div></template
              >
            </div>
          </div>
        </div></template
      ><template #pending="{ row }">{{
        total(row, "contractPending")
      }}</template
      ><template #inspection="{ row }">{{
        total(row, "pendingInspection")
      }}</template
      ><template #inbound="{ row }"
        ><ElTag :type="total(row, 'pendingInbound') ? 'warning' : 'info'">{{
          total(row, "pendingInbound")
        }}</ElTag></template
      ><template #temporary="{ row }"><ElTag :type="total(row, 'temporaryInbound') ? 'success' : 'info'">{{ total(row, 'temporaryInbound') }}</ElTag></template
      ><template #actions="{ row }"
        ><ElButton link type="primary" @click="edit(row)">登记数量</ElButton
        ><ElButton
          link
          type="primary"
          :disabled="!total(row, 'pendingInbound')"
          @click="prepareReceipt(row)"
          >一键入库</ElButton
        ><ElButton link type="success" :disabled="!total(row, 'temporaryInbound')" @click="prepareReceipt(row, 'temporary')">临时入库</ElButton
        ></template
      ></DataTable
    >
  </section>
  <ElDrawer
    v-model="editing"
    title="登记库存与到货进度"
    size="min(960px, 96vw)"
    :before-close="close"
    ><template v-if="product"
      ><h3>{{ productName(product) }}</h3>
      <p class="small-note">{{ product.sku }} · {{ product.colorName }}</p>
      <ElAlert
        title="增加待验货会等量减少合同未送；增加待入库会等量减少待验货。临时待入库独立登记，两种入库入口仅处理各自数量。"
        type="info"
        :closable="false"
      /><ElTable :data="draft"
        ><ElTableColumn
          prop="sizeCode"
          :formatter="(row) => inventorySizeLabel(row.sizeCode)"
          label="真实尺码"
          width="105"
        /><ElTableColumn label="现货余额" min-width="155"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.stock"
              :min="-2147483648"
              :max="2147483647"
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
        ><ElTableColumn label="待验货" min-width="155"
          ><template #default="{ row }">
            <ElInputNumber
              v-model="row.pendingInspection"
              :min="0"
              :precision="0"
              controls-position="right"
              @change="(value, old) => moveStage(row, 'inspection', value, old)"
            />
            <small style="display: block">原值 {{ row.originalInspection }} · 变化 {{delta(row.pendingInspection,row.originalInspection)}}</small>
          </template></ElTableColumn
        ><ElTableColumn label="待入库" min-width="155"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.pendingInbound"
              @change="(value, old) => moveStage(row, 'inbound', value, old)"
              :min="0"
              :precision="0"
              controls-position="right"
            /><small style="display: block"
              >原值 {{ row.originalInbound }} · 变化
              {{ delta(row.pendingInbound, row.originalInbound) }}</small
            ></template
          ></ElTableColumn
        ><ElTableColumn label="临时待入库" min-width="155"><template #default="{ row }">
            <ElInputNumber v-model="row.temporaryInbound" :min="0" :max="2147483647" :precision="0" :controls="false" :aria-label="`临时待入库 ${row.sizeCode}`" />
            <small style="display:block">原值 {{ row.originalTemporary }} · 变化 {{ delta(row.temporaryInbound, row.originalTemporary) }}</small>
          </template></ElTableColumn
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
          {{ s.contractPending }} / 待验货 {{ s.pendingInspection }} / 待入库
          {{ s.pendingInbound }}
          / 临时待入库 {{ s.temporaryInbound || 0 }}
        </p>
        <ElButton @click="adoptLatest">使用最新数据重新编辑</ElButton>
      </div>
      <section class="inventory-history">
        <div class="panel-title">
          <strong>登记操作记录</strong>
          <span class="small-note">每次成功保存记为一次操作 · 最新记录在前 · 每页 10 条</span>
        </div>
        <ElAlert v-if="operationHistory.error" :title="operationHistory.error" type="error" :closable="false">
          <ElButton link type="primary" @click="loadOperations">重新加载记录</ElButton>
        </ElAlert>
        <ElTable v-loading="operationHistory.loading" :data="operationHistory.items" row-key="id" empty-text="暂无登记操作记录">
          <ElTableColumn label="操作时间" width="165"><template #default="{ row }">{{ dateTime(row.occurredAt) }}</template></ElTableColumn>
          <ElTableColumn label="操作人" width="110"><template #default="{ row }">
            {{ row.actor.name || '未知操作人' }}<small class="history-role">{{ roleNames[row.actor.role] || row.actor.role }}</small>
          </template></ElTableColumn>
          <ElTableColumn label="登记数量 / 变化明细" min-width="400"><template #default="{ row }">
            <div v-for="change in row.changes" :key="change.sizeCode" class="history-size">
              <strong>{{ inventorySizeLabel(change.sizeCode) }}</strong>
              <span v-for="field in change.fields" :key="field.field" class="history-field">
                {{ inventoryFieldLabels[field.field] || field.field }} {{ field.before }} → {{ field.after }}
                <b :class="field.delta < 0 ? 'negative' : 'positive'">（{{ delta(field.after, field.before) }}）</b>
              </span>
            </div>
            <span v-if="!row.changes.length" class="small-note">本次保存数量未变化</span>
          </template></ElTableColumn>
        </ElTable>
        <ElPagination v-model:current-page="operationHistory.page" :page-size="10" :total="operationHistory.total" layout="total,prev,pager,next" class="section-gap" />
      </section></template
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
    size="min(1120px, 96vw)"
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
        ><ElRadioButton value="inspection">待验货变化</ElRadioButton
        ><ElRadioButton value="inbound">待入库变化</ElRadioButton
        ><ElRadioButton value="temporary">临时待入库变化</ElRadioButton
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
            prop="sizeCode"
            :formatter="(row) => inventorySizeLabel(row.sizeCode)"
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
          ><ElTableColumn label="待验货"
            ><template #default="{ row }"
              >{{ row.originalPendingInspection }} →
              {{ row.pendingInspection }}</template
            ></ElTableColumn
          ><ElTableColumn label="待入库"
            ><template #default="{ row }"
              ><span :class="{ positive: row.pendingInboundChanged }"
                >{{ row.originalPendingInbound ?? "保持" }} →
                {{ row.pendingInbound ?? "保持" }}</span
              ></template
            ></ElTableColumn
          ><ElTableColumn label="临时待入库"><template #default="{ row }"><span :class="{ positive: row.temporaryInboundChanged }">{{ row.originalTemporaryInbound ?? "保持" }} → {{ row.temporaryInbound ?? "保持" }}</span></template></ElTableColumn
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
    :title="receiptSource === 'temporary' ? '确认临时入库' : '确认一键入库'"
    width="680px"
    :close-on-click-modal="false"
    :before-close="closeReceipt"
    ><template v-if="receipt"
      ><p>
        本次将为 <strong>{{ productName(receipt) }}</strong> 入库
        <strong>{{ total(receipt, receiptField) }}</strong> 件，来源为<strong>{{ receiptSource === 'temporary' ? '独立临时待入库' : '采购待入库' }}</strong>。
      </p>
      <ElAlert
        :title="receiptSource === 'temporary' ? '现货增加、临时待入库清零；合同未送、待验货和采购待入库保持不变，各尺码整笔提交。' : '现货增加、采购待入库清零；合同未送、待验货和临时待入库保持不变，各尺码整笔提交。'"
        type="info"
        :closable="false" /><ElTable
        :data="receipt.sizePrices.filter((s) => s[receiptField] > 0)"
        ><ElTableColumn
          prop="sizeCode"
          :formatter="(row) => inventorySizeLabel(row.sizeCode)"
          label="尺码"
        /><ElTableColumn
          :prop="receiptField"
          label="本次入库"
          align="right"
        /><ElTableColumn label="现货"
          ><template #default="{ row }"
            >{{ row.stock }} → {{ row.stock + row[receiptField] }}</template
          ></ElTableColumn
        ><ElTableColumn label="合同未送"
          ><template #default="{ row }"
            >{{ row.contractPending }} → {{ row.contractPending }}</template
          ></ElTableColumn
        ></ElTable
      ><ElAlert
        v-if="receiptError"
        :title="receiptError"
        type="error"
        :closable="false" /><ElButton v-if="receiptConflict" link type="primary" @click="prepareReceipt(receipt, receiptSource)">读取最新数量并重新确认</ElButton></template
    ><template #footer
      ><ElButton :disabled="receiving" @click="receiptOpen = false"
        >取消</ElButton
      ><ElButton
        type="primary"
        :loading="receiving"
        :disabled="!receipt || !total(receipt, receiptField) || receiptConflict"
        @click="receive"
        >确认入库</ElButton
      ></template
    ></ElDialog
  >
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from "vue";
import { inventorySizeLabel } from "../utils/inventorySizes";
import { sortProductsByCategory } from "../utils/catalogOrder";
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
  dateTime,
  roleNames,
} from "../composables/workbench";
const auth = useAdminAuthStore(),
  canEdit = computed(() => auth.userRole !== "customer"),
  list = useList("inventory", { sort: "category" }),
  categories = ref([]),
  filters = reactive({
    keyword: list.query.keyword || "",
    category: list.query.category || "",
    stock: list.query.stock || "",
  });
const orderedRows = computed(() => sortProductsByCategory(list.rows || [], categories.value));
const inventoryTable = ref();
const expandedKeys = ref([]);
const allSizesExpanded = computed(
  () =>
    list.rows.length > 0 &&
    list.rows.every((row) => expandedKeys.value.includes(row.id)),
);
function toggleAllSizes() {
  expandedKeys.value = allSizesExpanded.value
    ? []
    : list.rows.map((row) => row.id);
}
watch(
  () => list.rows,
  () => {
    expandedKeys.value = [];
  },
);
const total = (row, field) =>
  row.sizePrices.reduce((sum, size) => sum + Number(size[field] || 0), 0);
const columns = computed(() => [
  { prop: "name", label: "商品 / 颜色 SKU", width: 300 },
  {
    prop: "stock",
    label: "现货余额",
    width: 100,
    numeric: true,
    sortable: true,
  },
  ...(canEdit.value
    ? [
        { prop: "availableStock", label: "可用现货", width: 100, numeric: true },
        { prop: "shortageUnits", label: "欠货件数", width: 100, numeric: true },
        { prop: "pending", label: "合同未送", width: 100, numeric: true },
        { prop: "inspection", label: "待验货", width: 100, numeric: true },
        { prop: "inbound", label: "待入库", width: 100, numeric: true },
        { prop: "temporary", label: "临时待入库", width: 110, numeric: true, defaultVisible: true },
        { prop: "actions", label: "操作", width: 250 },
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
const inventoryFieldLabels = { stock: '现货余额', contractPending: '合同未送', pendingInspection: '待验货', pendingInbound: '待入库', temporaryInbound: '临时待入库' };
const operationHistory = reactive({ items: [], total: 0, page: 1, loading: false, error: '' });
let operationController, operationSerial = 0;
async function loadOperations() {
  if (!editing.value || !product.value) return;
  operationController?.abort();
  operationController = new AbortController();
  const serial = ++operationSerial;
  operationHistory.loading = true;
  operationHistory.error = '';
  try {
    const result = await api(`inventory/${product.value.id}/operations?page=${operationHistory.page}&pageSize=10`, { signal: operationController.signal });
    if (serial === operationSerial) {
      operationHistory.items = result.items;
      operationHistory.total = result.total;
    }
  } catch (e) {
    if (serial === operationSerial && e.name !== 'AbortError') operationHistory.error = e.message;
  } finally {
    if (serial === operationSerial) operationHistory.loading = false;
  }
}
watch(() => [editing.value, product.value?.id, operationHistory.page], ([open]) => {
  if (open) loadOperations();
  else {
    operationController?.abort();
    operationSerial++;
    operationHistory.loading = false;
  }
});
onBeforeUnmount(() => operationController?.abort());
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
    originalInspection: s.pendingInspection || 0,
    temporaryInbound: s.temporaryInbound || 0,
    originalTemporary: s.temporaryInbound || 0,
  }));
  markClean();
  error.value = "";
  conflict.value = false;
  latest.value = null;
}
async function edit(row) {
  try {
    populate((await api(`inventory/${row.id}`)).product);
    Object.assign(operationHistory, { items: [], total: 0, page: 1, error: '' });
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
    Object.assign(filters, { keyword: "", category: "", stock: "" });
    list.apply(filters);
  }
}
function moveStage(row, stage, value, old) {
  if (!Number.isInteger(value) || !Number.isInteger(old)) return;
  const delta = value - old;
  const source =
    stage === "inspection" ? "contractPending" : "pendingInspection";
  if (row[source] - delta < 0) {
    row[stage === "inspection" ? "pendingInspection" : "pendingInbound"] = old;
    error.value = "本次转移超过上一阶段可用数量";
    return;
  }
  row[source] -= delta;
  error.value = "";
}
async function submit() {
  if (saving.value) return;
  if (
    draft.value.some(
      (s) =>
        !Number.isInteger(s.stock) ||
        s.stock < -2147483648 || s.stock > 2147483647 ||
        !Number.isInteger(s.contractPending) ||
        s.contractPending < 0 ||
        !Number.isInteger(s.pendingInbound) ||
        s.pendingInbound < 0 ||
        !Number.isInteger(s.pendingInspection) ||
        s.pendingInspection < 0 ||
        !Number.isInteger(s.temporaryInbound) || s.temporaryInbound < 0 || s.temporaryInbound > 2147483647,
    )
  ) {
    error.value = "现货须为范围内的整数，其他阶段须为非负整数，转移数量不能超过上一阶段";
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
      pendingInspectionBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.pendingInspection !== s.originalInspection)
          .map((s) => [s.sizeCode, s.pendingInspection]),
      ),
      pendingInboundBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.pendingInbound !== s.originalInbound)
          .map((s) => [s.sizeCode, s.pendingInbound]),
      ),
      temporaryInboundBySize: Object.fromEntries(draft.value.filter((s) => s.temporaryInbound !== s.originalTemporary).map((s) => [s.sizeCode, s.temporaryInbound])),
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
    loadOperations();
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
              : previewFilter.value === "temporary"
                ? r.temporaryInboundChanged
              : previewFilter.value === "inbound"
                ? r.pendingInboundChanged
                : previewFilter.value === "inspection"
                  ? r.pendingInspectionChanged
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
  receiptRequest = ref(""),
  receiptSource = ref('normal'),
  receiptConflict = ref(false);
const receiptField = computed(() => receiptSource.value === 'temporary' ? 'temporaryInbound' : 'pendingInbound');
async function prepareReceipt(row, source = 'normal') {
  try {
    receipt.value = (await api(`inventory/${row.id}`)).product;
    receiptSource.value = source;
    receiptConflict.value = false;
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
      `inventory/${receipt.value.id}/${receiptSource.value === 'temporary' ? 'temporary/' : ''}receive`,
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
    receiptConflict.value = e.status === 409;
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
.inventory-history {
  margin-top: 24px;
}
.history-role {
  display: block;
  color: var(--muted);
}
.history-size {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 4px 0;
}
.history-field {
  display: inline-block;
}
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
