<template>
  <PageHeader
    :title="editing ? '编辑商品' : '新建商品'"
    description="共同资料统一维护，各颜色独立设置图片、真实尺码、价格与库存。"
    eyebrow="CATALOG / 商品资料"
    ><ElButton @click="router.push('/products')"
      >返回商品列表</ElButton
    ></PageHeader
  ><ElSkeleton v-if="loading" :rows="12" animated /><ElAlert
    v-if="loadError"
    :title="loadError"
    type="error"
    :closable="false"
    ><ElButton @click="load">重试</ElButton></ElAlert
  ><template v-if="!loading && !loadError"
    ><div class="editor-layout">
      <nav class="editor-anchor">
        <a href="#basic">01 基础资料</a><a href="#colors">02 颜色与图片</a
        ><a href="#sizes">03 尺码与数量</a><a href="#assets">04 图片资料</a>
      </nav>
      <ElForm ref="formRef" :model="form" label-position="top"
        ><section id="basic" class="panel editor-section">
          <div class="panel-title">
            <h2>基础资料</h2>
            <small>同款颜色共同信息</small>
          </div>
          <div class="detail-grid">
            <ElFormItem
              label="商品分类"
              prop="categoryKey"
              :rules="[{ required: true, message: '请选择分类' }]"
              ><ElSelect v-model="form.categoryKey"
                ><ElOption
                  v-for="c in categories"
                  :key="c.key"
                  :value="c.key"
                  :label="c.labels?.zh || c.key" /></ElSelect></ElFormItem
            ><ElFormItem
              label="款式编码"
              prop="familyCode"
              :rules="[{ required: true, message: '请填写款式编码' }]"
              ><ElInput
                v-model.trim="form.familyCode"
                placeholder="例如 GT2026"
            /></ElFormItem>
          </div>
          <ElFormItem
            label="商品标题"
            prop="title"
            :rules="[{ required: true, message: '请填写商品标题' }]"
            ><ElInput
              v-model.trim="form.title"
              maxlength="255"
              show-word-limit /></ElFormItem
          ><ElCheckbox v-model="form.featured">首页推荐</ElCheckbox>
        </section>
        <section id="colors" class="panel editor-section">
          <div class="panel-title">
            <h2>颜色与图片</h2>
            <ElButton @click="addVariant">＋ 添加颜色</ElButton>
          </div>
          <ElAlert
            title="每个颜色需 3–10 张图片。已保存的颜色如需删除，请在商品列表中单独操作。"
            type="info"
            :closable="false"
          />
          <div
            v-for="(variant, index) in form.variants"
            :key="variant.localId"
            class="variant-panel"
          >
            <div class="panel-title">
              <h3>
                颜色 {{ index + 1 }} · {{ variant.colorName || "未命名" }}
              </h3>
              <ElButton
                v-if="!variant.id"
                link
                type="danger"
                @click="form.variants.splice(index, 1)"
                >移除此颜色</ElButton
              >
            </div>
            <div class="detail-grid">
              <ElFormItem
                label="颜色名称"
                :prop="`variants.${index}.colorName`"
                :rules="[{ required: true, message: '请填写颜色名称' }]"
                ><ElInput v-model.trim="variant.colorName" /></ElFormItem
              ><ElFormItem label="颜色值"
                ><ElColorPicker v-model="variant.colorHex" /></ElFormItem
              ><ElFormItem
                label="颜色商品编码"
                :prop="`variants.${index}.productCode`"
                :rules="[{ required: true, message: '请填写商品编码' }]"
                ><ElInput v-model.trim="variant.productCode" /></ElFormItem
              ><ElFormItem
                label="SKU"
                :prop="`variants.${index}.sku`"
                :rules="[{ required: true, message: '请填写 SKU' }]"
                ><ElInput v-model.trim="variant.sku"
              /></ElFormItem>
            </div>
            <ImageUploader
              v-model="variant.images"
              @busy="uploadBusy[variant.localId] = $event"
            />
          </div>
        </section>
        <section id="sizes" class="panel editor-section">
          <div class="panel-title">
            <h2>真实尺码、价格与库存</h2>
            <small>合同未送与待入库在库存模块独立登记</small>
          </div>
          <div class="filters">
            <ElInput
              v-model.trim="newSize"
              placeholder="新增真实尺码，如 Tall XL"
            /><ElButton @click="addSize">添加到所有颜色</ElButton
            ><ElInputNumber
              v-model="bulkPrice"
              :min="0"
              :precision="2"
              placeholder="统一价格"
            /><ElButton @click="fill('price')">应用价格</ElButton
            ><ElInputNumber
              v-model="bulkStock"
              :min="0"
              :precision="0"
              placeholder="统一库存"
            /><ElButton @click="fill('stock')">应用库存</ElButton>
          </div>
          <div
            v-for="variant in form.variants"
            :key="variant.localId"
            class="section-gap"
          >
            <h3>{{ variant.colorName || "未命名颜色" }} · {{ variant.sku }}</h3>
            <div class="size-editor-grid">
              <div
                v-for="(size, index) in variant.sizePrices"
                :key="size.sizeCode"
                class="size-editor-cell"
              >
                <div class="panel-title">
                  <strong>{{ size.sizeCode }}</strong
                  ><ElButton
                    link
                    type="danger"
                    @click="removeSize(variant, index)"
                    >移除</ElButton
                  >
                </div>
                <label>价格（USD）</label
                ><ElInputNumber
                  v-model="size.price"
                  :min="0"
                  :precision="2"
                  controls-position="right"
                /><label>实际库存</label
                ><ElInputNumber
                  v-model="size.stock"
                  :min="0"
                  :precision="0"
                  controls-position="right"
                />
              </div>
            </div>
          </div>
        </section>
        <section id="assets" class="panel editor-section">
          <h2>尺码表与详情图片</h2>
          <div class="detail-grid">
            <div>
              <h3>尺码表</h3>
              <ImageUploader
                v-model="form.chartImages"
                :max="1"
                @busy="uploadBusy.chart = $event"
              />
            </div>
            <div>
              <h3>商品详情图</h3>
              <ImageUploader
                v-model="form.descriptionImages"
                :max="1"
                @busy="uploadBusy.description = $event"
              />
            </div>
          </div></section
      ></ElForm>
    </div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false"
      ><ElButton v-if="conflict" text @click="readLatest"
        >读取最新版本（保留草稿）</ElButton
      ></ElAlert
    >
    <section v-if="latest" class="panel">
      <h3>线上最新商品</h3>
      <p v-for="p in latest" :key="p.id">
        {{ p.sku }} · 当前库存 {{ p.stock }} · {{ dateTime(p.updatedAt) }}
      </p>
      <ElButton @click="adoptLatest">放弃草稿，按最新资料重新编辑</ElButton>
    </section>
    <footer class="save-bar">
      <span class="small-note"
        >{{ dirty ? "有未保存修改" : "所有修改已同步" }} ·
        {{ form.variants.length }} 个颜色</span
      >
      <div>
        <ElButton :disabled="saving" @click="router.push('/products')"
          >取消</ElButton
        ><ElButton
          type="primary"
          :loading="saving"
          :disabled="Object.values(uploadBusy).some(Boolean)"
          @click="submit"
          >保存商品</ElButton
        >
      </div>
    </footer></template
  >
</template>
<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import PageHeader from "../components/PageHeader.vue";
import ImageUploader from "../components/ImageUploader.vue";
import {
  api,
  save,
  useDirty,
  confirm,
  notifyError,
  dateTime,
} from "../composables/workbench";
const route = useRoute(),
  router = useRouter(),
  editing = computed(() => !!route.params.id),
  loading = ref(false),
  loadError = ref(""),
  categories = ref([]),
  formRef = ref(),
  saving = ref(false),
  error = ref(""),
  conflict = ref(false),
  latest = ref(),
  versions = ref({}),
  newSize = ref(""),
  bulkPrice = ref(),
  bulkStock = ref(),
  uploadBusy = reactive({});
const form = reactive({
  categoryKey: "",
  familyCode: "",
  title: "",
  featured: false,
  origin: "China",
  chartImages: [],
  descriptionImages: [],
  variants: [],
});
const { dirty, markClean } = useDirty(() => form);
function addVariant() {
  form.variants.push({
    localId: crypto.randomUUID(),
    id: null,
    colorName: "",
    colorHex: "#334155",
    productCode: "",
    sku: "",
    slug: "",
    images: [],
    sizePrices: (
      form.variants[0]?.sizePrices || [
        { sizeCode: "S" },
        { sizeCode: "M" },
        { sizeCode: "L" },
        { sizeCode: "XL" },
      ]
    ).map((s) => ({ sizeCode: s.sizeCode, price: 0, stock: 0 })),
  });
}
function populate(items) {
  const first = items[0];
  Object.assign(form, {
    categoryKey: first.categoryKey,
    familyCode: first.colorGroup || first.productCode,
    title: first.name.zh || first.name.en,
    featured: first.featured,
    origin: first.origin,
    chartImages: first.sizeChartImage ? [first.sizeChartImage] : [],
    descriptionImages: first.descriptionImage ? [first.descriptionImage] : [],
    variants: items.map((p) => ({
      id: p.id,
      localId: crypto.randomUUID(),
      colorName: p.colorName,
      colorHex: p.colorHex || "#334155",
      productCode: p.productCode,
      sku: p.sku,
      slug: p.slug,
      images: p.gallery.length ? [...p.gallery] : [p.image],
      sizePrices: p.sizePrices.map((s) => ({ ...s })),
    })),
  });
  versions.value = Object.fromEntries(items.map((p) => [p.id, p.version]));
  markClean();
  error.value = "";
  conflict.value = false;
  latest.value = null;
}
async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    categories.value = (await api("categories")).items;
    if (editing.value)
      populate((await api(`products/${route.params.id}/family`)).items);
    else {
      if (!form.variants.length) addVariant();
      markClean();
    }
  } catch (e) {
    loadError.value = e.message;
  } finally {
    loading.value = false;
  }
}
function addSize() {
  if (!newSize.value) return;
  if (newSize.value.length > 32) {
    ElMessage.error("尺码名称不能超过 32 字符");
    return;
  }
  for (const v of form.variants)
    if (!v.sizePrices.some((s) => s.sizeCode === newSize.value))
      v.sizePrices.push({ sizeCode: newSize.value, price: 0, stock: 0 });
  newSize.value = "";
}
async function removeSize(variant, index) {
  if (
    await confirm(
      `移除 ${variant.colorName || "该颜色"} 的 ${variant.sizePrices[index].sizeCode} 尺码？合同未送非零时服务器会阻止删除。`,
    )
  )
    variant.sizePrices.splice(index, 1);
}
async function fill(field) {
  const value = field === "price" ? bulkPrice.value : bulkStock.value;
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < 0 ||
    (field === "stock" && !Number.isInteger(value))
  ) {
    ElMessage.error("请填写有效数量");
    return;
  }
  if (
    await confirm(
      `将全部 ${form.variants.length} 个颜色、${form.variants.reduce((n, v) => n + v.sizePrices.length, 0)} 个尺码的${field === "price" ? "价格" : "库存"}设置为 ${value}？`,
    )
  )
    for (const v of form.variants)
      for (const s of v.sizePrices) s[field] = value;
}
async function submit() {
  if (saving.value || !(await formRef.value.validate().catch(() => false)))
    return;
  error.value = "";
  if (!form.variants.length) {
    error.value = "请至少添加一个颜色";
    return;
  }
  if (!form.chartImages.length || !form.descriptionImages.length) {
    error.value = "请上传尺码表和详情图";
    return;
  }
  for (const v of form.variants) {
    if (v.images.length < 3 || v.images.length > 10) {
      error.value = `${v.colorName} 需要 3–10 张图片`;
      return;
    }
    if (
      !v.sizePrices.length ||
      v.sizePrices.some(
        (s) =>
          !Number.isInteger(s.stock) ||
          s.stock < 0 ||
          typeof s.price !== "number" ||
          !Number.isFinite(s.price) ||
          s.price < 0,
      )
    ) {
      error.value = `请核对 ${v.colorName} 的尺码、价格和非负整数库存`;
      return;
    }
  }
  saving.value = true;
  try {
    const products = form.variants.map((v) => ({
      id: v.id,
      categoryKey: form.categoryKey,
      familyCode: form.familyCode,
      colorGroup: form.familyCode,
      title: form.title,
      featured: form.featured,
      origin: form.origin,
      colorName: v.colorName,
      colorHex: v.colorHex,
      productCode: v.productCode,
      sku: v.sku,
      slug: v.slug || v.productCode.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      sizes: v.sizePrices.map((s) => s.sizeCode),
      sizePrices: v.sizePrices.map((s) => ({
        sizeCode: s.sizeCode,
        stock: s.stock,
        price: s.price,
      })),
      image: v.images[0],
      gallery: v.images,
      sizeChartImage: form.chartImages[0],
      descriptionImage: form.descriptionImages[0],
    }));
    await save(
      "products/save-group",
      { products, versions: versions.value },
      "POST",
    );
    markClean();
    ElMessage.success("商品已保存");
    router.push("/products");
  } catch (e) {
    error.value = e.message;
    conflict.value = e.status === 409;
  } finally {
    saving.value = false;
  }
}
async function readLatest() {
  try {
    latest.value = (await api(`products/${route.params.id}/family`)).items;
  } catch (e) {
    notifyError(e);
  }
}
async function adoptLatest() {
  if (await confirm("放弃当前草稿，使用线上最新资料？")) populate(latest.value);
}
onMounted(load);
</script>
<style scoped>
.variant-panel {
  padding: 20px 0;
  border-bottom: 1px solid var(--line);
}
.variant-panel:last-child {
  border: 0;
}
.filters .el-input-number {
  width: 130px;
}
.filters .el-input {
  width: 200px;
}
</style>
