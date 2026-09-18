<template>
  <img :src="failed ? src : optimized" :alt="alt" loading="lazy" decoding="async" @error="failed = true" />
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { imageUrl } from '../utils/imageUrl'

const props = defineProps({ src: { type: String, default: '' }, alt: { type: String, default: '' }, width: { type: Number, default: 160 } })
const failed = ref(false)
const optimized = computed(() => imageUrl(props.src, props.width))
watch(() => [props.src, props.width], () => { failed.value = false })
</script>
