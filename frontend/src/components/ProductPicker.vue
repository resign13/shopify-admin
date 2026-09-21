<template>
  <ElDrawer v-model="open" title="选择商品" size="820px"
    ><form
      class="filters"
      @submit.prevent="
        query.page = 1;
        load();
      "
    >
      <ElInput
        v-model="query.keyword"
        clearable
        placeholder="标题、款式或 SKU"
      /><ElSelect v-model="query.category" clearable placeholder="全部分类"
        ><ElOption
          v-for="c in categories"
          :key="c.key"
          :value="c.key"
          :label="c.labels?.zh || c.key" /></ElSelect
      ><ElButton native-type="submit">查询</ElButton>
    </form>
    <ElAlert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
    /><ElTable
      ref="table"
      v-loading="loading"
      :data="rows"
      row-key="id"
      @selection-change="selected = $event"
      ><ElTableColumn
        type="selection"
        reserve-selection
        :selectable="(row) => !modelValue.includes(row.id)"
        width="40"
      /><ElTableColumn label="款号"
        ><template #default="{ row }"
          ><div class="product-cell">
            <span class="product-name" :title="row.sku">{{ row.sku }}</span>
          </div></template
        ></ElTableColumn
      ><ElTableColumn label="操作" width="100"
        ><template #default="{ row }"
          ><ElButton
            :disabled="modelValue.includes(row.id)"
            link
            type="primary"
            @click="$emit('select', row)"
            >{{ modelValue.includes(row.id) ? "已加入" : "加入" }}</ElButton
          ></template
        ></ElTableColumn
      ></ElTable
    ><ElPagination
      v-model:current-page="query.page"
      :page-size="25"
      :total="total"
      layout="total,prev,pager,next"
      class="section-gap"
      @current-change="load"
    /><template #footer
      ><span class="small-note">已选 {{ selected.length }} 个商品 </span
      ><ElButton
        type="primary"
        :disabled="!selected.length"
        @click="
          emit('select-many', selected);
          table.clearSelection();
          open = false;
        "
        >加入所选并完成</ElButton
      ></template
    ></ElDrawer
  >
</template>
<script setup>
import { computed, reactive, ref, watch } from "vue";
import { api } from "../composables/workbench";
const props = defineProps({
    visible: Boolean,
    modelValue: { type: Array, default: () => [] },
    categories: Array,
  }),
  emit = defineEmits(["update:visible", "select", "select-many"]);
const table = ref(),
  selected = ref([]);
const open = computed({
    get: () => props.visible,
    set: (v) => emit("update:visible", v),
  }),
  query = reactive({ page: 1, pageSize: 25, keyword: "", category: "" }),
  rows = ref([]),
  total = ref(0),
  loading = ref(false),
  error = ref("");
let serial = 0;
async function load() {
  const id = ++serial;
  loading.value = true;
  error.value = "";
  try {
    const result = await api("products?" + new URLSearchParams(query));
    if (id === serial) {
      rows.value = result.items;
      total.value = result.total;
    }
  } catch (e) {
    if (id === serial) error.value = e.message;
  } finally {
    if (id === serial) loading.value = false;
  }
}
watch(
  () => [query.keyword, query.category],
  () => {
    selected.value = [];
    table.value?.clearSelection();
  },
);
watch(
  () => props.visible,
  (v) => {
    if (v) {
      selected.value = [];
      table.value?.clearSelection();
      load();
    }
  },
);
</script>

