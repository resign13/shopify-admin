<template>
  <PageHeader
    title="经营工作台"
    description="从经营表现到日常业务，一站掌握全局。"
    eyebrow="OVERVIEW / 经营概览"
    ><span class="muted">更新于 {{ dateTime(data?.updatedAt) }}</span
    ><ElButton :loading="loading" @click="load(false, false)"
      >刷新数据</ElButton
    ></PageHeader
  >
  <section class="panel">
    <div class="filters" style="padding: 0; border: 0">
      <ElRadioGroup v-model="preset" @change="setPreset"
        ><ElRadioButton value="1">今天</ElRadioButton
        ><ElRadioButton value="7">近 7 天</ElRadioButton
        ><ElRadioButton value="30">近 30 天</ElRadioButton
        ><ElRadioButton value="custom">自定义</ElRadioButton></ElRadioGroup
      ><ElDatePicker
        v-model="dates"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        :clearable="false"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        @change="preset = 'custom'"
      /><ElSelect v-model="country" clearable filterable placeholder="全部国家"
        ><ElOption
          v-for="item in data?.filters.countries"
          :key="item"
          :label="item"
          :value="item" /></ElSelect
      ><ElSelect v-model="style" clearable filterable placeholder="全部款号"
        ><ElOption
          v-for="item in data?.filters.styles"
          :key="item"
          :label="item"
          :value="item" /></ElSelect
      ><ElButton type="primary" :loading="loading" @click="load(true)"
        >查询</ElButton
      >
    </div>
    <p class="small-note filter-scope">
      统计范围：{{ appliedRange }} · {{ appliedGlobal.country || "全部国家" }} ·
      {{ appliedGlobal.style || "全部款号"
      }}<span v-if="hasDraftGlobal">；筛选已更改，点击查询应用</span>
    </p>
  </section>
  <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon
    ><ElButton link type="primary" @click="load(false, false)"
      >重新加载</ElButton
    ></ElAlert
  >
  <ElSkeleton v-if="!data && loading" :rows="12" animated class="section-gap" />
  <div
    v-if="data"
    v-loading="loading"
    class="dashboard-content"
    :aria-busy="loading"
  >
    <div class="metric-grid">
      <article v-for="metric in metrics" :key="metric.key" class="metric">
        <span>{{ metric.label }}</span
        ><strong>{{
          metric.amount
            ? money(data.metrics[metric.key])
            : data.metrics[metric.key].toLocaleString()
        }}</strong
        ><small
          :class="
            change(metric.key) === null
              ? 'muted'
              : change(metric.key) >= 0
                ? 'positive'
                : 'negative'
          "
          >{{ changeText(metric.key) }}</small
        ><small class="muted"> 对比上一等长周期</small>
      </article>
    </div>
    <div class="dashboard-grid">
      <section class="panel">
        <div class="panel-title">
          <div>
            <h2>经营趋势</h2>
            <small>有效订单 · 按北京时间统计 · 不含运费</small>
          </div>
          <ElRadioGroup v-model="trendMetric"
            ><ElRadioButton value="orders">订单数</ElRadioButton
            ><ElRadioButton value="amount"
              >商品金额</ElRadioButton
            ></ElRadioGroup
          >
        </div>
        <TrendChart :points="data.trend" :metric="trendMetric" />
      </section>
      <section class="panel">
        <div class="panel-title">
          <h2>订单状态</h2>
          <small>当前筛选</small>
        </div>
        <div
          v-for="(label, status) in statusNames"
          :key="status"
          class="ranking-row"
        >
          <span class="rank-number"
            ><span
              class="status-dot"
              style="display: block; background: #93b4f8"
            ></span
          ></span>
          <div class="ranking-body">
            <div>
              <RouterLink
                :to="{
                  path: '/orders',
                  query: {
                    status,
                    ...appliedGlobal,
                  },
                }"
                >{{ label }}</RouterLink
              ><strong>{{ data.statusCounts[status] || 0 }}</strong>
            </div>
            <div class="rank-track">
              <span
                :style="{
                  width: `${
                    ((data.statusCounts[status] || 0) /
                      Math.max(
                        1,
                        Object.values(data.statusCounts).reduce(
                          (a, b) => a + b,
                          0,
                        ),
                      )) *
                    100
                  }%`,
                }"
              ></span>
            </div>
          </div>
        </div>
        <p class="small-note">点击状态查看订单明细</p>
      </section>
    </div>
    <section class="panel style-performance-panel">
      <div class="panel-title style-performance-title">
        <div>
          <h2>款号商品表现</h2>
          <small>按款号汇总颜色 SKU，展开查看每个真实尺码的销量与库存。</small>
        </div>
        <div class="inline-actions">
          <ElRadioGroup
            v-model="velocityWindow"
            size="small"
            @change="loadStylePerformance(true)"
          >
            <ElRadioButton value="7">近 7 天周转</ElRadioButton>
            <ElRadioButton value="30">近 30 天周转</ElRadioButton>
          </ElRadioGroup>
          <ElButton
            size="small"
            :loading="stylePerformanceLoading"
            @click="loadStylePerformance(false)"
            >刷新</ElButton
          >
        </div>
      </div>
      <div class="style-performance-filters">
        <ElInput
          v-model="styleKeyword"
          clearable
          placeholder="搜索款号、颜色 SKU 或商品名称"
          @keyup.enter="loadStylePerformance(true)"
          @clear="loadStylePerformance(true)"
        />
        <ElSelect
          v-model="styleCategory"
          clearable
          placeholder="全部分类"
          @change="loadStylePerformance(true)"
        >
          <ElOption
            v-for="item in data.filters.categories || []"
            :key="item.key"
            :label="item.label"
            :value="item.key"
          />
        </ElSelect>
        <ElSelect
          v-model="styleRisk"
          clearable
          placeholder="全部库存状态"
          @change="loadStylePerformance(true)"
        >
          <ElOption label="欠货" value="backordered" /><ElOption label="无库存" value="out_of_stock" />
          <ElOption label="周转期无销量" value="no_sales" />
          <ElOption label="预计 7 天内售罄" value="critical" />
          <ElOption label="预计 7–30 天售罄" value="warning" />
          <ElOption label="库存健康" value="healthy" />
        </ElSelect>
        <ElSelect
          v-model="styleSort"
          placeholder="排序方式"
          @change="loadStylePerformance(true)"
        >
          <ElOption label="销量" value="units" />
          <ElOption label="金额" value="amount" />
          <ElOption label="现货余额" value="stock" />
          <ElOption label="预计可售天数" value="estimatedDays" />
          <ElOption label="最近销售时间" value="lastSoldAt" />
        </ElSelect>
        <ElSelect
          v-model="styleDirection"
          class="sort-direction"
          aria-label="排序方向"
          @change="loadStylePerformance(true)"
        >
          <ElOption label="从高到低" value="desc" />
          <ElOption label="从低到高" value="asc" />
        </ElSelect>
        <ElButton
          type="primary"
          :loading="stylePerformanceLoading"
          @click="loadStylePerformance(true)"
          >查询</ElButton
        >
        <ElButton @click="resetStyleFilters">重置</ElButton>
      </div>
      <p class="small-note calculation-note">
        销量与金额按上方日期、国家和款号筛选，排除已取消订单，金额不含运费。现货及各库存阶段为当前数量。预计可售天数
        = 当前现货 ÷ 截至 {{ appliedGlobal.dateTo }} 的近
        {{ velocityWindow }} 天日均销量（{{
          appliedGlobal.country || "全部国家"
        }}）；无销量时不估算。
      </p>
      <ElAlert
        v-if="stylePerformanceError"
        :title="stylePerformanceError"
        type="error"
        :closable="false"
        show-icon
        ><ElButton link type="primary" @click="loadStylePerformance(false)"
          >重试款号数据</ElButton
        ></ElAlert
      >
      <div
        v-loading="stylePerformanceLoading"
        :aria-busy="stylePerformanceLoading"
      >
        <template v-if="stylePerformance.items">
          <div class="style-summary-grid">
            <div>
              <span>款号</span
              ><strong>{{
                number(stylePerformance.summary?.styleCount)
              }}</strong>
            </div>
            <div>
              <span>筛选销量</span
              ><strong>{{ number(stylePerformance.summary?.units) }} 件</strong>
            </div>
            <div>
              <span>商品金额</span
              ><strong>{{
                money(stylePerformance.summary?.amount || 0)
              }}</strong>
            </div>
            <div>
              <span>当前库存</span
              ><strong>{{ number(stylePerformance.summary?.stock) }}</strong>
            </div>
            <div><span>可用现货</span><strong>{{ number(stylePerformance.summary?.availableStock) }}</strong></div>
            <div><span>欠货件数 / 尺码数</span><strong>{{ number(stylePerformance.summary?.shortageUnits) }} / {{ number(stylePerformance.summary?.shortageSizeCount) }}</strong></div>
            <div>
              <span>合同未送</span
              ><strong>{{
                number(stylePerformance.summary?.contractPending)
              }}</strong>
            </div>
            <div>
              <span>待验货</span
              ><strong>{{
                number(stylePerformance.summary?.pendingInspection)
              }}</strong>
            </div>
            <div>
              <span>待入库</span
              ><strong>{{
                number(stylePerformance.summary?.pendingInbound)
              }}</strong>
            </div>
          </div>
          <ElEmpty
            v-if="!stylePerformance.items.length"
            description="当前筛选暂无款号数据，可调整条件或重置筛选"
            :image-size="70"
          />
          <ElTable
            v-else
            :data="stylePerformance.items"
            row-key="styleCode"
            size="small"
            class="style-performance-table"
          >
            <ElTableColumn label="款号 / 商品" min-width="180" fixed="left">
              <template #default="{ row }"
                ><button
                  class="style-link"
                  :title="row.styleCode"
                  @click="openStyle(row)"
                >
                  {{ row.styleCode }}</button
                ><small class="style-name">{{
                  row.name || "未命名商品"
                }}</small></template
              >
            </ElTableColumn>
            <ElTableColumn label="销量" prop="units" width="86" align="right" />
            <ElTableColumn label="金额" width="110" align="right"
              ><template #default="{ row }">{{
                money(row.amount)
              }}</template></ElTableColumn
            >
            <ElTableColumn
              label="颜色 SKU"
              prop="colorSkuCount"
              width="88"
              align="right"
            />
            <ElTableColumn
              label="现货余额"
              prop="stock"
              width="92"
              align="right"
            />
            <ElTableColumn label="日均销量" width="92" align="right"
              ><template #default="{ row }">{{
                row.averageDailyUnits || 0
              }}</template></ElTableColumn
            >
            <ElTableColumn label="预计可售" width="105" align="right"
              ><template #default="{ row }">{{
                daysText(row)
              }}</template></ElTableColumn
            >
            <ElTableColumn label="状态" width="132"
              ><template #default="{ row }"
                ><ElTag :type="riskType(row.risk)" size="small">{{
                  riskName(row.risk)
                }}</ElTag></template
              ></ElTableColumn
            >
            <ElTableColumn label="最近销售时间" width="170"
              ><template #default="{ row }">{{
                dateTime(row.lastSoldAt)
              }}</template></ElTableColumn
            >
            <ElTableColumn label="操作" width="90" fixed="right"
              ><template #default="{ row }"
                ><ElButton
                  link
                  type="primary"
                  size="small"
                  @click="openStyle(row)"
                  >查看明细</ElButton
                ></template
              ></ElTableColumn
            >
          </ElTable>
          <div
            class="table-footer style-performance-footer"
            v-if="stylePerformance.total"
          >
            <span
              >显示第
              {{
                (stylePerformance.page - 1) * stylePerformance.pageSize + 1
              }}–{{
                Math.min(
                  stylePerformance.page * stylePerformance.pageSize,
                  stylePerformance.total,
                )
              }}
              条，共 {{ stylePerformance.total }} 个款号</span
            >
            <ElPagination
              :current-page="stylePage"
              :page-size="stylePageSize"
              layout="sizes, prev, pager, next"
              :pager-count="5"
              :page-sizes="[10, 25, 50]"
              :total="stylePerformance.total"
              size="small"
              @current-change="changeStylePage"
              @size-change="changeStylePageSize"
            />
          </div>
        </template>
        <ElSkeleton v-else-if="stylePerformanceLoading" :rows="5" animated />
      </div>
      <ElDrawer
        v-model="styleDrawerVisible"
        :title="`款号 ${selectedStyle?.styleCode || ''} 明细`"
        size="min(1120px, 96vw)"
      >
        <ElSkeleton v-if="styleDetailLoading" :rows="8" animated />
        <ElAlert
          v-else-if="styleDetailError"
          :title="styleDetailError"
          type="error"
          :closable="false"
          show-icon
          ><ElButton link type="primary" @click="openStyle(selectedStyle)"
            >重新加载明细</ElButton
          ></ElAlert
        >
        <template v-else-if="styleDetail">
          <p class="small-note calculation-note">
            销售统计：{{ styleDetail.salesWindow.dateFrom }} 至
            {{ styleDetail.salesWindow.dateTo }} ·
            {{ appliedStyleQuery.country || "全部国家" }}。周转窗口：{{
              styleDetail.velocityWindow.dateFrom
            }}
            至 {{ styleDetail.velocityWindow.dateTo }}。点击行首箭头展开尺码。
          </p>
          <div class="style-detail-summary">
            <div>
              <span>颜色 SKU</span
              ><strong>{{ styleDetail.items.length }}</strong>
            </div>
            <div v-for="item in inventoryMetrics" :key="item.key">
              <span>{{ item.label }}</span
              ><strong>{{
                number(
                  styleDetail.items.reduce(
                    (sum, row) => sum + row[item.key],
                    0,
                  ),
                )
              }}</strong>
            </div>
          </div>
          <ElTable
            :data="styleDetail.items"
            row-key="productId"
            size="small"
            class="style-detail-table"
          >
            <ElTableColumn type="expand"
              ><template #default="{ row }"
                ><div class="size-detail">
                  <h3>
                    {{ row.colorName || row.productCode || row.sku }} · 尺码明细
                  </h3>
                  <ElTable
                    :data="row.sizes"
                    size="small"
                    row-key="sizeCode"
                    empty-text="此颜色 SKU 暂无尺码数据"
                    ><ElTableColumn
                      prop="sizeCode"
                      label="尺码"
                      min-width="95"
                    /><ElTableColumn
                      prop="units"
                      label="销量"
                      width="70"
                      align="right"
                    /><ElTableColumn label="金额" width="105" align="right"
                      ><template #default="{ row: size }">{{
                        money(size.amount)
                      }}</template></ElTableColumn
                    ><ElTableColumn
                      v-for="item in inventoryMetrics"
                      :key="item.key"
                      :prop="item.key"
                      :label="item.label"
                      width="86"
                      align="right"
                    /><ElTableColumn
                      prop="averageDailyUnits"
                      label="日均销量"
                      width="92"
                      align="right"
                    /><ElTableColumn label="预计可售" width="105" align="right"
                      ><template #default="{ row: size }">{{
                        daysText(size)
                      }}</template></ElTableColumn
                    ><ElTableColumn label="状态" width="130"
                      ><template #default="{ row: size }"
                        ><ElTag :type="riskType(size.risk)" size="small">{{
                          riskName(size.risk)
                        }}</ElTag></template
                      ></ElTableColumn
                    ></ElTable
                  >
                </div></template
              ></ElTableColumn
            >
            <ElTableColumn label="颜色 SKU" min-width="145"
              ><template #default="{ row }"
                ><span class="sku">{{ row.productCode || row.sku }}</span
                ><small class="style-name">{{
                  row.colorName || "未填写色号"
                }}</small></template
              ></ElTableColumn
            >
            <ElTableColumn label="销量" prop="units" width="80" align="right" />
            <ElTableColumn label="金额" width="105" align="right"
              ><template #default="{ row }">{{
                money(row.amount)
              }}</template></ElTableColumn
            >
            <ElTableColumn
              v-for="item in inventoryMetrics"
              :key="item.key"
              :label="item.label"
              :prop="item.key"
              width="86"
              align="right"
            />
            <ElTableColumn label="预计可售" width="95" align="right"
              ><template #default="{ row }">{{
                daysText(row)
              }}</template></ElTableColumn
            >
            <ElTableColumn label="状态" width="130"
              ><template #default="{ row }"
                ><ElTag :type="riskType(row.risk)" size="small">{{
                  riskName(row.risk)
                }}</ElTag></template
              ></ElTableColumn
            >
          </ElTable>
          <div class="inline-actions style-detail-links">
            <RouterLink
              :to="{
                path: '/products',
                query: { keyword: styleDetail.styleCode },
              }"
              ><ElButton size="small">查看商品</ElButton></RouterLink
            ><RouterLink
              :to="{
                path: '/inventory',
                query: { keyword: styleDetail.styleCode },
              }"
              ><ElButton size="small">查看库存</ElButton></RouterLink
            >
          </div>
        </template>
      </ElDrawer>
    </section>
    <section class="panel country-panel">
      <div class="panel-title">
        <h2>国家分布</h2>
        <small>订单数 / 商品金额</small>
      </div>
      <ElEmpty
        v-if="!data.countries.length"
        description="暂无国家数据"
        :image-size="70"
      />
      <div class="country-grid">
        <div
          v-for="item in data.countries"
          :key="item.country"
          class="ranking-row"
        >
          <div class="ranking-body">
            <div>
              <span>{{ item.country }}</span
              ><strong>{{ item.orders }} 单</strong>
            </div>
            <small>{{ money(item.amount) }}</small>
          </div>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-title">
        <h2>当前业务快照</h2>
        <ElTag type="info">当前全库 · 不受上方筛选影响</ElTag>
      </div>
      <div class="snapshot-grid">
        <div>
          <span>待付款订单</span
          ><strong>{{ data.snapshot.statuses.pending_payment || 0 }}</strong>
        </div>
        <div>
          <span>待发货订单</span
          ><strong>{{ data.snapshot.statuses.paid || 0 }}</strong>
        </div>
        <div>
          <span>当前库存</span
          ><strong>{{ data.snapshot.stock.toLocaleString() }}</strong>
        </div>
        <div><span>可用现货</span><strong>{{ number(data.snapshot.availableStock) }}</strong></div>
        <div><span>欠货件数 / 尺码数</span><strong>{{ number(data.snapshot.shortageUnits) }} / {{ number(data.snapshot.shortageSizeCount) }}</strong></div>
        <div>
          <span>合同未送</span
          ><strong>{{ data.snapshot.pending.toLocaleString() }}</strong>
        </div>
        <div>
          <span>待验货</span
          ><strong>{{
            (data.snapshot.inspection || 0).toLocaleString()
          }}</strong>
        </div>
        <div>
          <span>待入库</span
          ><strong>{{ (data.snapshot.inbound || 0).toLocaleString() }}</strong>
        </div>
        <div>
          <span>零库存尺码</span><strong>{{ data.snapshot.empty }}</strong>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-title">
        <h2>最近订单</h2>
        <RouterLink class="small-note" to="/orders">查看全部订单 →</RouterLink>
      </div>
      <ElTable :data="data.recentOrders"
        ><ElTableColumn label="订单号"
          ><template #default="{ row }"
            ><RouterLink
              :to="{ path: '/orders', query: { orderId: row.id } }"
              style="color: var(--accent)"
              >{{ row.orderNo }}</RouterLink
            ></template
          ></ElTableColumn
        ><ElTableColumn prop="userName" label="客户" /><ElTableColumn
          prop="country"
          label="国家"
        /><ElTableColumn label="商品金额" align="right"
          ><template #default="{ row }">{{
            money(row.goodsAmount)
          }}</template></ElTableColumn
        ><ElTableColumn label="状态"
          ><template #default="{ row }"
            ><ElTag type="info">{{ statusNames[row.status] }}</ElTag></template
          ></ElTableColumn
        ><ElTableColumn label="下单时间"
          ><template #default="{ row }">{{
            dateTime(row.createdAt)
          }}</template></ElTableColumn
        ></ElTable
      >
    </section>
  </div>
</template>
<script setup>
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import PageHeader from "../components/PageHeader.vue";
import { api, money, dateTime, statusNames } from "../composables/workbench";
const TrendChart = defineAsyncComponent(
  () => import("../components/TrendChart.vue"),
);
const route = useRoute(),
  router = useRouter();
const data = ref(),
  loading = ref(false),
  error = ref("");
const preset = ref("30"),
  dates = ref([]),
  country = ref(""),
  style = ref("");
const appliedGlobal = ref({}),
  appliedPreset = ref("30"),
  trendMetric = ref("orders");
const stylePerformance = ref({ items: null, summary: {} });
const stylePerformanceLoading = ref(false),
  stylePerformanceError = ref("");
const styleKeyword = ref(""),
  styleCategory = ref(""),
  styleRisk = ref("");
const styleSort = ref("units"),
  styleDirection = ref("desc"),
  velocityWindow = ref("7");
const stylePage = ref(1),
  stylePageSize = ref(10),
  requestedStyleQuery = ref(null),
  appliedStyleQuery = ref({});
const styleDrawerVisible = ref(false),
  styleDetailLoading = ref(false);
const styleDetail = ref(null),
  styleDetailError = ref(""),
  selectedStyle = ref(null);
const metrics = [
  { key: "orders", label: "有效订单数" },
  { key: "amount", label: "商品订单金额", amount: true },
  { key: "units", label: "下单商品件数" },
  { key: "average", label: "平均每单商品金额", amount: true },
  { key: "customers", label: "下单客户数" },
];
const inventoryMetrics = [
  { key: "stock", label: "现货余额" },
  { key: "availableStock", label: "可用现货" },
  { key: "shortageUnits", label: "欠货件数" },
  { key: "contractPending", label: "合同未送" },
  { key: "pendingInspection", label: "待验货" },
  { key: "pendingInbound", label: "待入库" },
];
const appliedRange = computed(
  () =>
    `${appliedGlobal.value.dateFrom || "—"} 至 ${appliedGlobal.value.dateTo || "—"}`,
);
const hasDraftGlobal = computed(
  () => queryKey(globalQuery()) !== queryKey(appliedGlobal.value),
);
function number(value) {
  return Number(value || 0).toLocaleString();
}
function riskName(value) {
  return (
    {
      backordered: "欠货",
      out_of_stock: "无库存",
      no_sales: "周转期无销量",
      critical: "7 天内售罄",
      warning: "7–30 天售罄",
      healthy: "库存健康",
    }[value] || "待观察"
  );
}
function riskType(value) {
  return (
    {
      backordered: "danger",
      out_of_stock: "danger",
      no_sales: "info",
      critical: "danger",
      warning: "warning",
      healthy: "success",
    }[value] || "info"
  );
}
function daysText(item) {
  if (Number(item?.shortageUnits || 0) > 0) return "欠货待补";
  if (!item || Number(item.availableStock ?? item.stock ?? 0) <= 0) return "无库存";
  if (!Number(item.velocityUnits || 0) || item.estimatedDays == null)
    return "暂无销量";
  return `${Number(item.estimatedDays).toFixed(1)} 天`;
}
function presetDates(value) {
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const end = new Date(`${today}T00:00:00Z`),
    start = new Date(end);
  start.setUTCDate(start.getUTCDate() - Number(value) + 1);
  return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)];
}
function setPreset(value) {
  if (value === "custom") return;
  dates.value = presetDates(value);
  load(true);
}
function change(key) {
  const previous = Number(data.value?.previous[key] || 0);
  return previous
    ? Number(
        (((data.value.metrics[key] - previous) / previous) * 100).toFixed(1),
      )
    : null;
}
function changeText(key) {
  const value = change(key);
  return value == null
    ? "上期为 0，暂无可比值"
    : `${value > 0 ? "+" : ""}${value}%`;
}
function globalQuery() {
  return {
    dateFrom: dates.value?.[0] || "",
    dateTo: dates.value?.[1] || "",
    country: country.value,
    style: style.value,
  };
}
function queryKey(query) {
  return JSON.stringify(
    Object.entries(query)
      .filter(([, value]) => value != null && value !== "")
      .sort(([a], [b]) => a.localeCompare(b)),
  );
}
const scalar = (value) => (typeof value === "string" ? value : "");
function readRoute() {
  const q = route.query;
  requestedStyleQuery.value = null;
  country.value = scalar(q.country);
  style.value = scalar(q.style);
  dates.value =
    q.dateFrom && q.dateTo
      ? [scalar(q.dateFrom), scalar(q.dateTo)]
      : presetDates("30");
  preset.value =
    ["1", "7", "30"].includes(q.datePreset) &&
    queryKey(dates.value) === queryKey(presetDates(q.datePreset))
      ? q.datePreset
      : q.dateFrom
        ? "custom"
        : "30";
  styleKeyword.value = scalar(q.styleKeyword);
  styleCategory.value = scalar(q.styleCategory);
  styleRisk.value = [
    "backordered",
    "out_of_stock",
    "no_sales",
    "critical",
    "warning",
    "healthy",
  ].includes(q.styleRisk)
    ? q.styleRisk
    : "";
  styleSort.value = [
    "units",
    "amount",
    "stock",
    "estimatedDays",
    "lastSoldAt",
  ].includes(q.styleSort)
    ? q.styleSort
    : "units";
  styleDirection.value = q.styleDirection === "asc" ? "asc" : "desc";
  velocityWindow.value = q.velocityWindow === "30" ? "30" : "7";
  stylePage.value =
    Number.isInteger(Number(q.stylePage)) && Number(q.stylePage) > 0
      ? Number(q.stylePage)
      : 1;
  stylePageSize.value = [10, 25, 50].includes(Number(q.stylePageSize))
    ? Number(q.stylePageSize)
    : 10;
  appliedGlobal.value = globalQuery();
}
let syncedRouteKey = "",
  seq = 0,
  styleSeq = 0,
  detailSeq = 0;
let overviewController, styleController, detailController;
function syncRoute(query) {
  const next = {
    ...appliedGlobal.value,
    datePreset: appliedPreset.value,
    styleKeyword: query.keyword,
    styleCategory: query.category,
    styleRisk: query.risk,
    styleSort: query.sort,
    styleDirection: query.direction,
    velocityWindow: query.velocityWindow,
    stylePage: String(stylePage.value),
    stylePageSize: String(stylePageSize.value),
  };
  Object.keys(next).forEach((key) => {
    if (next[key] === "" || next[key] == null) delete next[key];
  });
  syncedRouteKey = queryKey(next);
  if (queryKey(route.query) !== syncedRouteKey) router.replace({ query: next });
}
async function loadStylePerformance(resetPage = false, applyDraft = resetPage) {
  if (resetPage) stylePage.value = 1;
  styleDrawerVisible.value = false;
  styleController?.abort();
  const controller = (styleController = new AbortController()),
    id = ++styleSeq;
  const filters =
    applyDraft || !requestedStyleQuery.value
      ? {
          keyword: styleKeyword.value.trim(),
          category: styleCategory.value,
          risk: styleRisk.value,
          sort: styleSort.value,
          direction: styleDirection.value,
          velocityWindow: velocityWindow.value,
        }
      : requestedStyleQuery.value;
  const query = {
    ...filters,
    ...appliedGlobal.value,
    page: String(stylePage.value),
    pageSize: String(stylePageSize.value),
  };
  requestedStyleQuery.value = query;
  syncRoute(query);
  stylePerformanceLoading.value = true;
  stylePerformanceError.value = "";
  try {
    const result = await api(
      "dashboard?" +
        new URLSearchParams({ view: "style-performance", ...query }),
      { signal: controller.signal },
    );
    if (id !== styleSeq) return;
    stylePerformance.value = result;
    stylePage.value = result.page;
    appliedStyleQuery.value = query;
    syncRoute(query);
  } catch (e) {
    if (id === styleSeq && e.name !== "AbortError") {
      stylePerformanceError.value = e.message;
      stylePerformance.value = { items: null, summary: {} };
    }
  } finally {
    if (id === styleSeq) stylePerformanceLoading.value = false;
  }
}
function changeStylePage(page) {
  if (page === stylePage.value) return;
  stylePage.value = page;
  loadStylePerformance(false);
}
function changeStylePageSize(size) {
  stylePageSize.value = size;
  loadStylePerformance(true);
}
function resetStyleFilters() {
  styleKeyword.value = styleCategory.value = styleRisk.value = "";
  styleSort.value = "units";
  styleDirection.value = "desc";
  velocityWindow.value = "7";
  loadStylePerformance(true);
}
async function openStyle(row) {
  if (!row) return;
  detailController?.abort();
  const controller = (detailController = new AbortController()),
    id = ++detailSeq;
  selectedStyle.value = row;
  styleDrawerVisible.value = true;
  styleDetailLoading.value = true;
  styleDetailError.value = "";
  styleDetail.value = null;
  try {
    const result = await api(
      "dashboard?" +
        new URLSearchParams({
          ...appliedStyleQuery.value,
          view: "style-detail",
          styleCode: row.styleCode,
        }),
      { signal: controller.signal },
    );
    if (id === detailSeq) styleDetail.value = result;
  } catch (e) {
    if (id === detailSeq && e.name !== "AbortError")
      styleDetailError.value = e.message;
  } finally {
    if (id === detailSeq) styleDetailLoading.value = false;
  }
}
async function load(resetPage = false, applyDraft = true) {
  overviewController?.abort();
  const controller = (overviewController = new AbortController()),
    id = ++seq;
  const query = applyDraft ? globalQuery() : { ...appliedGlobal.value };
  resetPage ||=
    queryKey(query) !== queryKey(appliedGlobal.value) &&
    !!appliedGlobal.value.dateFrom;
  appliedGlobal.value = query;
  if (applyDraft) appliedPreset.value = preset.value;
  loading.value = true;
  error.value = "";
  const overview = (async () => {
    try {
      const result = await api(
        "dashboard?" + new URLSearchParams({ view: "workbench", ...query }),
        { signal: controller.signal },
      );
      if (id === seq) data.value = result;
    } catch (e) {
      if (id === seq && e.name !== "AbortError") {
        error.value = e.message;
        data.value = null;
      }
    }
  })();
  await Promise.all([overview, loadStylePerformance(resetPage, applyDraft)]);
  if (id === seq) loading.value = false;
}
watch(styleDrawerVisible, (visible) => {
  if (!visible) {
    ++detailSeq;
    detailController?.abort();
  }
});
watch(
  () => route.query,
  (query) => {
    if (route.path !== "/dashboard") return;
    if (queryKey(query) === syncedRouteKey) return;
    readRoute();
    load(false);
  },
);
onMounted(() => {
  readRoute();
  load(false);
});
onBeforeUnmount(() => {
  ++seq;
  ++styleSeq;
  ++detailSeq;
  overviewController?.abort();
  styleController?.abort();
  detailController?.abort();
});
</script>

<style scoped>
.style-performance-panel {
  margin-bottom: 16px;
}
.style-performance-title {
  align-items: flex-start;
}
.style-performance-title small,
.style-name {
  display: block;
  color: var(--muted);
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.style-performance-title small {
  white-space: normal;
}
.filter-scope {
  margin: 12px 0 0;
  line-height: 1.6;
}
.filter-scope span {
  color: var(--accent);
}
.calculation-note {
  margin: 12px 0;
  line-height: 1.8;
}
.style-performance-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.style-performance-filters .el-input {
  width: 270px;
}
.style-performance-filters .el-select {
  width: 150px;
}
.style-performance-filters .sort-direction {
  width: 115px;
}
.style-summary-grid,
.style-detail-summary {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
  padding: 14px 0;
}
.style-detail-summary {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}
.style-summary-grid > div,
.style-detail-summary > div {
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 6px;
  min-width: 0;
}
.style-summary-grid span,
.style-detail-summary span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}
.style-summary-grid strong,
.style-detail-summary strong {
  display: block;
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
}
.style-performance-table :deep(.cell),
.style-detail-table :deep(.cell) {
  min-width: 0;
}
.style-link {
  display: block;
  max-width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.style-performance-footer {
  flex-wrap: wrap;
  gap: 10px;
}
.style-detail-links {
  margin-top: 18px;
}
.size-detail {
  padding: 12px 18px;
  background: #f8fafc;
}
.size-detail h3 {
  margin: 0 0 12px;
  font-size: 13px;
}
.country-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0 28px;
}
.country-grid .ranking-row {
  margin: 8px 0;
}
.snapshot-grid {
  grid-template-columns: repeat(7, minmax(0, 1fr));
}
.snapshot-grid > div {
  padding: 12px 8px;
}
@media (max-width: 1023px) {
  .style-performance-title {
    flex-direction: column;
  }
  .style-summary-grid,
  .style-detail-summary,
  .snapshot-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 639px) {
  .style-performance-filters .el-input,
  .style-performance-filters .el-select {
    width: 100%;
  }
  .style-summary-grid,
  .style-detail-summary,
  .snapshot-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .style-performance-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
