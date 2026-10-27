<template>
  <form class="filters responsive-filters" :class="{'is-expanded': expanded}" @submit.prevent="$emit('submit', $event)">
    <slot />
    <ElButton v-if="hasAdvanced" native-type="button" class="mobile-filter-toggle" :aria-label="expanded ? '收起筛选' : '更多筛选'" :aria-expanded="expanded" @click="expanded = !expanded"><ElIcon v-if="isPhone"><Filter/></ElIcon><template v-else>{{ expanded ? '收起筛选' : '更多筛选' }}{{ chips.length ? ` (${chips.length})` : '' }}</template></ElButton>
    <div v-if="chips.length" class="mobile-filter-chips">
      <ElTag v-for="chip in chips" :key="chip.key" closable @close="$emit('remove', chip.key)">{{ chip.label }}：{{ chip.value }}</ElTag>
    </div>
  </form>
</template>
<script setup>
import { computed, ref } from 'vue';
import { Filter } from '@element-plus/icons-vue';
import { useResponsive } from '../composables/responsive';
const { isPhone } = useResponsive();
const props = defineProps({ active: { type: Object, default: () => ({}) }, labels: { type: Object, default: () => ({}) }, hasAdvanced: { type: Boolean, default: true } });
defineEmits(['submit', 'remove']);
const expanded = ref(false);
const defaults = {category:'分类',categoryId:'分类',status:'状态',role:'角色',stock:'库存',country:'国家',salespersonId:'业务员',styleCode:'款号',style:'款号',dateFrom:'开始日期',dateTo:'结束日期',startDate:'开始日期',endDate:'结束日期',module:'模块',action:'操作',resource:'模块',actorId:'操作人'};
const values = {active:'启用',disabled:'停用',all:'全部',backordered:'欠货',available:'有可用现货',empty:'无可用现货',admin:'管理员',sales:'外贸部',finance:'财务部',warehouse:'仓库部',customer:'客户',pending_payment:'待付款',allocated:'已配货',paid:'已付款',shipped:'已发货',completed:'已完成',cancelled:'已取消'};
const chips = computed(() => Object.entries(props.active).filter(([key,value]) => (defaults[key] || props.labels[key]) && value !== '' && value != null && value !== 'all').map(([key,value]) => ({key,label:props.labels[key] || defaults[key],value:values[value] || value})));
</script>
