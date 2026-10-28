<template>
  <form class="goods-search mobile-query-bar" @submit.prevent="$emit('submit')">
    <ElInput :model-value="modelValue" :placeholder="placeholder" :aria-label="placeholder" clearable @update:model-value="$emit('update:modelValue', $event)" @clear="$emit('submit')"><template #prefix><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg></template></ElInput>
    <ElButton native-type="submit" type="primary">查询</ElButton>
    <ElButton v-if="filterable" class="goods-filter" aria-label="筛选" @click="$emit('filter')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/></svg><span v-if="active" class="filter-dot"/></ElButton>
  </form>
</template>
<script setup>
defineProps({ modelValue: String, placeholder: { type: String, default: '搜索' }, filterable: Boolean, active: Boolean });
defineEmits(['update:modelValue', 'submit', 'filter']);
</script>
<style scoped>
.goods-search{display:flex;gap:10px;margin:0 0 20px}.goods-search :deep(.el-input__wrapper){min-height:44px;border-radius:12px;background:#edf1f7;box-shadow:none;padding:0 12px}.goods-search :deep(.el-input__inner){font-size:13px;color:#182b49}.goods-search :deep(.el-input__inner::placeholder){font-size:12px;color:#9aa8bc}.goods-search svg{width:17px;height:17px;fill:none;stroke:#91a3bf;stroke-width:1.5}.goods-filter{position:relative;flex:0 0 44px;width:44px;height:44px;padding:10px;margin:0!important;border:1px solid #e4ebf6;border-radius:12px;color:#7990b3;background:#fff}.goods-filter svg circle{fill:#fff}.filter-dot{position:absolute;right:7px;top:7px;width:5px;height:5px;border-radius:50%;background:#2f69eb}
</style>
