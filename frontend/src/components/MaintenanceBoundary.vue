<template>
  <div class="maintenance-content" :inert="state.active" :aria-hidden="state.active ? 'true' : undefined"><slot /></div>
  <Teleport to="body">
    <div v-if="state.active" class="maintenance-cover" data-testid="maintenance-cover">
      <section ref="dialog" role="alertdialog" aria-modal="true" aria-labelledby="maintenance-title" aria-describedby="maintenance-description" tabindex="-1">
        <div class="maintenance-brand">GINGTTO · 管理后台</div>
        <h1 id="maintenance-title">{{ state.recovered ? '系统已恢复' : '系统正在维护' }}</h1>
        <p id="maintenance-description">{{ state.recovered ? '当前页面和未提交内容仍然保留，请核对后继续操作。' : '系统正在更新，请稍候。当前输入已保留，不会自动重试刚才的操作。' }}</p>
        <button v-if="state.recovered" type="button" @click="maintenance.continue()">继续操作</button>
        <button v-else type="button" :disabled="state.checking" @click="maintenance.check()">{{ state.checking ? '正在检查…' : '检查恢复情况' }}</button>
        <small v-if="!state.recovered">每 30 秒自动检查一次，无需刷新页面。</small>
      </section>
    </div>
  </Teleport>
</template>
<script setup>
import { nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { maintenance } from '../utils/maintenance.js';
const state = shallowRef(maintenance.state), dialog = ref();
let previousFocus;
const unsubscribe = maintenance.subscribe(value => { state.value = value; });
watch(() => state.value.active, async active => {
  if (active) { previousFocus = document.activeElement; await nextTick(); dialog.value?.focus(); }
  else { await nextTick(); if (previousFocus?.isConnected) previousFocus.focus(); }
}, { immediate: true });
onBeforeUnmount(unsubscribe);
</script>
<style scoped>
.maintenance-content{display:contents}
.maintenance-cover{position:fixed;inset:0;z-index:2147483640;display:grid;place-items:center;overflow:auto;padding:24px;background:#eff3f9f5;color:#14243c;font:16px/1.6 system-ui,-apple-system,"Microsoft YaHei",sans-serif}
.maintenance-cover section{box-sizing:border-box;width:min(100%,460px);padding:32px;border:1px solid #dce5f1;border-radius:22px;background:#fff;box-shadow:0 16px 48px #13264312;outline:none}
.maintenance-brand{font-size:12px;font-weight:750;letter-spacing:.1em;color:#30558a}
.maintenance-cover h1{margin:16px 0 12px;font-size:28px;line-height:1.3}.maintenance-cover p{margin:0 0 24px;color:#455c78}
.maintenance-cover button{min-height:44px;padding:0 18px;border:0;border-radius:10px;background:#2458d8;color:#fff;font:inherit;font-weight:650;cursor:pointer}.maintenance-cover button:disabled{opacity:.6;cursor:wait}.maintenance-cover button:focus-visible{outline:3px solid #172f60;outline-offset:3px}.maintenance-cover small{display:block;margin-top:16px;font-size:12px;color:#60748f}
</style>
