<template>
  <PageHeader
    :title="editing ? '编辑商品' : '新建商品'"
    mobile-description="共同资料统一维护，颜色与尺码独立设置"
    description="共同资料统一维护，各颜色独立设置图片、真实尺码、价格、库存与净重。"
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
    ><nav v-if="isPhone" class="mobile-editor-tabs" aria-label="商品编辑步骤"><button v-for="(tab,index) in mobileEditorTabs" :key="tab.key" type="button" :class="{ active: mobileEditorSection === tab.key }" :aria-current="mobileEditorSection === tab.key ? 'step' : undefined" @click="mobileEditorSection = tab.key"><span>{{ index+1 }}</span>{{ tab.label }}</button></nav><div class="editor-layout">
      <nav class="editor-anchor">
        <a href="#basic">01 基础资料</a><a href="#colors">02 颜色与图片</a
        ><a href="#sizes">03 尺码与数量</a><a href="#assets">04 图片资料</a>
      </nav>
      <ElForm ref="formRef" :model="form" label-position="top"
        ><section v-show="!isPhone || mobileEditorSection === 'basic'" id="basic" class="panel editor-section">
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
          >
        </section>
        <section v-show="!isPhone || mobileEditorSection === 'colors'" id="colors" class="panel editor-section">
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
            <ImageUploader purpose="product"
              v-model="variant.images"
              @busy="uploadBusy[variant.localId] = $event"
            />
          </div>
        </section>
        <section v-show="!isPhone || mobileEditorSection === 'sizes'" id="sizes" class="panel editor-section">
          <div class="panel-title">
            <h2>真实尺码、价格、库存与净重</h2>
            <small>合同未送与合格在库存模块独立登记</small>
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
              :min="-2147483648"
              :max="2147483647"
              :precision="0"
              placeholder="统一库存"
            /><ElButton @click="fill('stock')">应用库存</ElButton>
          </div>
          <div class="filters weight-bulk-tools" data-testid="weight-bulk-tools">
            <ElSelect v-model="weightSizeCode" :empty-values="[null, undefined]" aria-label="批量重量尺码" style="width: 160px">
              <ElOption label="全部尺码" value="" />
              <ElOption v-for="code in weightSizes" :key="code" :label="code" :value="code" />
            </ElSelect>
            <ElInputNumber v-model="bulkWeight" :min="1" :max="MAX_WEIGHT_GRAMS" :precision="0" controls-position="right" placeholder="单件净重（g）" aria-label="批量单件净重（g）" />
            <ElButton @click="fillWeight">批量应用重量</ElButton>
            <small class="small-note">单件商品净重，不含包装；应用后保存商品才生效。</small>
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
                /><label>现货余额</label
                ><ElInputNumber
                  v-model="size.stock"
                  :min="-2147483648"
                  :max="2147483647"
                  :precision="0"
                  controls-position="right"
                /><label>单件净重（g）</label>
                <ElInputNumber v-model="size.weightGrams" :min="1" :max="MAX_WEIGHT_GRAMS" :precision="0" controls-position="right" placeholder="未设置" :aria-label="`${variant.colorName || '未命名颜色'} ${size.sizeCode} 单件净重（g）`" />
              </div>
            </div>
          </div>
        </section>
        <section v-show="!isPhone || mobileEditorSection === 'assets'" id="assets" class="panel editor-section">
          <h2>尺码表与详情图片</h2>
          <div class="detail-grid">
            <div>
              <h3>尺码表</h3>
              <ImageUploader purpose="product"
                v-model="form.chartImages"
                :max="1"
                @busy="uploadBusy.chart = $event"
              />
            </div>
            <div>
              <h3>商品详情图</h3>
              <ImageUploader purpose="product"
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
        ><ElButton v-if="isPhone && mobileEditorSection !== 'assets'" type="primary" :disabled="saving" @click="nextMobileSection">下一步</ElButton><ElButton v-else
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
import { useResponsive } from '../composables/responsive';
import { productSlug } from "../utils/productSlug";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { MAX_WEIGHT_GRAMS, validWeight, realWeightSizes, weightTargets, applyWeight } from "../utils/productWeights";
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
const { isPhone } = useResponsive();
const mobileEditorSection=ref('basic');
const mobileEditorTabs=[{key:'basic',label:'基础'},{key:'colors',label:'颜色'},{key:'sizes',label:'尺码'},{key:'assets',label:'图片'}];
function nextMobileSection(){const index=mobileEditorTabs.findIndex(tab=>tab.key===mobileEditorSection.value);mobileEditorSection.value=mobileEditorTabs[Math.min(index+1,mobileEditorTabs.length-1)].key;window.scrollTo({top:0,behavior:'smooth'});}
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
  bulkWeight = ref(),
  weightSizeCode = ref(""),
  uploadBusy = reactive({});
const form = reactive({
  categoryKey: "",
  familyCode: "",
  title: "",
  origin: "China",
  chartImages: [],
  descriptionImages: [],
  variants: [],
});
const { dirty, markClean } = useDirty(() => form);
const weightSizes = computed(() => realWeightSizes(form.variants));
watch(weightSizes, (codes) => { if (weightSizeCode.value && !codes.includes(weightSizeCode.value)) weightSizeCode.value = ""; });
async function fillWeight() {
  if (!validWeight(bulkWeight.value)) { ElMessage.error("单件净重请填写正整数克数"); return; }
  const targets = weightTargets(form.variants, weightSizeCode.value);
  if (!targets.length) { ElMessage.info("没有可应用的尺码"); return; }
  const changed = targets.filter(({ size }) => size.weightGrams !== bulkWeight.value);
  if (!changed.length) { ElMessage.info("对应尺码已经使用该重量"); return; }
  const overwritten = changed.filter(({ size }) => size.weightGrams != null).length;
  const colors = new Set(targets.map(({ variant }) => variant.localId)).size;
  if (overwritten && !(await confirm(`将 ${colors} 个颜色、${targets.length} 个尺码的单件净重设为 ${bulkWeight.value} g，其中 ${overwritten} 个已填重量将被覆盖。保存商品后生效，是否应用？`))) return;
  applyWeight(form.variants, weightSizeCode.value, bulkWeight.value);
  ElMessage.success(`已应用到 ${targets.length} 个尺码，请保存商品`);
}
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
    ).map((s) => ({ sizeCode: s.sizeCode, price: 0, stock: 0, weightGrams: null })),
  });
}
function populate(items) {
  const first = items[0];
  Object.assign(form, {
    categoryKey: first.categoryKey,
    familyCode: first.colorGroup || first.productCode,
    title: first.name.zh || first.name.en,
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
    categories.value = (await api("catalog-options")).items;
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
      v.sizePrices.push({ sizeCode: newSize.value, price: 0, stock: 0, weightGrams: null });
  newSize.value = "";
}
async function removeSize(variant, index) {
  if (
    await confirm(
      `移除 ${variant.colorName || "该颜色"} 的 ${variant.sizePrices[index].sizeCode} 尺码？存在欠货、在途数量或未履约订单时不能删除。`,
    )
  )
    variant.sizePrices.splice(index, 1);
}
async function fill(field) {
  const value = field === "price" ? bulkPrice.value : bulkStock.value;
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    (field === "price" && value < 0) ||
    (field === "stock" && (!Number.isInteger(value) || value < -2147483648 || value > 2147483647))
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
  if (saving.value) return;
  const valid = await formRef.value.validate().catch((fields) => {
    if (isPhone.value) mobileEditorSection.value = Object.keys(fields || {})[0]?.startsWith('variants.') ? 'colors' : 'basic';
    return false;
  });
  if (!valid) return;
  error.value = "";
  if (!form.variants.length) {
    if (isPhone.value) mobileEditorSection.value = "colors";
    error.value = "请至少添加一个颜色";
    return;
  }
  if (!form.chartImages.length || !form.descriptionImages.length) {
    if (isPhone.value) mobileEditorSection.value = "assets";
    error.value = "请上传尺码表和详情图";
    return;
  }
  for (const v of form.variants) {
    if (v.images.length < 3 || v.images.length > 10) {
      if (isPhone.value) mobileEditorSection.value = "colors";
      error.value = `${v.colorName} 需要 3–10 张图片`;
      return;
    }
    if (
      !v.sizePrices.length ||
      v.sizePrices.some(
        (s) =>
          !Number.isInteger(s.stock) ||
          s.stock < -2147483648 || s.stock > 2147483647 ||
          typeof s.price !== "number" ||
          !Number.isFinite(s.price) ||
          s.price < 0 ||
          (s.weightGrams != null && !validWeight(s.weightGrams)),
      )
    ) {
      if (isPhone.value) mobileEditorSection.value = "sizes";
      error.value = `请核对 ${v.colorName} 的尺码、价格、整数现货余额及正整数净重`;
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
      origin: form.origin,
      colorName: v.colorName,
      colorHex: v.colorHex,
      productCode: v.productCode,
      sku: v.sku,
      slug: v.slug || productSlug(v.productCode),
      sizes: v.sizePrices.map((s) => s.sizeCode),
      sizePrices: v.sizePrices.map((s) => ({
        sizeCode: s.sizeCode,
        stock: s.stock,
        price: s.price,
        weightGrams: s.weightGrams ?? null,
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
.weight-bulk-tools .el-input-number {
  width: 160px;
}
@media (max-width: 760px) {
  .editor-layout { display: block; }
  .editor-anchor { display: none; }
  .save-bar { padding: 12px; gap: 8px; flex-wrap: wrap; }
}
</style>

<style scoped>
@media(max-width:767px){.mobile-editor-tabs{display:flex;gap:6px;margin:0 0 18px;padding:6px;border:1px solid #e7edf6;border-radius:14px;background:#fff}.mobile-editor-tabs button{display:flex;gap:6px;align-items:center;justify-content:center;flex:1;min-width:0;padding:9px 4px;border:0;border-radius:10px;background:none;font:inherit;font-size:12px;color:#8c9ab0}.mobile-editor-tabs button span{display:grid;place-items:center;width:18px;height:18px;border-radius:6px;background:#f0f3f8;font-size:10px}.mobile-editor-tabs button.active{background:#eff4fe;color:#2f69eb}.mobile-editor-tabs button.active span{background:#2f69eb;color:#fff}.editor-section{padding:18px!important;border:1px solid #e7edf6!important;border-radius:17px!important;background:#fff!important}.editor-section h2{font-size:15px;color:#182b49}.editor-section h3{font-size:13px;color:#182b49}.editor-section .detail-grid{grid-template-columns:1fr}.variant-panel{margin:14px 0;padding:16px 0}.variant-panel .panel-title{align-items:flex-start}.size-editor-grid{grid-template-columns:1fr}.size-editor-cell{padding:15px;border-radius:14px;border:1px solid #e8edf5;background:#f9fbff}.size-editor-cell .el-input-number{width:100%}.filters{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}.filters .el-input,.filters .el-input-number{width:100%!important}.weight-bulk-tools{display:flex;flex-wrap:wrap}.weight-bulk-tools small{width:100%;font-size:10px;line-height:1.7}.save-bar{border-radius:15px;font-size:11px}.save-bar>div{display:flex;gap:8px}.save-bar .el-button+.el-button{margin-left:0}.editor-section :deep(.el-form-item__label){font-size:12px;color:#6f829f}.editor-section :deep(.el-input__wrapper){border-radius:10px}.editor-section :deep(.image-grid){grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.editor-section :deep(.image-tile){min-width:0}.editor-section :deep(.image-tools){flex-wrap:wrap}}
</style>
