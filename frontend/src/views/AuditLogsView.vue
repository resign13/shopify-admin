<template>
  <PageHeader
    title="操作日志"
    description="追溯后台关键操作，记录从新版上线起开始积累。"
    eyebrow="AUDIT / 账号与系统"
    ><ElButton @click="list.load">刷新</ElButton></PageHeader
  >
  <section class="panel">
    <form
      class="filters"
      @submit.prevent="
        list.apply({
          ...filters,
          dateFrom: dates?.[0] || '',
          dateTo: dates?.[1] || '',
        })
      "
    >
      <ElInput
        v-model="filters.keyword"
        clearable
        placeholder="操作人或对象 ID"
      /><ElSelect v-model="filters.module" clearable placeholder="全部模块"
        ><ElOption
          v-for="(label, value) in modules"
          :key="value"
          :value="value"
          :label="label" /></ElSelect
      ><ElSelect v-model="filters.action" clearable placeholder="全部动作"
        ><ElOption
          v-for="(label, value) in actions"
          :key="value"
          :value="value"
          :label="label" /></ElSelect
      ><ElDatePicker
        v-model="dates"
        type="daterange"
        value-format="YYYY-MM-DD"
      /><ElButton type="primary" native-type="submit">查询</ElButton
      ><ElButton @click="reset">重置</ElButton
      ><ElTag
        v-if="list.query.objectId"
        closable
        @close="list.apply({ objectId: '' })"
        >对象 {{ list.query.objectId }}</ElTag
      >
    </form>
    <DataTable
      storage-key="audit"
      :rows="list.rows"
      :columns="columns"
      :total="list.total"
      :page="list.query.page"
      :page-size="list.query.pageSize"
      :loading="list.loading"
      :error="list.error"
      @retry="list.load"
      @page="list.query.page = $event"
      @page-size="list.query = { ...list.query, page: 1, pageSize: $event }"
      ><template #occurredAt="{ row }">{{ dateTime(row.occurredAt) }}</template
      ><template #actor="{ row }"
        >{{ row.actor.name
        }}<small style="display: block">{{
          roleNames[row.actor.role]
        }}</small></template
      ><template #module="{ row }">{{
        modules[row.module] || row.module
      }}</template
      ><template #action="{ row }"
        ><ElTag
          :type="
            row.action === 'DELETE'
              ? 'danger'
              : row.action === 'INSERT'
                ? 'success'
                : 'primary'
          "
          >{{ actions[row.action] }}</ElTag
        ></template
      ><template #batchId="{ row }"
        ><span :title="row.batchId" class="sku">{{
          row.batchId.slice(0, 8)
        }}</span
        ><ElButton link @click="list.apply({ batchId: row.batchId })"
          >同批次</ElButton
        ></template
      ><template #details="{ row }"
        ><ElButton link type="primary" @click="show(row)"
          >查看差异</ElButton
        ></template
      ></DataTable
    >
  </section>
  <ElDrawer v-model="open" title="变更详情" size="760px"
    ><template v-if="item"
      ><div class="detail-grid">
        <div>
          <span>操作人</span>{{ item.actor.name }} ·
          {{ roleNames[item.actor.role] }}
        </div>
        <div><span>操作时间</span>{{ dateTime(item.occurredAt) }}</div>
        <div>
          <span>模块 / 对象</span>{{ modules[item.module] }} /
          {{ item.objectId }}
        </div>
        <div><span>数据记录</span>{{ item.entityTable }}</div>
      </div>
      <ElTable :data="changes" class="section-gap"
        ><ElTableColumn prop="field" label="字段" width="160" /><ElTableColumn
          label="修改前"
          ><template #default="{ row }">
            <pre class="json-diff">{{ format(row.before) }}</pre>
          </template></ElTableColumn
        ><ElTableColumn label="修改后"
          ><template #default="{ row }">
            <pre class="json-diff">{{ format(row.after) }}</pre>
          </template></ElTableColumn
        ></ElTable
      >
      <p class="small-note section-gap">
        敏感凭据不记录；关联明细可通过“同批次”查看。
      </p></template
    ></ElDrawer
  >
</template>
<script setup>
import { computed, reactive, ref } from "vue";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import {
  api,
  useList,
  notifyError,
  dateTime,
  roleNames,
} from "../composables/workbench";
const list = useList("audit-logs"),
  filters = reactive({
    keyword: list.query.keyword || "",
    module: list.query.module || "",
    action: list.query.action || "",
  }),
  dates = ref(
    list.query.dateFrom ? [list.query.dateFrom, list.query.dateTo] : null,
  ),
  open = ref(false),
  item = ref();
const modules = {
    products: "商品",
    inventory: "库存",
    orders: "订单",
    contracts: "采购合同",
    "home-config": "首页与活动",
    categories: "分类",
    "admin-users": "后台账号",
    "store-users": "商城账号",
    banners: "海报",
  },
  actions = { INSERT: "新增", UPDATE: "修改", DELETE: "删除" };
const columns = [
  { prop: "occurredAt", label: "时间", width: 170 },
  { prop: "actor", label: "操作人", width: 120 },
  { prop: "module", label: "模块", width: 100 },
  { prop: "action", label: "动作", width: 70 },
  { prop: "objectId", label: "对象 ID", width: 80 },
  { prop: "batchId", label: "操作批次", width: 150 },
  { prop: "details", label: "详情", width: 90 },
];
const changes = computed(() =>
  !item.value
    ? []
    : [
        ...new Set([
          ...Object.keys(item.value.before || {}),
          ...Object.keys(item.value.after || {}),
        ]),
      ]
        .filter(
          (k) =>
            JSON.stringify(item.value.before?.[k]) !==
            JSON.stringify(item.value.after?.[k]),
        )
        .map((field) => ({
          field,
          before: item.value.before?.[field],
          after: item.value.after?.[field],
        })),
);
const format = (value) =>
  value === undefined
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value, null, 2)
      : String(value);
function reset() {
  Object.assign(filters, { keyword: "", module: "", action: "" });
  dates.value = null;
  list.apply({
    ...filters,
    objectId: "",
    batchId: "",
    dateFrom: "",
    dateTo: "",
  });
}
async function show(row) {
  try {
    item.value = (await api(`audit-logs/${row.id}`)).item;
    open.value = true;
  } catch (e) {
    notifyError(e);
  }
}
</script>
