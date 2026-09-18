<template>
  <PageHeader
    :title="title"
    :description="
      isHome
        ? '配置面板与待保存结构预览，保存后更新商城首页。'
        : '按活动模块维护报名商品，加入、移除和排序均在保存后生效。'
    "
    eyebrow="OPERATIONS / 商城运营"
  /><ElSkeleton v-if="loading" :rows="10" animated /><ElAlert
    v-if="loadError"
    :title="loadError"
    type="error"
    :closable="false"
    ><ElButton @click="load">重试</ElButton></ElAlert
  ><template v-if="ready"
    ><div :class="{ 'operations-layout': isHome }">
      <div>
        <template v-if="isHome"
          ><section class="panel">
            <h2>首页海报</h2>
            <div class="hero-edit-grid">
              <div v-for="m in modules" :key="m.key">
                <h3>{{ m.label }}</h3>
                <ImageUploader
                  :model-value="
                    form.heroBanners[m.key] ? [form.heroBanners[m.key]] : []
                  "
                  :max="1"
                  @update:model-value="
                    form.heroBanners[m.key] = $event[0] || ''
                  "
                  @busy="busy[m.key] = $event"
                />
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-title">
              <h2>展示分类</h2>
              <small>最多 5 个，按顺序展示</small>
            </div>
            <div class="filters">
              <ElSelect v-model="categoryDraft" placeholder="选择分类"
                ><ElOption
                  v-for="c in categories.filter(
                    (c) => !form.displayCategoryKeys.includes(c.key),
                  )"
                  :key="c.key"
                  :value="c.key"
                  :label="c.labels?.zh || c.key" /></ElSelect
              ><ElButton
                :disabled="
                  !categoryDraft || form.displayCategoryKeys.length >= 5
                "
                @click="
                  form.displayCategoryKeys.push(categoryDraft);
                  categoryDraft = '';
                "
                >添加分类</ElButton
              >
            </div>
            <div
              v-for="(key, index) in form.displayCategoryKeys"
              :key="key"
              class="list-row stack-row"
            >
              <span>{{ index + 1 }} · {{ categoryName(key) }}</span>
              <div>
                <ElButton
                  link
                  :disabled="index === 0"
                  @click="move(form.displayCategoryKeys, index, -1)"
                  >上移</ElButton
                ><ElButton
                  link
                  :disabled="index === form.displayCategoryKeys.length - 1"
                  @click="move(form.displayCategoryKeys, index, 1)"
                  >下移</ElButton
                ><ElButton
                  link
                  type="danger"
                  @click="form.displayCategoryKeys.splice(index, 1)"
                  >移除</ElButton
                >
              </div>
            </div>
          </section></template
        >
        <section class="panel">
          <div class="panel-title">
            <h2>{{ isHome ? "首页推荐商品" : "活动商品" }}</h2>
            <ElButton type="primary" @click="pickerOpen = true"
              >＋ {{ isHome ? "选择推荐商品" : "报名商品" }}</ElButton
            >
          </div>
          <ElTabs v-model="module"
            ><ElTabPane
              v-for="m in modules"
              :key="m.key"
              :name="m.key"
              :label="`${m.label} (${form[field][m.key].length})`"
          /></ElTabs>
          <p class="small-note">
            {{
              isHome
                ? "每个模块最多展示 5 个商品。"
                : "列表顺序即活动展示顺序；跨页勾选只作用于明确选中的商品。"
            }}
            本次新增 {{ added }}，移除 {{ removed }}。
          </p>
          <form class="filters" @submit.prevent="apply">
            <ElInput
              v-model="keywordDraft"
              clearable
              placeholder="在已选商品中搜索"
            /><ElButton native-type="submit">查询</ElButton
            ><ElButton
              @click="
                keywordDraft = '';
                apply();
              "
              >重置</ElButton
            >
          </form>
          <div v-if="selected.length" class="batch-bar">
            <span>已选 {{ selected.length }} 个商品</span
            ><ElButton @click="removeSelected">移除所选</ElButton
            ><ElButton text @click="table.clearSelection()">清空选择</ElButton>
          </div>
          <DataTable
            ref="table"
            :key="module + keyword"
            :storage-key="`operations-${mode}`"
            :rows="rows"
            :columns="columns"
            :total="total"
            :page="page"
            :page-size="pageSize"
            :loading="rowsLoading"
            :error="rowsError"
            selectable
            @selection-change="selected = $event"
            @page="page = $event"
            @page-size="
              pageSize = $event;
              page = 1;
            "
            @retry="loadRows"
            ><template #name="{ row }"
              ><div class="product-cell">
                <ProductImage :src="row.image" />
                <div>
                  <RouterLink
                    :to="`/products/${row.id}/edit`"
                    class="product-name"
                    :title="productName(row)"
                    >{{ shortName(row) }}</RouterLink
                  ><small>{{ row.sku }} · {{ row.colorName }}</small>
                </div>
              </div></template
            ><template #state="{ row }"
              ><ElTag
                :type="originalIds.includes(row.id) ? 'info' : 'success'"
                >{{
                  originalIds.includes(row.id) ? "已报名" : "本次新增"
                }}</ElTag
              ></template
            ><template #actions="{ row }"
              ><ElButton
                link
                :disabled="ids.indexOf(row.id) === 0"
                @click="move(ids, ids.indexOf(row.id), -1)"
                >上移</ElButton
              ><ElButton
                link
                :disabled="ids.indexOf(row.id) === ids.length - 1"
                @click="move(ids, ids.indexOf(row.id), 1)"
                >下移</ElButton
              ><ElButton link type="danger" @click="removeIds([row.id])"
                >移除</ElButton
              ></template
            ></DataTable
          >
        </section>
      </div>
      <aside v-if="isHome" class="panel structure-preview">
        <div class="panel-title">
          <h2>结构预览</h2>
          <ElTag type="info">待保存</ElTag>
        </div>
        <div class="preview-categories">
          <ElTag
            v-for="key in form.displayCategoryKeys"
            :key="key"
            type="info"
            >{{ categoryName(key) }}</ElTag
          >
        </div>
        <div v-for="m in modules" :key="m.key" class="preview-module">
          <ElImage
            v-if="form.heroBanners[m.key]"
            :src="imageUrl(form.heroBanners[m.key], 320)"
            fit="cover"
          />
          <div v-else class="empty-state">{{ m.label }} 海报待设置</div>
          <h3>{{ m.label }}</h3>
          <p class="small-note">
            推荐商品 {{ form.sectionProductIds[m.key].length }} 个 · 活动商品
            {{ form.collectionProductIds[m.key].length }} 个
          </p>
          <div class="preview-products">
            <RouterLink
              v-for="id in form.sectionProductIds[m.key]"
              :key="id"
              :to="`/products/${id}/edit`"
              >{{ names[id] || `商品 #${id}` }}</RouterLink
            >
          </div>
        </div>
      </aside>
    </div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false"
      ><ElButton v-if="conflict" text @click="readLatest"
        >读取最新配置（保留草稿）</ElButton
      ></ElAlert
    >
    <section v-if="latest" class="panel">
      <h3>线上最新配置</h3>
      <p v-for="m in modules" :key="m.key">
        {{ m.label }}：推荐
        {{ latest.sectionProductIds[m.key].length }} 个，活动
        {{ latest.collectionProductIds[m.key].length }} 个
      </p>
      <ElButton @click="adoptLatest">放弃草稿，使用最新配置</ElButton>
    </section>
    <footer class="save-bar">
      <span>{{ dirty ? "有未保存修改" : "配置已同步" }}</span>
      <div>
        <ElButton :disabled="saving || !dirty" @click="discard"
          >放弃修改</ElButton
        ><ElButton
          type="primary"
          :loading="saving"
          :disabled="!dirty || Object.values(busy).some(Boolean)"
          @click="submit"
          >保存{{ isHome ? "首页配置" : "活动调整" }}</ElButton
        >
      </div>
    </footer>
    <ProductPicker
      v-model:visible="pickerOpen"
      :model-value="ids"
      :categories="categories"
      @select="add"
      @select-many="addMany"
  /></template>
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import PageHeader from "./PageHeader.vue";
import DataTable from "./DataTable.vue";
import ProductImage from "./ProductImage.vue";
import ImageUploader from "./ImageUploader.vue";
import ProductPicker from "./ProductPicker.vue";
import {
  api,
  save,
  useDirty,
  confirm,
  notifyError,
  productName,
  shortName,
} from "../composables/workbench";
import { imageUrl } from "../utils/imageUrl";
const props = defineProps({ mode: { type: String, default: "home" } }),
  isHome = computed(() => props.mode === "home"),
  title = computed(() =>
    isHome.value
      ? "首页配置"
      : props.mode === "apply"
        ? "活动报名"
        : "活动管理",
  ),
  field = computed(() =>
    isHome.value ? "sectionProductIds" : "collectionProductIds",
  );
const modules = [
    { key: "bestSeller", label: "Best Seller" },
    { key: "newArrival", label: "New Arrival" },
    { key: "specialPrice", label: "PRE-ORDER" },
  ],
  module = ref("bestSeller"),
  form = reactive({}),
  baseline = ref(),
  ready = ref(false),
  loading = ref(false),
  loadError = ref(""),
  categories = ref([]),
  categoryDraft = ref(""),
  busy = reactive({}),
  names = reactive({}),
  pickerOpen = ref(false),
  saving = ref(false),
  error = ref(""),
  conflict = ref(false),
  latest = ref();
const { dirty, markClean } = useDirty(() => form),
  ids = computed(() => form[field.value]?.[module.value] || []),
  originalIds = computed(
    () => baseline.value?.[field.value]?.[module.value] || [],
  ),
  added = computed(
    () => ids.value.filter((id) => !originalIds.value.includes(id)).length,
  ),
  removed = computed(
    () => originalIds.value.filter((id) => !ids.value.includes(id)).length,
  );
const rows = ref([]),
  total = ref(0),
  rowsLoading = ref(false),
  rowsError = ref(""),
  page = ref(1),
  pageSize = ref(25),
  keyword = ref(""),
  keywordDraft = ref(""),
  table = ref(),
  selected = ref([]);
const columns = [
  { prop: "name", label: "商品 / 颜色 SKU", width: 250 },
  { prop: "state", label: "状态", width: 90 },
  { prop: "actions", label: "操作", width: 160 },
];
function categoryName(key) {
  return categories.value.find((c) => c.key === key)?.labels?.zh || key;
}
function populate(value) {
  Object.assign(form, JSON.parse(JSON.stringify(value)));
  baseline.value = JSON.parse(JSON.stringify(value));
  ready.value = true;
  error.value = "";
  conflict.value = false;
  latest.value = null;
  markClean();
  loadRows();
}
async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const [config, cats] = await Promise.all([
      api("home-config"),
      api("categories"),
    ]);
    categories.value = cats.items;
    populate(config.config);
  } catch (e) {
    loadError.value = e.message;
  } finally {
    loading.value = false;
  }
}
let serial = 0;
async function loadRows() {
  const current = ++serial;
  if (!ids.value.length) {
    rows.value = [];
    total.value = 0;
    rowsLoading.value = false;
    return;
  }
  rowsLoading.value = true;
  rowsError.value = "";
  try {
    const params = new URLSearchParams({
      page: page.value,
      pageSize: pageSize.value,
      ids: ids.value.join(","),
      sort: "configured",
      keyword: keyword.value,
    });
    const result = await api("products?" + params);
    if (current === serial) {
      rows.value = result.items;
      total.value = result.total;
      for (const p of result.items) names[p.id] = productName(p);
    }
  } catch (e) {
    if (current === serial) rowsError.value = e.message;
  } finally {
    if (current === serial) rowsLoading.value = false;
  }
}
watch([() => ids.value.join(","), page, pageSize, keyword], loadRows);
watch(module, () => {
  page.value = 1;
  selected.value = [];
  keyword.value = "";
  keywordDraft.value = "";
});
function apply() {
  if (selected.value.length) ElMessage.info("查询条件已改变，已清空选择");
  selected.value = [];
  table.value?.clearSelection();
  page.value = 1;
  keyword.value = keywordDraft.value;
  loadRows();
}
function add(row) {
  if (ids.value.includes(row.id)) return;
  if (isHome.value && ids.value.length >= 5) {
    ElMessage.warning("首页每个模块最多 5 个商品");
    return;
  }
  ids.value.push(row.id);
  names[row.id] = productName(row);
  ElMessage.success("已加入待保存列表");
}
async function addMany(rows) {
  const fresh = rows.filter((row) => !ids.value.includes(row.id));
  if (isHome.value && ids.value.length + fresh.length > 5) {
    ElMessage.warning("首页每个模块最多 5 个商品，请减少选择数量");
    return;
  }
  if (!(await confirm(`将 ${fresh.length} 个商品加入当前模块？保存后生效。`)))
    return;
  for (const row of fresh) {
    ids.value.push(row.id);
    names[row.id] = productName(row);
  }
}
function move(values, index, offset) {
  const other = index + offset;
  if (other < 0 || other >= values.length) return;
  [values[index], values[other]] = [values[other], values[index]];
}
async function removeIds(values) {
  if (!(await confirm(`从当前模块移除 ${values.length} 个商品？保存后生效。`)))
    return;
  form[field.value][module.value] = ids.value.filter(
    (id) => !values.includes(id),
  );
  selected.value = [];
  table.value?.clearSelection();
  page.value = 1;
}
function removeSelected() {
  return removeIds(selected.value.map((p) => p.id));
}
async function discard() {
  if (await confirm("放弃本次尚未保存的配置？")) populate(baseline.value);
}
async function submit() {
  if (saving.value) return;
  error.value = "";
  if (modules.some((m) => !form.heroBanners[m.key])) {
    error.value = "请先在首页配置中补齐三个模块海报";
    return;
  }
  saving.value = true;
  try {
    const result = await save("home-config", form);
    populate(result.config);
    ElMessage.success("配置已保存");
  } catch (e) {
    error.value = e.message;
    conflict.value = e.status === 409;
  } finally {
    saving.value = false;
  }
}
async function readLatest() {
  try {
    latest.value = (await api("home-config")).config;
  } catch (e) {
    notifyError(e);
  }
}
async function adoptLatest() {
  if (await confirm("放弃当前草稿，使用线上最新配置？")) populate(latest.value);
}
onMounted(load);
</script>
<style scoped>
.operations-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: start;
}
.hero-edit-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.structure-preview {
  position: sticky;
  top: 76px;
}
.preview-categories {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.preview-module {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.preview-module > .el-image {
  width: 100%;
  height: 90px;
  margin-bottom: 12px;
}
.preview-products {
  display: grid;
  gap: 6px;
}
.preview-products a {
  padding: 8px;
  background: var(--bg);
  border-radius: 4px;
  overflow-wrap: anywhere;
  font-size: 12px;
}
@media (max-width: 1350px) {
  .operations-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .structure-preview {
    position: static;
  }
  .preview-module {
    display: inline-block;
    vertical-align: top;
    width: 32%;
    padding: 12px;
  }
}
</style>
