<template>
  <div v-if="allowed" class="order-voice-reminder" aria-live="polite">
    <span class="voice-status" :class="{ 'is-active': ui.status === 'listening' }">{{ labels[ui.status] || '未开启' }}</span>
    <ElButton v-if="!ui.enabled || ['needs-sound','error','stopped','server-off'].includes(ui.status)"
      size="small" :disabled="!controller || ui.playing || !!unsupported" @click="controller?.enable()">
      {{ ui.enabled ? '启用声音／恢复监听' : '开启语音提醒' }}
    </ElButton>
    <ElButton v-if="ui.enabled" size="small" @click="controller?.disable()">关闭语音提醒</ElButton>
    <ElButton size="small" :disabled="!controller || ui.playing || !!unsupported" @click="controller?.test()">测试播报</ElButton>
    <ElButton v-if="ui.uncertainCount" size="small" type="warning" :disabled="ui.playing || ui.status === 'needs-sound'"
      @click="controller?.replay()">待核对 {{ ui.uncertainCount }} 笔 · 人工重播</ElButton>
    <span v-if="unsupported || ui.message" class="voice-message">{{ unsupported || ui.message }}</span>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, reactive, shallowRef, watch } from 'vue';
import { useAdminAuthStore } from '../stores/auth';
import { request } from '../api';
import recording from '../assets/new-order-zh-CN.wav';
import { createNotificationStorage } from '../notifications/storage';
import { createVoiceAudio } from '../notifications/audio';
import { OrderVoiceController, sessionKey } from '../notifications/controller';

const auth = useAdminAuthStore();
const allowed = computed(() => auth.isAuthenticated && auth.can('orders') && ['admin','sales','warehouse'].includes(auth.userRole));
const labels = { off: '未开启', 'needs-sound': '待启用声音', listening: '正常监听', reconnecting: '断线重连',
  error: '播放／存储异常', follower: '其他标签页负责播报', stopped: '监听已停止', 'server-off': '服务器未启用', unsupported: '浏览器能力不足' };
const ui = reactive({ status: 'off', enabled: false, playing: false, uncertainCount: 0, message: '' });
const unsupported = !window.isSecureContext ? '请通过 HTTPS 或本机地址开启提醒' :
  !navigator.locks || !window.indexedDB || !window.BroadcastChannel || !window.crypto?.subtle ?
    '当前浏览器缺少提醒所需能力，请使用新版 Chrome／Edge' : '';
const controller = shallowRef(null); let revision = 0;
const storage = unsupported ? null : createNotificationStorage();
watch(() => [auth.token, auth.user?.id, allowed.value], async ([token, userId, access], previous) => {
  const current = ++revision;
  const old = controller.value; controller.value = null;
  await old?.dispose(!!previous && (previous[0] !== token || !access));
  Object.assign(ui, { status: unsupported ? 'unsupported' : 'off', enabled: false, playing: false, uncertainCount: 0, message: '' });
  if (!access || unsupported) return;
  const key = await sessionKey(userId, token);
  if (current !== revision) return;
  controller.value = new OrderVoiceController({ key, storage, player: createVoiceAudio(recording),
    api: async (operation, body, signal) => { try { return await request(`/api/admin/order-notifications/${operation}`, {
      method: 'POST', body: JSON.stringify(body), signal, skipGlobalLoading: true,
      headers: { Authorization: `Bearer ${token}` },
    }); } catch (error) {
      if (error.status === 403) await auth.initialize();
      throw error;
    } }, onState: state => { if (current === revision) Object.assign(ui, state); },
  });
  controller.value.refresh().catch(error => controller.value?.fail(error));
}, { immediate: true });

async function tokenChanged(event) {
  if (event.key !== 'lumiere-admin-token' || event.newValue === auth.token) return;
  await controller.value?.dispose(true);
  auth.token = event.newValue || ''; auth.user = null;
  if (auth.token) await auth.initialize();
}
window.addEventListener('storage', tokenChanged);
onBeforeUnmount(() => { ++revision; controller.value?.dispose(false); window.removeEventListener('storage', tokenChanged); });
</script>
<style scoped>
.order-voice-reminder { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:6px; max-width:720px; margin-left:auto; margin-right:18px; }
.voice-status { color:#8b94a7; font-size:12px; }
.voice-status.is-active { color:#059669; }
.voice-message { flex-basis:100%; color:#64748b; text-align:right; font-size:12px; }
@media(max-width:1000px) { .order-voice-reminder { max-width:420px; margin-right:8px; } }
</style>
