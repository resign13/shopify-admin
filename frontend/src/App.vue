<template>
  <ElConfigProvider :locale="zhCn" size="small"
    ><RouterView
  /></ElConfigProvider>
</template>
<script setup>
import { RouterView } from "vue-router";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import { onMounted, onBeforeUnmount } from 'vue';
let viewportFrame;
function updateViewport() {
  cancelAnimationFrame(viewportFrame);
  viewportFrame = requestAnimationFrame(() => {
    const viewport = window.visualViewport;
    const root = document.documentElement;
    root.style.setProperty('--mobile-viewport-height', `${viewport?.height || window.innerHeight}px`);
    root.style.setProperty('--mobile-viewport-top', `${viewport?.offsetTop || 0}px`);
  });
}
onMounted(() => {
  updateViewport();
  window.addEventListener('resize', updateViewport);
  window.visualViewport?.addEventListener('resize', updateViewport);
  window.visualViewport?.addEventListener('scroll', updateViewport);
});
onBeforeUnmount(() => {
  cancelAnimationFrame(viewportFrame);
  window.removeEventListener('resize', updateViewport);
  window.visualViewport?.removeEventListener('resize', updateViewport);
  window.visualViewport?.removeEventListener('scroll', updateViewport);
});
</script>
