import { Comment, Fragment, defineComponent, h, nextTick, ref, shallowRef, watch } from 'vue';
import { ElTable, ElButton, ElCheckbox, ElEmpty, ElSelect, ElOption } from 'element-plus';
import 'element-plus/es/components/table/style/css';
import 'element-plus/es/components/checkbox/style/css';
import 'element-plus/es/components/button/style/css';
import 'element-plus/es/components/select/style/css';
import 'element-plus/es/components/empty/style/css';
import { useResponsive } from '../composables/responsive';

// Keep the existing declarative ElTableColumn slots as the single source of
// cells and permissions. Only the presentation changes on phones.
export function tableColumns(nodes) {
  return (nodes || []).flatMap(node => {
    if (!node || node.type === Comment) return [];
    if (node.type === Fragment) return tableColumns(node.children);
    if (node.type?.name === 'ElTableColumn') return [node];
    return [];
  });
}

export default defineComponent({
  name: 'AdaptiveTable', inheritAttrs: false,
  props: {
    data: { type: Array, default: () => [] },
    rowKey: [String, Function], expandRowKeys: Array,
    mobileCards: { type: Boolean, default: true },
  },
  emits: ['selection-change', 'expand-change', 'sort-change'],
  setup(props, { attrs, slots, emit, expose }) {
    const { isPhone } = useResponsive();
    const table = shallowRef();
    const selected = shallowRef(new Map());
    const expanded = ref([]);
    const sort = ref({ prop: '', order: null });
    let columns = [], restoring = false;
    const key = (row, index = props.data.indexOf(row)) => typeof props.rowKey === 'function'
      ? props.rowKey(row) : props.rowKey ? row[props.rowKey] : row.id ?? index;
    const selectionColumn = () => columns.find(c => c.props?.type === 'selection');
    const selectable = (row, index) => !selectionColumn()?.props?.selectable || selectionColumn().props.selectable(row, index);
    const selectionChanged = rows => {
      if (restoring) return;
      selected.value = new Map(rows.map(row => [key(row), row]));
      emit('selection-change', rows);
    };
    function toggleRowSelection(row, checked) {
      if (table.value && !isPhone.value) { table.value.toggleRowSelection(row, checked); return; }
      if (!selectable(row, props.data.indexOf(row))) return;
      const next = new Map(selected.value), id = key(row);
      if (checked ?? !next.has(id)) next.set(id, row); else next.delete(id);
      selected.value = next; emit('selection-change', [...next.values()]);
    }
    function clearSelection() {
      selected.value = new Map();
      if (table.value && !isPhone.value) table.value.clearSelection();
      else emit('selection-change', []);
    }
    function toggleRowExpansion(row, value) {
      if (table.value && !isPhone.value) { table.value.toggleRowExpansion(row, value); return; }
      const id = key(row), next = new Set(props.expandRowKeys || expanded.value);
      if (value ?? !next.has(id)) next.add(id); else next.delete(id);
      expanded.value = [...next];
      emit('expand-change', row, props.data.filter(r => next.has(key(r))));
    }
    async function restoreSelection(instance) {
      if (!instance) return;
      restoring = true;
      await nextTick();
      for (const row of selected.value.values()) instance.toggleRowSelection(row, true);
      restoring = false;
    }
    watch(table, restoreSelection);
    watch(() => props.data, rows => {
      const reserve = selectionColumn()?.props?.['reserve-selection'] ?? selectionColumn()?.props?.reserveSelection;
      const visible = new Map(rows.map((r, i) => [key(r, i), r]));
      const next = new Map([...selected.value].filter(([id]) => reserve || visible.has(id)).map(([id, row]) => [id, visible.get(id) || row]));
      if (next.size !== selected.value.size || [...next].some(([id, row]) => selected.value.get(id) !== row)) {
        selected.value = next; emit('selection-change', [...next.values()]);
      }
    });
    function changeSort(value) {
      if (sort.value.prop === value.prop && sort.value.order === value.order) return;
      sort.value = { prop: value.prop || '', order: value.order || null };
      emit('sort-change', sort.value);
    }
    expose({ clearSelection, toggleRowSelection, toggleRowExpansion,
      getSelectionRows: () => [...selected.value.values()], doLayout: () => table.value?.doLayout() });
    const cell = (column, row, index) => {
      if (column.children?.default) return column.children.default({ row, $index: index, column: column.props });
      const value = column.props?.prop?.split('.').reduce((v, k) => v?.[k], row);
      return column.props?.formatter ? column.props.formatter(row, column.props, value, index) : String(value ?? '—');
    };
    return () => {
      columns = tableColumns(slots.default?.());
      if (!isPhone.value || !props.mobileCards) return h(ElTable, {
        ...attrs, ref: table, data: props.data, rowKey: props.rowKey || key,
        expandRowKeys: columns.some(c => c.props?.type === 'expand') ? props.expandRowKeys || expanded.value : undefined,
        defaultSort: sort.value.prop ? sort.value : attrs['default-sort'],
        onSelectionChange: selectionChanged,
        onSortChange: changeSort,
        onExpandChange: (row, rows) => { expanded.value = rows.map(r => key(r)); emit('expand-change', row, rows); },
      }, slots);
      const fields = columns.filter(c => !['selection', 'expand'].includes(c.props?.type));
      const expand = columns.find(c => c.props?.type === 'expand');
      const actions = fields.filter(c => c.props?.prop === 'actions' || c.props?.label === '操作');
      const content = fields.filter(c => !actions.includes(c));
      const sortable = fields.filter(c => c.props?.sortable);
      const eligible = props.data.filter(selectable);
      const count = eligible.filter(r => selected.value.has(key(r))).length;
      const rowClass = attrs['row-class-name'] || attrs.rowClassName;
      return h('div', { class: ['mobile-table', attrs.class], style: attrs.style, 'data-testid': 'mobile-table' }, [
        !!(selectionColumn() || sortable.length) && h('div', { class: 'mobile-table-tools' }, [
          selectionColumn() && h(ElCheckbox, { modelValue: !!eligible.length && count === eligible.length,
            indeterminate: count > 0 && count < eligible.length, disabled: !eligible.length,
            'onUpdate:modelValue': value => { eligible.forEach(row => toggleRowSelection(row, value)); },
          }, () => '全选本页'),
          sortable.length > 0 && h(ElSelect, { modelValue: sort.value.prop, placeholder: '排序', 'aria-label': '列表排序',
            'onUpdate:modelValue': value => changeSort({ prop: value, order: value ? 'descending' : null }),
          }, () => [h(ElOption, { label: '默认排序', value: '' }), ...sortable.map(c => h(ElOption, { label: c.props.label, value: c.props.prop }))]),
          sort.value.prop && h(ElButton, { 'aria-label': '切换排序方向', onClick: () => changeSort({ prop: sort.value.prop, order: sort.value.order === 'ascending' ? 'descending' : 'ascending' }) }, () => sort.value.order === 'ascending' ? '升序 ↑' : '降序 ↓'),
        ]),
        !props.data.length && h(ElEmpty, { description: attrs['empty-text'] || attrs.emptyText || '暂无符合条件的数据' }),
        ...props.data.map((row, index) => h('article', {
          key: key(row, index), class: ['mobile-record', { 'has-selection': !!selectionColumn() }, typeof rowClass === 'function' ? rowClass({ row, rowIndex: index }) : rowClass],
        }, [
          selectionColumn() && h(ElCheckbox, { class: 'mobile-record-select', modelValue: selected.value.has(key(row, index)), disabled: !selectable(row, index),
            'aria-label': `选择第 ${index + 1} 项`, 'onUpdate:modelValue': v => toggleRowSelection(row, v) }, () => '选择'),
          slots['mobile-card'] ? slots['mobile-card']({ row, index, field: ({ name }) => {
            const column = fields.find(c => c.props?.prop === name);
            return column ? cell(column, row, index) : null;
          } }) : h('dl', { class: 'mobile-record-fields' }, content.map((column, i) => h('div', {
            key: column.key ?? column.props?.prop ?? column.props?.label ?? i,
            class: ['mobile-record-field', { 'is-primary': i === 0, 'is-wide': ['商品','商品 / SKU','登记数量 / 变化明细','变化明细','备注'].includes(column.props?.label) }],
          }, [h('dt', column.props?.label || ''), h('dd', cell(column, row, index))]))),
          actions.length > 0 && h('div', { class: 'mobile-record-actions' }, actions.map(c => cell(c, row, index))),
          expand && h(ElButton, { text: true, onClick: () => toggleRowExpansion(row) }, () => (props.expandRowKeys || expanded.value).includes(key(row, index)) ? '收起明细' : '展开明细'),
          expand && (props.expandRowKeys || expanded.value).includes(key(row, index)) && h('div', { class: 'mobile-record-expanded' }, cell(expand, row, index)),
        ])),
        slots.append?.(),
      ]);
    };
  },
});
