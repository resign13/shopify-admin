<template>
  <ElConfigProvider :locale="zhCn" size="small"
    ><RouterView
  /></ElConfigProvider>
</template>
<script setup>
import { RouterView } from "vue-router";
import zhCn from "element-plus/es/locale/lang/zh-cn";
</script>
