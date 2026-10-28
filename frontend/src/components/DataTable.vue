<template>
  <div ref="container" class="data-toolbar" :class="{ 'mobile-toolbar-hidden': isPhone && !mobileTools }">
    <span>{{ total }} 条记录</span>
    <div>
      <MobileActionMenu v-if="$slots.toolbar" label="列表操作"><slot name="toolbar" /></MobileActionMenu><ElPopover v-if="!isPhone" trigger="click" width="200"
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
  <AdaptiveTable
    ref="table"
    :class="{ 'selection-large': largeSelection }"
    v-loading="loading"
    :data="rows"
    row-key="id"
    :expand-row-keys="expandedKeys"
    :mobile-selection="mobileSelection"
    :mobile-actions="mobileActions"
    :mobile-tools="mobileTools"
    :sort-state="sortState"
    @expand-change="(row, rows) => $emit('expand-change', row, rows)"
    size="small"
    empty-text="暂无符合条件的数据"
    @sort-change="$emit('sort-change', $event)"
    @selection-change="$emit('selection-change', $event)"
  >
    <template v-if="$slots['mobile-card']" #mobile-card="scope"><slot name="mobile-card" v-bind="scope" /></template>
    <ElTableColumn v-if="expandable" type="expand" width="38"
      ><template #default="{ row }"
        ><slot name="expanded" :row="row" /></template
    ></ElTableColumn>
    <ElTableColumn
      v-if="selectable"
      type="selection"
      :reserve-selection="true"
      :width="largeSelection ? 64 : 40"
    />
    <ElTableColumn
      v-for="column in shown"
      :key="column.prop"
      :prop="column.prop"
      :label="column.label"
      :width="column.fixedWidth"
      :min-width="column.fixedWidth || columnWidth(column)"
      :sortable="column.sortable ? 'custom' : false"
      :align="column.numeric ? 'right' : 'left'"
    >
      <template #default="{ row }"
        ><slot :name="column.prop" :row="row"
          ><span class="cell-value">{{ row[column.prop] ?? "—" }}</span></slot
        ></template
      >
    </ElTableColumn>
  </AdaptiveTable>
  <div class="table-footer">
    <span>共 {{ total }} 条</span
    ><ElPagination
      :current-page="Number(page)"
      :page-size="Number(pageSize)"
      :page-sizes="[25, 50, 100]"
      :total="total"
      :pager-count="5"
      layout="sizes, prev, pager, next"
      @update:current-page="$emit('page', $event)"
      @update:page-size="$emit('page-size', $event)"
    />
  </div>
</template>
<script setup>
import AdaptiveTable from "./AdaptiveTable";
import MobileActionMenu from "./MobileActionMenu.vue";
import { computed, ref, watch, onMounted, onBeforeUnmount } from "vue";
import { useAdminAuthStore } from "../stores/auth";
import { useResponsive } from '../composables/responsive';
const { isPhone } = useResponsive();
const props = defineProps({
  rows: Array,
  columns: Array,
  total: Number,
  page: [Number, String],
  pageSize: [Number, String],
  loading: Boolean,
  error: String,
  selectable: Boolean,
  largeSelection: Boolean,
  expandable: Boolean,
  expandedKeys: Array,
  storageKey: String,
  mobileSelection: { type: Boolean, default: true },
  mobileActions: { type: Boolean, default: true },
  mobileTools: { type: Boolean, default: true },
  sortState: { type: Object, default: undefined },
});
defineEmits(["expand-change", "retry", "sort-change", "selection-change", "page", "page-size"]);
const key = `gingtto-table:${useAdminAuthStore().user?.id}:${props.storageKey}`;
let settings = {};
try {
  settings = JSON.parse(localStorage.getItem(key) || "{}");
} catch {}
const savedVisible = Array.isArray(settings.visible)
  ? settings.visible
  : props.columns.map((c) => c.prop);
const knownColumns = Array.isArray(settings.knownColumns)
  ? settings.knownColumns
  : savedVisible;
const visible = ref([
  ...new Set([
    ...savedVisible,
    ...props.columns
      .filter((c) => c.defaultVisible && !knownColumns.includes(c.prop))
      .map((c) => c.prop),
  ]),
]),
  table = ref();
const container = ref(),
  available = ref(1200);
let observer, resizeFrame = null, measuredWidth = available.value;
onMounted(() => {
  persistSettings();
  const width = container.value.getBoundingClientRect().width;
  if (width > 0) available.value = measuredWidth = width;
  observer = new ResizeObserver((entries) => {
    const width = entries[0].contentRect.width;
    // Phone toolbars are display:none. Keep the last real column width until
    // the desktop table returns, and write outside the observer delivery cycle.
    if (!(width > 0)) return;
    measuredWidth = width;
    if (width === available.value || resizeFrame !== null) return;
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = null;
      if (measuredWidth !== available.value) available.value = measuredWidth;
    });
  });
  observer.observe(container.value);
});
onBeforeUnmount(() => {
  observer?.disconnect();
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
});
function columnWidth(column) {
  const base = shown.value.reduce((sum, c) => sum + (c.width || 100), 0);
  const width =
    available.value - (props.selectable ? (props.largeSelection ? 64 : 40) : 0) - (props.expandable ? 38 : 0);
  return Math.max(
    column.minWidth || 52,
    Math.floor((column.width || 100) * Math.min(1, width / base)),
  );
}
const shown = computed(() =>
  props.columns.filter((c) => visible.value.includes(c.prop)),
);
function persistSettings() {
  try {
    localStorage.setItem(key, JSON.stringify({
      visible: visible.value,
      knownColumns: [...new Set([...knownColumns, ...props.columns.map((c) => c.prop)])],
    }));
  } catch {}
}
watch(visible, persistSettings, { deep: true });
defineExpose({
  clearSelection: () => table.value?.clearSelection(),
  selectCurrentPage: () => props.rows.forEach((row) => table.value?.toggleRowSelection(row, true)),
  toggleExpansion: (row) => table.value?.toggleRowExpansion(row),
});
</script>

<style scoped>
.selection-large :deep(.el-table-column--selection .cell) {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 0;
}
.selection-large :deep(.el-table-column--selection .el-checkbox) {
  --el-checkbox-input-height: 22px;
  --el-checkbox-input-width: 22px;
  width: 44px;
  height: 44px;
  margin: 0;
  justify-content: center;
}
.selection-large :deep(.el-table-column--selection .el-checkbox__inner) {
  width: 22px;
  height: 22px;
  border-radius: 4px;
}
.selection-large :deep(.el-table-column--selection .el-checkbox__inner::after) {
  width: 6px;
  height: 11px;
}
.selection-large :deep(.el-table-column--selection .is-indeterminate .el-checkbox__inner::before) {
  width: 12px;
}
</style>
