<template>
  <section v-if="isPhone" class="mobile-audit" data-testid="mobile-audit">
    <header class="ma-heading"><div><h1>操作日志</h1><p>每一次变更，都有迹可循</p></div><MobileActionMenu label="更多"><ElButton @click="list.load">刷新记录</ElButton><ElButton @click="reset">重置筛选</ElButton></MobileActionMenu></header>
    <ResponsiveFilters class="ma-search" :active="list.query" :labels="{objectId:'对象',batchId:'同批次'}" @remove="removeInlineAuditFilter" @submit="applyMobileAudit">
      <ElInput v-model="filters.keyword" clearable placeholder="搜索操作人或对象 ID" @clear="applyMobileAudit"><template #prefix><ElIcon><Search /></ElIcon></template></ElInput>
      <ElSelect v-model="filters.module" clearable placeholder="全部模块" aria-label="日志模块"><ElOption v-for="(label,value) in modules" :key="value" :label="label" :value="value"/></ElSelect>
      <ElSelect v-model="filters.action" clearable placeholder="全部动作" aria-label="日志动作"><ElOption v-for="(label,value) in actions" :key="value" :label="label" :value="value"/></ElSelect>
      <ElDatePicker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期"/>
      <label class="mobile-filter-field"><span>每页记录</span><ElSelect :model-value="Number(list.query.pageSize)" aria-label="日志每页条数" @change="list.query={...list.query,page:1,pageSize:$event}"><ElOption v-for="n in [25,50,100]" :key="n" :label="n+' 条'" :value="n"/></ElSelect></label>
      <ElButton native-type="submit" type="primary" :loading="list.loading">查询</ElButton><ElButton @click="reset">重置</ElButton>
    </ResponsiveFilters>
    <div class="ma-section">最近活动 <small>· {{ list.total }} 条</small></div><ElAlert v-if="list.error" :title="list.error" type="error" :closable="false"><ElButton text @click="list.load">重试</ElButton></ElAlert>
    <div class="ma-timeline" v-loading="list.loading"><template v-for="(row,index) in list.rows" :key="row.id"><p v-if="index===0||mobileLogDay(row.occurredAt)!==mobileLogDay(list.rows[index-1].occurredAt)" class="ma-day">{{ mobileLogDay(row.occurredAt) }}</p><button class="ma-event" @click="show(row)"><span class="ma-line"/><span class="ma-event-icon" :class="row.module"><ElIcon><component :is="row.module==='orders'?Document:row.module==='inventory'?Box:row.module==='admin-users'?User:Clock"/></ElIcon></span><span class="ma-event-body"><span><strong>{{ actions[row.action]||row.action }}</strong><time>{{ mobileLogTime(row.occurredAt) }}</time></span><b>{{ row.objectId }}</b><small>{{ row.actor.name }} <i>·</i> {{ modules[row.module]||row.module }}</small></span><ElIcon class="ma-arrow"><ArrowRight /></ElIcon></button></template><ElEmpty v-if="!list.loading&&!list.rows.length" description="当前筛选暂无操作记录" :image-size="64"/></div>
    <ElPagination v-if="list.total" class="ma-pagination" :current-page="Number(list.query.page)" :page-size="Number(list.query.pageSize)" :total="list.total" :pager-count="5" layout="prev, pager, next" @current-change="list.query.page=$event"/>
  </section>
  <template v-else>
  <PageHeader
    title="操作日志"
    description="追溯后台关键操作，记录从新版上线起开始积累。"
    eyebrow="AUDIT / 账号与系统"
    ><ElButton @click="list.load">刷新</ElButton></PageHeader
  >
  <section class="panel">
    <ResponsiveFilters :active="list.query" @remove="removeMobileFilter"
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
    </ResponsiveFilters>
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
  </template>
  <ElDrawer v-model="open" title="变更详情" :size="isPhone ? '94%' : '760px'" :direction="isPhone?'btt':'rtl'"
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
      <div v-if="isPhone" class="mobile-audit-diffs"><article v-for="change in changes" :key="change.field"><h3>{{ change.field }}</h3><div><span>修改前</span><pre>{{ format(change.before) }}</pre></div><div><span>修改后</span><pre>{{ format(change.after) }}</pre></div></article><ElButton v-if="item.batchId" @click="list.apply({batchId:item.batchId});open=false">查看同批次</ElButton></div>
      <AdaptiveTable v-else :data="changes" class="section-gap"
        ><ElTableColumn prop="field" label="字段" width="160" /><ElTableColumn
          label="修改前"
          ><template #default="{ row }">
            <pre class="json-diff">{{ format(row.before) }}</pre>
          </template></ElTableColumn
        ><ElTableColumn label="修改后"
          ><template #default="{ row }">
            <pre class="json-diff">{{ format(row.after) }}</pre>
          </template></ElTableColumn
        ></AdaptiveTable
      >
      <p class="small-note section-gap">
        敏感凭据不记录；关联明细可通过“同批次”查看。
      </p></template
    ></ElDrawer
  >
</template>
<script setup>
import { useResponsive } from "../composables/responsive";
import MobileActionMenu from "../components/MobileActionMenu.vue";
import {Search,Document,Box,User,Clock,ArrowRight} from "@element-plus/icons-vue";
import ResponsiveFilters from "../components/ResponsiveFilters.vue";
import AdaptiveTable from "../components/AdaptiveTable";
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
const {isPhone}=useResponsive();
function applyMobileAudit(){list.apply({...filters,dateFrom:dates.value?.[0]||'',dateTo:dates.value?.[1]||''});}
function removeInlineAuditFilter(key){if(key==='dateFrom'||key==='dateTo'){if(dates.value?.[0]===list.query.dateFrom&&dates.value?.[1]===list.query.dateTo)dates.value=null;list.apply({dateFrom:'',dateTo:''});return;}if(key in filters&&String(filters[key]??'')===String(list.query[key]??''))filters[key]='';list.apply({[key]:''});}
function mobileLogDay(value){return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric'}).format(new Date(value));}
function mobileLogTime(value){return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));}
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
    presale: "预售管理",
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
  actions = { INSERT: "新增", UPDATE: "修改", DELETE: "删除", REORDER: "再来一单", DRAFT_SAVE: "保存草稿", DRAFT_DELETE: "删除草稿" };
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
function removeMobileFilter(key) {
  if (key === 'dateFrom' || key === 'dateTo') dates.value = null;
  else if (key in filters) filters[key] = '';
  list.apply({...filters,dateFrom:dates.value?.[0] || '',dateTo:dates.value?.[1] || '',[key]:''});
}
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

<style scoped>
@media(max-width:767px){.mobile-audit{color:#182b49}.ma-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:4px 0 22px}.ma-heading h1{font-size:25px;margin:0;letter-spacing:-.04em}.ma-heading p{font-size:11px;color:#8c9ab0;margin:7px 0 0}.ma-chips{display:flex;flex-wrap:wrap;gap:6px}.ma-chips :deep(.el-tag){font-size:10px;max-width:100%}.ma-section{font-size:12px;font-weight:600;margin:24px 0 15px}.ma-section small{color:#9fadc3;font-size:11px;font-weight:400}.ma-timeline{min-height:90px}.ma-day{font-size:11px;color:#a4b2c7;margin:0 0 18px}.ma-event{position:relative;display:flex;width:100%;gap:13px;align-items:flex-start;padding:0 0 25px;text-align:left;background:none;border:0;color:inherit;min-height:95px}.ma-line{position:absolute;left:17px;top:36px;bottom:0;width:1px;background:#e3eaf5}.ma-event:last-child .ma-line{display:none}.ma-event-icon{width:35px;height:35px;flex:0 0 35px;display:grid;place-items:center;border-radius:12px;background:#edf3ff;color:#819fcf;border:3px solid #f5f7fb;z-index:1}.ma-event-icon.inventory{background:#eaf6f2;color:#6aa793}.ma-event-icon.admin-users{background:#f1edfb;color:#9c85bd}.ma-event-body{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px;padding-top:3px}.ma-event-body>span{display:flex;justify-content:space-between;align-items:center;gap:12px}.ma-event-body strong{font-size:13px;font-weight:600;color:#3d577b}.ma-event-body time{font-size:10px;color:#a9b7cb;white-space:nowrap}.ma-event-body>b{font-size:11px;font-weight:450;color:#7a92b4;overflow-wrap:anywhere}.ma-event-body>small{font-size:11px;color:#a1b1c8}.ma-event-body i{font-style:normal;margin:0 5px}.ma-arrow{align-self:center;color:#bdcadc;font-size:12px;margin-top:-18px}.ma-pagination{justify-content:center;margin-top:18px;max-width:100%;overflow:auto}.mobile-audit-diffs{display:flex;flex-direction:column;gap:12px;margin-top:20px}.mobile-audit-diffs article{border:1px solid #e8edf7;background:#fff;border-radius:14px;padding:14px}.mobile-audit-diffs h3{font-size:13px;margin:0 0 14px;color:#5d7aa1;overflow-wrap:anywhere}.mobile-audit-diffs article>div{display:flex;flex-direction:column;gap:7px;margin-top:12px}.mobile-audit-diffs span{font-size:10px;color:#9eb0c9}.mobile-audit-diffs pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#6e88ab;background:#f5f8fd;border-radius:9px;padding:10px;margin:0;max-width:100%}}
</style>

<style scoped>
@media(max-width:767px){.ma-filter-drawer :deep(.el-date-editor--daterange){width:100%;min-width:0;max-width:100%;box-sizing:border-box}.ma-filter-drawer :deep(.el-select){width:100%}}
</style>
