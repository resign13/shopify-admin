<template>
  <PageHeader
    title="商品管理"
    description="统一维护商品资料、颜色 SKU 与展示信息。"
    eyebrow="CATALOG / 商品与库存"
    ><ElButton type="primary" @click="router.push('/products/new')"
      >＋ 新建商品</ElButton
    ></PageHeader
  >
  <section class="panel">
    <form class="filters" @submit.prevent="apply">
      <ElInput
        v-model="filters.keyword"
        clearable
        placeholder="搜索标题、款式、SKU 或颜色"
      /><ElSelect v-model="filters.category" clearable placeholder="全部分类"
        ><ElOption
          v-for="c in categories"
          :key="c.key"
          :value="c.key"
          :label="c.labels?.zh || c.key" /></ElSelect
      ><ElSelect v-model="filters.stock" clearable placeholder="库存状态"
        ><ElOption value="available" label="有库存" /><ElOption
          value="empty"
          label="无库存" /></ElSelect
      ><ElSelect v-model="filters.featured" clearable placeholder="首页推荐"
        ><ElOption value="true" label="已推荐" /><ElOption
          value="false"
          label="未推荐" /></ElSelect
      ><ElButton native-type="submit" type="primary">查询</ElButton
      ><ElButton @click="reset">重置</ElButton>
    </form>
    <div v-if="selected.length" class="batch-bar">
      <strong>已选 {{ selected.length }} 个商品</strong
      ><ElButton @click="batchOpen = true">批量调整分类 / 推荐</ElButton
      ><ElButton text @click="clearSelection">清空选择</ElButton>
    </div>
    <DataTable
      ref="table"
      :key="list.filterKey"
      storage-key="products"
      :rows="list.rows"
      :columns="columns"
      :total="list.total"
      :page="list.query.page"
      :page-size="list.query.pageSize"
      :loading="list.loading"
      :error="list.error"
      selectable
      @retry="list.load"
      @sort-change="list.sort"
      @page="list.query.page = $event"
      @page-size="list.query = { ...list.query, page: 1, pageSize: $event }"
      @selection-change="selected = $event"
    >
      <template #name="{ row }"
        ><div class="product-cell">
          <ProductImage :src="row.image" :alt="productName(row)" />
          <div>
            <a
              href="#"
              class="product-name"
              :title="productName(row)"
              @click.prevent="preview(row)"
              >{{ shortName(row) }}</a
            ><small
              >{{ row.colorName || "未设置颜色" }} ·
              {{ row.colorGroup || "—" }}</small
            >
          </div>
        </div></template
      >
      <template #sku="{ row }"
        ><span class="sku" :title="row.sku">{{ row.sku }}</span
        ><ElButton text size="small" @click="copy(row.sku)"
          >复制</ElButton
        ></template
      >
      <template #price="{ row }">{{ priceRange(row) }}</template
      ><template #featured="{ row }"
        ><ElTag :type="row.featured ? 'primary' : 'info'">{{
          row.featured ? "已推荐" : "未推荐"
        }}</ElTag></template
      ><template #updatedAt="{ row }"
        ><small>{{ dateTime(row.updatedAt) }}</small></template
      >
      <template #actions="{ row }"
        ><ElButton
          link
          type="primary"
          @click="router.push(`/products/${row.id}/edit`)"
          >编辑</ElButton
        ><ElDropdown
          @command="
            (command) => (command === 'preview' ? preview(row) : remove(row))
          "
          ><ElButton link>更多</ElButton
          ><template #dropdown
            ><ElDropdownMenu
              ><ElDropdownItem command="preview">查看资料</ElDropdownItem
              ><ElDropdownItem command="delete" divided
                >删除商品</ElDropdownItem
              ></ElDropdownMenu
            ></template
          ></ElDropdown
        ></template
      ></DataTable
    >
  </section>
  <ElDrawer v-model="previewOpen" title="商品资料" size="580px"
    ><template v-if="item"
      ><h2>{{ productName(item) }}</h2>
      <p class="muted">{{ item.sku }} · {{ item.colorName }}</p>
      <div class="image-grid">
        <ElImage
          v-for="(url, i) in item.gallery"
          :key="url"
          :src="imageUrl(url, 320)"
          :preview-src-list="item.gallery"
          :initial-index="i"
          style="width: 100px; height: 130px"
          fit="contain"
        />
      </div>
      <ElDescriptions :column="2" border class="section-gap"
        ><ElDescriptionsItem label="分类">{{
          item.categoryLabel
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="当前库存">{{
          item.stock
        }}</ElDescriptionsItem></ElDescriptions
      ><ElTable :data="item.sizePrices" class="section-gap"
        ><ElTableColumn prop="sizeCode" label="真实尺码" /><ElTableColumn
          label="价格"
          align="right"
          ><template #default="{ row }">{{
            money(row.price)
          }}</template></ElTableColumn
        ><ElTableColumn
          prop="stock"
          label="库存"
          align="right" /></ElTable></template
  ></ElDrawer>
  <ElDialog
    v-model="batchOpen"
    title="批量调整商品"
    width="480px"
    :close-on-click-modal="false"
    ><p>
      将修改明确选中的 {{ selected.length }} 个商品，未设置的字段保持不变。
    </p>
    <ElForm label-position="top"
      ><ElFormItem label="调整分类"
        ><ElSelect
          v-model="batch.categoryKey"
          clearable
          placeholder="保持原分类"
          ><ElOption
            v-for="c in categories"
            :key="c.key"
            :value="c.key"
            :label="c.labels?.zh || c.key" /></ElSelect></ElFormItem
      ><ElFormItem label="首页推荐"
        ><ElSelect v-model="batch.featured"
          ><ElOption value="keep" label="保持原值" /><ElOption
            value="true"
            label="设置推荐" /><ElOption
            value="false"
            label="取消推荐" /></ElSelect></ElFormItem></ElForm
    ><template #footer
      ><ElButton @click="batchOpen = false">取消</ElButton
      ><ElButton type="primary" :loading="saving" @click="applyBatch"
        >确认修改 {{ selected.length }} 项</ElButton
      ></template
    ></ElDialog
  >
</template>
<script setup>
import { onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import ProductImage from "../components/ProductImage.vue";
import { imageUrl } from "../utils/imageUrl";
import {
  api,
  save,
  useList,
  confirm,
  notifyError,
  money,
  productName,
  shortName,
  copy,
  dateTime,
} from "../composables/workbench";
const router = useRouter(),
  list = useList("products"),
  categories = ref([]),
  selected = ref([]),
  table = ref(),
  previewOpen = ref(false),
  item = ref(),
  batchOpen = ref(false),
  saving = ref(false),
  batch = reactive({ categoryKey: "", featured: "keep" });
const filters = reactive({
  keyword: list.query.keyword || "",
  category: list.query.category || "",
  stock: list.query.stock || "",
  featured: list.query.featured || "",
});
const columns = [
  { prop: "name", label: "商品信息", width: 260 },
  { prop: "sku", label: "颜色 SKU", width: 135, sortable: true },
  { prop: "categoryLabel", label: "分类", width: 90 },
  { prop: "price", label: "价格", numeric: true, sortable: true, width: 115 },
  { prop: "stock", label: "库存", numeric: true, sortable: true, width: 80 },
  { prop: "featured", label: "推荐", width: 80 },
  { prop: "updatedAt", label: "更新时间", width: 140, sortable: true },
  { prop: "actions", label: "操作", width: 100 },
];
watch(
  () => list.filterKey,
  () => {
    if (selected.value.length) ElMessage.info("筛选已改变，已清空选择");
    clearSelection();
  },
);
function clearSelection() {
  selected.value = [];
  table.value?.clearSelection();
}
function apply() {
  if (selected.value.length) ElMessage.info("筛选已改变，已清空选择");
  clearSelection();
  list.apply(filters);
}
function reset() {
  Object.assign(filters, {
    keyword: "",
    category: "",
    stock: "",
    featured: "",
  });
  apply();
}
function priceRange(row) {
  const values = (row.sizePrices || []).map((s) => Number(s.price));
  if (!values.length) return money(row.price);
  const a = Math.min(...values),
    b = Math.max(...values);
  return a === b ? money(a) : `${money(a)}–${money(b)}`;
}
async function preview(row) {
  try {
    item.value = (await api(`products/${row.id}`)).product;
    previewOpen.value = true;
  } catch (e) {
    notifyError(e);
  }
}
async function remove(row) {
  if (
    !(await confirm(
      `删除“${productName(row)}”？此操作会影响商品展示。`,
      "删除商品",
    ))
  )
    return;
  try {
    await save(`products/${row.id}`, { version: row.version }, "DELETE");
    ElMessage.success("商品已删除");
    clearSelection();
    list.load();
  } catch (e) {
    notifyError(e);
  }
}
async function applyBatch() {
  if (saving.value) return;
  if (!batch.categoryKey && batch.featured === "keep") {
    ElMessage.info("请选择要修改的字段");
    return;
  }
  saving.value = true;
  try {
    await save(
      "products/batch",
      {
        ids: selected.value.map((p) => p.id),
        versions: Object.fromEntries(
          selected.value.map((p) => [p.id, p.version]),
        ),
        ...(batch.categoryKey ? { categoryKey: batch.categoryKey } : {}),
        ...(batch.featured !== "keep"
          ? { featured: batch.featured === "true" }
          : {}),
      },
      "POST",
    );
    ElMessage.success("批量调整完成");
    batchOpen.value = false;
    clearSelection();
    list.load();
  } catch (e) {
    notifyError(e);
  } finally {
    saving.value = false;
  }
}
onMounted(async () => {
  try {
    categories.value = (await api("categories")).items;
  } catch (e) {
    notifyError(e);
  }
});
</script>
