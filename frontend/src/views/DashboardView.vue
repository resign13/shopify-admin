<template>
  <PageHeader
    title="经营工作台"
    description="从经营表现到日常业务，一站掌握全局。"
    eyebrow="OVERVIEW / 经营概览"
    ><span class="muted">更新于 {{ dateTime(data?.updatedAt) }}</span
    ><ElButton :loading="loading" @click="load">刷新数据</ElButton></PageHeader
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
        @change="preset = 'custom'"
      /><ElSelect v-model="country" clearable filterable placeholder="全部国家"
        ><ElOption
          v-for="item in data?.filters.countries"
          :key="item"
          :label="item"
          :value="item" /></ElSelect
      ><ElSelect v-model="style" clearable filterable placeholder="全部款式"
        ><ElOption
          v-for="item in data?.filters.styles"
          :key="item"
          :label="item"
          :value="item" /></ElSelect
      ><ElButton type="primary" @click="load">查询</ElButton>
    </div>
  </section>
  <ElAlert v-if="error" :title="error" type="error" :closable="false" />
  <ElSkeleton v-if="!data && loading" :rows="12" animated class="section-gap" />
  <template v-if="data">
    <div class="metric-grid">
      <article v-for="metric in metrics" :key="metric.key" class="metric">
        <span>{{ metric.label }}</span
        ><strong>{{
          metric.amount
            ? money(data.metrics[metric.key])
            : data.metrics[metric.key].toLocaleString()
        }}</strong
        ><small :class="change(metric.key) >= 0 ? 'positive' : 'negative'">{{
          data.previous[metric.key]
            ? `${change(metric.key) > 0 ? "+" : ""}${change(metric.key)}%`
            : "—"
        }}</small
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
                    dateFrom: dates?.[0],
                    dateTo: dates?.[1],
                    country,
                    style,
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
    <div class="dashboard-grid">
      <section class="panel">
        <div class="panel-title">
          <h2>商品表现 TOP 10</h2>
          <ElRadioGroup v-model="rankMetric"
            ><ElRadioButton value="units">件数</ElRadioButton
            ><ElRadioButton value="amount">金额</ElRadioButton></ElRadioGroup
          >
        </div>
        <ElEmpty
          v-if="!data.topProducts.length"
          description="此时间段暂无商品数据"
          :image-size="70"
        />
        <div
          v-for="(item, index) in ranked"
          :key="item.sku"
          class="ranking-row"
        >
          <span class="rank-number">{{
            String(index + 1).padStart(2, "0")
          }}</span>
          <div class="ranking-body">
            <div>
              <RouterLink
                class="rank-label"
                :title="item.name"
                :to="{ path: '/products', query: { keyword: item.sku } }"
                >{{ item.sku }} · {{ item.name }}</RouterLink
              ><strong>{{
                rankMetric === "amount"
                  ? money(item.amount)
                  : item.units + " 件"
              }}</strong>
            </div>
            <div class="rank-track">
              <span
                :style="{
                  width: `${(item[rankMetric] / Math.max(1, ...ranked.map((r) => r[rankMetric]))) * 100}%`,
                }"
              ></span>
            </div>
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-title">
          <h2>国家分布</h2>
          <small>订单数 / 商品金额</small>
        </div>
        <ElEmpty
          v-if="!data.countries.length"
          description="暂无国家数据"
          :image-size="70"
        />
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
      </section>
    </div>
    <section class="panel">
      <div class="panel-title">
        <h2>当前业务快照</h2>
        <ElTag type="info">当前全库 · 不受日期筛选影响</ElTag>
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
        <div>
          <span>合同未送</span
          ><strong>{{ data.snapshot.pending.toLocaleString() }}</strong>
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
  </template>
</template>
<script setup>
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import PageHeader from "../components/PageHeader.vue";
import { api, money, dateTime, statusNames } from "../composables/workbench";
const TrendChart = defineAsyncComponent(
  () => import("../components/TrendChart.vue"),
);
const route = useRoute(),
  router = useRouter(),
  data = ref(),
  loading = ref(false),
  error = ref(""),
  preset = ref("30"),
  dates = ref([]),
  country = ref(route.query.country || ""),
  style = ref(route.query.style || ""),
  trendMetric = ref("orders"),
  rankMetric = ref("units");
const metrics = [
  { key: "orders", label: "有效订单数" },
  { key: "amount", label: "商品订单金额", amount: true },
  { key: "units", label: "下单商品件数" },
  { key: "average", label: "平均每单商品金额", amount: true },
  { key: "customers", label: "下单客户数" },
];
const ranked = computed(() =>
  [
    ...((rankMetric.value === "amount"
      ? data.value?.topProductsByAmount
      : data.value?.topProducts) || []),
  ].sort((a, b) => b[rankMetric.value] - a[rankMetric.value]),
);
function setPreset(value) {
  if (value === "custom") return;
  const end = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  const start = new Date(end);
  start.setDate(start.getDate() - Number(value) + 1);
  const f = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  dates.value = [f(start), f(end)];
}
function change(key) {
  return Number(
    (
      ((data.value.metrics[key] - data.value.previous[key]) /
        data.value.previous[key]) *
      100
    ).toFixed(1),
  );
}
let seq = 0;
async function load() {
  const id = ++seq;
  loading.value = true;
  error.value = "";
  try {
    const query = {
      dateFrom: dates.value?.[0] || "",
      dateTo: dates.value?.[1] || "",
      country: country.value,
      style: style.value,
    };
    const result = await api(
      "dashboard?" + new URLSearchParams({ view: "workbench", ...query }),
    );
    if (id === seq) data.value = result;
    router.replace({ query });
  } catch (e) {
    if (id === seq) error.value = e.message;
  } finally {
    if (id === seq) loading.value = false;
  }
}
onMounted(() => {
  setPreset("30");
  if (route.query.dateFrom && route.query.dateTo) {
    dates.value = [route.query.dateFrom, route.query.dateTo];
    preset.value = "custom";
  }
  load();
});
</script>
