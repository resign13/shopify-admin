<template>
  <article class="goods-card" :class="{ 'is-selected': selected, 'has-selection': selectable }">
    <ElCheckbox v-if="selectable" class="goods-card-check" :model-value="selected" :aria-label="`选择${eyebrow || title}`" @update:model-value="$emit('select', $event)" />
    <button class="goods-card-main" type="button" :disabled="disabled" @click="selectable ? $emit('select', !selected) : $emit('open')">
      <slot name="leading"><ProductImage v-if="image" :src="image" :alt="title" class="goods-card-image" /></slot>
      <span class="goods-card-copy"><small v-if="eyebrow">{{ eyebrow }}</small><strong>{{ title }}</strong><span v-if="subtitle">{{ subtitle }}</span><slot /></span>
      <slot name="badge" />
    </button>
    <div v-if="$slots.footer || $slots.actions" class="goods-card-footer"><div class="goods-card-footer-copy"><slot name="footer" /></div><slot name="actions" /></div>
  </article>
</template>
<script setup>
import ProductImage from '../ProductImage.vue';
defineProps({ title: String, eyebrow: String, subtitle: String, image: String, selected: Boolean, selectable: Boolean, disabled: Boolean });
defineEmits(['open', 'select']);
</script>
<style scoped>
.goods-card{position:relative;min-width:0;background:#fff;border:1px solid #e9edf4;border-radius:18px;overflow:hidden}.goods-card.is-selected{border-color:#a9c3fb;background:#fcfdff}.goods-card-main{display:flex;align-items:center;gap:13px;width:100%;min-width:0;padding:16px;border:0;background:none;text-align:left;color:#182b49;font:inherit;cursor:pointer}.goods-card-main:disabled{cursor:default}.goods-card-image{flex:0 0 64px;width:64px!important;height:78px!important;border-radius:12px;background:#f2f5fa}.goods-card-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:6px}.goods-card-copy>small{font-size:10px;letter-spacing:.035em;color:#8c9ab0;overflow-wrap:anywhere}.goods-card-copy>strong{font-size:14px;font-weight:650;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.goods-card-copy>span{font-size:11px;line-height:1.5;color:#8c9ab0}.goods-card-footer{display:flex;gap:8px;align-items:center;padding:0 16px 13px}.goods-card-footer-copy{display:flex;flex:1;min-width:0;align-items:center;justify-content:space-between;gap:10px;font-size:11px;color:#8c9ab0}.goods-card-footer :deep(.el-button){font-size:11px}.goods-card-footer :deep(.el-tag){font-size:10px}.goods-card-check{position:absolute;left:14px;top:31px;margin:0}.goods-card.has-selection .goods-card-main{padding-left:45px}.goods-card.has-selection .goods-card-footer{padding-left:45px}.goods-card-main:focus-visible{outline:2px solid #2f69eb;outline-offset:-3px;border-radius:17px}
</style>
