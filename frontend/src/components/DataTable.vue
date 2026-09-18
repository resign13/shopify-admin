<template>
  <div ref="container" class="data-toolbar">
    <span>{{ total }} 条记录</span>
    <div>
      <slot name="toolbar" /><ElRadioGroup v-model="density" size="small"
        ><ElRadioButton value="small">紧凑</ElRadioButton
        ><ElRadioButton value="default">舒适</ElRadioButton></ElRadioGroup
      ><ElPopover trigger="click" width="200"
        ><template #reference><ElButton>显示列</ElButton></template
        ><ElCheckboxGroup v-model="visible"
          ><ElCheckbox
            v-for="column in columns"
            :key="column.prop"
            :value="column.prop"
            >{{ column.label }}</ElCheckbox
          ></ElCheckboxGroup
        ></ElPopover
      >
    </div>
  </div>
  <ElAlert v-if="error" :title="error" type="error" show-icon :closable="false"
    ><ElButton text @click="$emit('retry')">重试</ElButton></ElAlert
  >
  <ElTable
    ref="table"
    v-loading="loading"
    :data="rows"
    row-key="id"
    :size="density"
    empty-text="暂无符合条件的数据"
    @sort-change="$emit('sort-change', $event)"
    @selection-change="$emit('selection-change', $event)"
  >
    <ElTableColumn v-if="expandable" type="expand" width="38"
      ><template #default="{ row }"
        ><slot name="expanded" :row="row" /></template
    ></ElTableColumn>
    <ElTableColumn
      v-if="selectable"
      type="selection"
      :reserve-selection="true"
      width="40"
    />
    <ElTableColumn
      v-for="column in shown"
      :key="column.prop"
      :prop="column.prop"
      :label="column.label"
      :min-width="columnWidth(column)"
      :sortable="column.sortable ? 'custom' : false"
      :align="column.numeric ? 'right' : 'left'"
    >
      <template #default="{ row }"
        ><slot :name="column.prop" :row="row"
          ><span class="cell-value">{{ row[column.prop] ?? "—" }}</span></slot
        ></template
      >
    </ElTableColumn>
  </ElTable>
  <div class="table-footer">
    <span>共 {{ total }} 条</span
    ><ElPagination
      :current-page="Number(page)"
      :page-size="Number(pageSize)"
      :page-sizes="[25, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next"
      @update:current-page="$emit('page', $event)"
      @update:page-size="$emit('page-size', $event)"
    />
  </div>
</template>
<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from "vue";
import { useAdminAuthStore } from "../stores/auth";
const props = defineProps({
  rows: Array,
  columns: Array,
  total: Number,
  page: [Number, String],
  pageSize: [Number, String],
  loading: Boolean,
  error: String,
  selectable: Boolean,
  expandable: Boolean,
  storageKey: String,
});
defineEmits(["retry", "sort-change", "selection-change", "page", "page-size"]);
const key = `gingtto-table:${useAdminAuthStore().user?.id}:${props.storageKey}`;
let settings = {};
try {
  settings = JSON.parse(localStorage.getItem(key) || "{}");
} catch {}
const density = ref(settings.density || "small"),
  visible = ref(settings.visible || props.columns.map((c) => c.prop)),
  table = ref();
const container = ref(),
  available = ref(1200);
let observer;
onMounted(() => {
  observer = new ResizeObserver(
    (entries) => (available.value = entries[0].contentRect.width),
  );
  observer.observe(container.value);
});
onBeforeUnmount(() => observer?.disconnect());
function columnWidth(column) {
  const base = shown.value.reduce((sum, c) => sum + (c.width || 100), 0);
  const width =
    available.value - (props.selectable ? 40 : 0) - (props.expandable ? 38 : 0);
  return Math.max(
    52,
    Math.floor((column.width || 100) * Math.min(1, width / base)),
  );
}
const shown = computed(() =>
  props.columns.filter((c) => visible.value.includes(c.prop)),
);
watch(
  [density, visible],
  () => {
    try {
      localStorage.setItem(
        key,
        JSON.stringify({ density: density.value, visible: visible.value }),
      );
    } catch {}
  },
  { deep: true },
);
defineExpose({
  clearSelection: () => table.value?.clearSelection(),
  toggleExpansion: (row) => table.value?.toggleRowExpansion(row),
});
</script>
