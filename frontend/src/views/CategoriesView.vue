<template>
  <PageHeader
    title="商品分类"
    description="维护分类名称与展示顺序，保持商品组织清晰。"
    eyebrow="CATALOG / 商品与库存"
    ><ElButton type="primary" @click="edit()">＋ 新建分类</ElButton></PageHeader
  >
  <section class="panel">
    <div class="filters">
      <ElInput
        v-model="keyword"
        clearable
        placeholder="搜索分类编码或名称"
        @input="page = 1"
      />
    </div>
    <DataTable
      storage-key="categories"
      :rows="filtered.slice((page - 1) * pageSize, page * pageSize)"
      :columns="columns"
      :total="filtered.length"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      :error="error"
      @retry="load"
      @sort-change="sort = $event"
      @page="page = $event"
      @page-size="
        pageSize = $event;
        page = 1;
      "
      ><template #zh="{ row }">{{ row.labels.zh }}</template
      ><template #en="{ row }">{{ row.labels.en }}</template
      ><template #actions="{ row }"
        ><ElButton link type="primary" @click="edit(row)">编辑</ElButton
        ><ElButton link type="danger" @click="remove(row)"
          >删除</ElButton
        ></template
      ></DataTable
    >
  </section>
  <ElDrawer
    v-model="open"
    :title="form.id ? '编辑分类' : '新建分类'"
    size="480px"
    :before-close="close"
    ><ElForm ref="formRef" :model="form" label-position="top"
      ><ElFormItem
        label="分类编码"
        prop="key"
        :rules="[{ required: true, message: '请输入分类编码' }]"
        ><ElInput
          v-model.trim="form.key"
          placeholder="例如 denim" /></ElFormItem
      ><ElFormItem
        label="中文名称"
        prop="labels.zh"
        :rules="[{ required: true, message: '请输入中文名称' }]"
        ><ElInput v-model.trim="form.labels.zh" /></ElFormItem
      ><ElFormItem
        label="英文名称"
        prop="labels.en"
        :rules="[{ required: true, message: '请输入英文名称' }]"
        ><ElInput v-model.trim="form.labels.en" /></ElFormItem
      ><ElFormItem label="排序值（小的优先）"
        ><ElInputNumber
          v-model="form.sortOrder"
          :min="0"
          :precision="0" /></ElFormItem
      ><ElAlert
        v-if="saveError"
        :title="saveError"
        type="error"
        :closable="false" /></ElForm
    ><template #footer
      ><ElButton :disabled="saving" @click="close()">取消</ElButton
      ><ElButton type="primary" :loading="saving" @click="submit"
        >保存分类</ElButton
      ></template
    ></ElDrawer
  >
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import {
  api,
  save,
  notifyError,
  confirm,
  useDirty,
} from "../composables/workbench";
const route = useRoute(),
  router = useRouter(),
  items = ref([]),
  keyword = ref(route.query.keyword || ""),
  page = ref(Number(route.query.page) || 1),
  pageSize = ref(Number(route.query.pageSize) || 25),
  sort = ref({ prop: "sortOrder", order: "ascending" }),
  loading = ref(false),
  error = ref(""),
  open = ref(false),
  saving = ref(false),
  formRef = ref(),
  saveError = ref(""),
  form = reactive({
    id: null,
    key: "",
    sortOrder: 0,
    labels: { zh: "", en: "" },
  });
const { markClean, canLeave } = useDirty(() => form);
const columns = [
  { prop: "key", label: "分类编码", sortable: true },
  { prop: "zh", label: "中文名称" },
  { prop: "en", label: "英文名称" },
  { prop: "productCount", label: "关联商品", numeric: true, sortable: true },
  { prop: "sortOrder", label: "排序", numeric: true, sortable: true },
  { prop: "actions", label: "操作", width: 110 },
];
const filtered = computed(() =>
  items.value
    .filter((i) =>
      [i.key, i.labels.zh, i.labels.en]
        .join(" ")
        .toLowerCase()
        .includes(keyword.value.toLowerCase()),
    )
    .sort(
      (a, b) =>
        String(a[sort.value.prop] ?? "").localeCompare(
          String(b[sort.value.prop] ?? ""),
          undefined,
          { numeric: true },
        ) * (sort.value.order === "descending" ? -1 : 1),
    ),
);
watch([keyword, page, pageSize], () =>
  router.replace({
    query: {
      keyword: keyword.value,
      page: page.value,
      pageSize: pageSize.value,
    },
  }),
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    items.value = (await api("categories")).items;
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function edit(row) {
  Object.assign(
    form,
    { id: null, key: "", sortOrder: 0, labels: { zh: "", en: "" } },
    row ? JSON.parse(JSON.stringify(row)) : {},
  );
  saveError.value = "";
  open.value = true;
  markClean();
}
async function close(done) {
  if (saving.value) return;
  if (await canLeave()) {
    markClean();
    open.value = false;
    if (typeof done === "function") done();
  }
}
async function submit() {
  if (saving.value || !(await formRef.value.validate().catch(() => false)))
    return;
  saving.value = true;
  try {
    await save(
      `categories${form.id ? "/" + form.id : ""}`,
      form,
      form.id ? "PUT" : "POST",
    );
    markClean();
    open.value = false;
    load();
    ElMessage.success("分类已保存");
  } catch (e) {
    saveError.value = e.message;
  } finally {
    saving.value = false;
  }
}
async function remove(row) {
  if (row.productCount) {
    ElMessage.warning("此分类仍有关联商品，请先将商品调整至其他分类");
    return;
  }
  if (await confirm(`删除分类“${row.labels.zh}”？`)) {
    try {
      await save(`categories/${row.id}`, {}, "DELETE");
      load();
    } catch (e) {
      notifyError(e);
    }
  }
}
onMounted(load);
</script>
