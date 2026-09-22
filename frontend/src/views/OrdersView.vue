<template>
  <PageHeader
    title="订单管理"
    description="跟进订单状态、付款与物流，保持业务进度清晰可见。"
    eyebrow="ORDERS / 订单业务"
    ><ElButton v-if="canEditDetails" type="primary" @click="editOrder()"
      >＋ 新增订单</ElButton
    ><ElDropdown v-if="canExportOrders" @command="exportOrders"
      ><ElButton :loading="exporting">导出订单 ▾</ElButton
      ><template #dropdown
        ><ElDropdownMenu
          ><ElDropdownItem command="export"
            >{{
              selected.length
                ? "已选 " + selected.length + " 个订单"
                : "当前筛选全部订单"
            }}
            · 合并表格</ElDropdownItem
          ><ElDropdownItem command="export-by-sheet"
            >{{ selected.length ? "已选订单" : "当前筛选全部订单" }} · 分
            Sheet</ElDropdownItem
          ></ElDropdownMenu
        ></template
      ></ElDropdown
    ></PageHeader
  >
  <section class="panel">
    <ElTabs
      :model-value="list.query.status || 'all'"
      @update:model-value="changeStatus"
      ><ElTabPane label="全部" name="all" /><ElTabPane
        v-for="(label, status) in statusNames"
        :key="status"
        :name="status"
        :label="`${label} ${list.statusCounts[status] || 0}`"
    /></ElTabs>
    <form class="filters" @submit.prevent="apply">
      <ElInput
        v-model="filters.keyword"
        clearable
        placeholder="订单号、账号、公司、物流单号"
      /><ElDatePicker
        v-model="dates"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
      /><ElSelect v-model="filters.category" clearable placeholder="全部分类"
        ><ElOption
          v-for="c in categories"
          :key="c.key"
          :value="c.key"
          :label="c.labels?.zh || c.key" /></ElSelect
      ><ElButton native-type="submit" type="primary">查询</ElButton
      ><ElButton @click="reset">重置</ElButton
      ><ElTag
        v-if="list.query.country"
        closable
        @close="list.apply({ country: '' })"
        >{{ list.query.country }}</ElTag
      ><ElTag
        v-if="list.query.style"
        closable
        @close="list.apply({ style: '' })"
        >{{ list.query.style }}</ElTag
      >
    </form>
    <div v-if="selected.length" class="batch-bar">
      <strong>已选 {{ selected.length }} 个订单</strong
      ><ElButton text @click="clear">清空选择</ElButton
      ><ElButton
        v-if="auth.userRole === 'admin'"
        type="danger"
        plain
        :loading="deleting"
        @click="remove"
        >删除已选订单</ElButton
      >
    </div>
    <DataTable
      ref="table"
      :key="list.filterKey"
      storage-key="orders"
      :rows="list.rows"
      :columns="columns"
      :total="list.total"
      :page="list.query.page"
      :page-size="list.query.pageSize"
      :loading="list.loading"
      :error="list.error"
      selectable
      @retry="list.load"
      @selection-change="selected = $event"
      @sort-change="list.sort"
      @page="list.query.page = $event"
      @page-size="list.query = { ...list.query, page: 1, pageSize: $event }"
      ><template #orderNo="{ row }"
        ><ElButton link type="primary" @click="open(row.id)">{{
          row.orderNo
        }}</ElButton></template
      ><template #userName="{ row }"
        >{{ row.userName
        }}<small style="display: block">{{
          row.companyName || row.userEmail
        }}</small></template
      ><template #goodsAmount="{ row }">{{ money(row.goodsAmount) }}</template
      ><template #shippingFee="{ row }">{{ money(row.shippingFee) }}</template
      ><template #totalAmount="{ row }">{{ money(row.totalAmount) }}</template
      ><template #status="{ row }"
        ><ElTag
          :type="
            row.status === 'cancelled'
              ? 'info'
              : row.status === 'completed'
                ? 'success'
                : row.status === 'pending_payment'
                  ? 'warning'
                  : 'primary'
          "
          >{{ statusNames[row.status] }}</ElTag
        ></template
      ><template #createdAt="{ row }"
        ><small>{{ dateTime(row.createdAt) }}</small></template
      ><template #actions="{ row }"
        ><ElButton
          link
          type="primary"
          @click="
            detailId = row.id;
            detailOpen = true;
          "
          >订单详情</ElButton
        ></template
      ></DataTable
    >
  </section>
  <OrderDrawer v-model:open="detailOpen" :id="detailId" @saved="list.load" />
  <OrderEditor v-model:open="editorOpen" @saved="orderSaved" />
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useRoute } from "vue-router";
import { useAdminAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import OrderDrawer from "../components/OrderDrawer.vue";
import OrderEditor from "../components/OrderEditor.vue";
import {
  api,
  save,
  useList,
  download,
  notifyError,
  confirm,
  money,
  dateTime,
  statusNames,
} from "../composables/workbench";
const auth = useAdminAuthStore(),
  route = useRoute(),
  list = useList("orders"),
  selected = ref([]),
  table = ref(),
  categories = ref([]),
  detailOpen = ref(false),
  detailId = ref(),
  exporting = ref(false),
  deleting = ref(false);
const canEditDetails = computed(() =>
    ["admin", "sales"].includes(auth.userRole),
  ),
  // The route is already protected by the orders module permission. Reuse that
  // capability here so warehouse accounts with the module grant see exports.
  canExportOrders = computed(() => auth.can("orders")),
  editorOpen = ref(false);
function orderSaved(id) {
  list.load();
  if (id) {
    detailId.value = id;
    detailOpen.value = true;
  }
}
function editOrder() {
  editorOpen.value = true;
}
const filters = reactive({
    keyword: list.query.keyword || "",
    category: list.query.category || "",
  }),
  dates = ref(
    list.query.dateFrom ? [list.query.dateFrom, list.query.dateTo] : null,
  );
const columns = [
  { prop: "orderNo", label: "订单号", width: 165 },
  { prop: "userName", label: "业务员", width: 150 },
  { prop: "country", label: "国家", width: 90 },
  { prop: "itemCount", label: "件数", numeric: true, width: 60 },
  { prop: "goodsAmount", label: "商品金额", numeric: true, width: 100 },
  { prop: "shippingFee", label: "运费", numeric: true, width: 85 },
  {
    prop: "totalAmount",
    label: "应付总额",
    numeric: true,
    width: 105,
    sortable: true,
  },
  { prop: "status", label: "状态", width: 85 },
  { prop: "createdAt", label: "下单时间", width: 145, sortable: true },
  { prop: "actions", label: "操作", width: 85 },
];
watch(
  () => list.filterKey,
  () => {
    if (selected.value.length) ElMessage.info("筛选已改变，已清空选择");
    clear();
  },
);
function clear() {
  selected.value = [];
  table.value?.clearSelection();
}
function apply() {
  if (selected.value.length) ElMessage.info("筛选已改变，已清空选择");
  clear();
  list.apply({
    ...filters,
    dateFrom: dates.value?.[0] || "",
    dateTo: dates.value?.[1] || "",
  });
}
function reset() {
  Object.assign(filters, { keyword: "", category: "" });
  dates.value = null;
  list.query.country = "";
  list.query.style = "";
  apply();
}
function changeStatus(status) {
  clear();
  list.apply({ status });
}
function open(id) {
  detailId.value = id;
  detailOpen.value = true;
}
async function remove() {
  if (
    deleting.value ||
    !(await confirm(
      `将删除 ${selected.value.length} 个订单，现有删除规则会处理库存回补。确认继续？`,
      "删除订单",
    ))
  )
    return;
  deleting.value = true;
  try {
    await save(
      "orders",
      {
        orderIds: selected.value.map((o) => o.id),
        versions: Object.fromEntries(
          selected.value.map((o) => [o.id, o.version]),
        ),
      },
      "DELETE",
    );
    clear();
    list.load();
    ElMessage.success("订单已删除");
  } catch (e) {
    notifyError(e);
  } finally {
    deleting.value = false;
  }
}
async function exportOrders(type) {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const params = new URLSearchParams({
      ...list.query,
      view: "workbench",
      includeImages: "1",
      ...(selected.value.length
        ? { orderIds: selected.value.map((o) => o.id).join(",") }
        : {}),
    });
    await download(`orders/${type}?${params}`, `订单-${type}.xlsx`);
  } catch (e) {
    notifyError(e);
  } finally {
    exporting.value = false;
  }
}
onMounted(async () => {
  if (route.query.orderId) open(Number(route.query.orderId));
  try {
    categories.value = (await api("catalog-options")).items;
  } catch (e) {
    notifyError(e);
  }
});
</script>
