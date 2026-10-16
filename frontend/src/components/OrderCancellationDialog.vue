<template>
  <ElDialog :model-value="open" :title="noteOnly ? '修改取消备注' : '取消订单'" width="min(520px, 94vw)"
    append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!busy" :before-close="close">
    <template v-if="current">
      <p class="order-id">{{ current.orderNo }}</p>
      <p v-if="!noteOnly" class="small-note">{{ statusNames[current.status] }} → 已取消；商品库存按现有规则返还。</p>
      <ElForm label-position="top" @submit.prevent="submit">
        <ElFormItem label="取消备注（选填）">
          <ElInput v-model="note" type="textarea" :rows="4" maxlength="500" show-word-limit
            aria-label="取消备注（选填）" :disabled="busy" placeholder="填写取消原因，仅后台可见" />
        </ElFormItem>
      </ElForm>
      <ElAlert v-if="error" :title="error" type="error" :closable="false">
        <ElButton v-if="conflict" link type="primary" :loading="busy" @click="refresh">刷新订单版本（保留备注）</ElButton>
      </ElAlert>
    </template>
    <template #footer>
      <ElButton :disabled="busy" @click="close()">返回</ElButton>
      <ElButton type="primary" :loading="busy" :disabled="!current || conflict || invalidState" @click="submit">
        {{ noteOnly || current?.status === 'cancelled' ? '保存取消备注' : '确认取消订单' }}
      </ElButton>
    </template>
  </ElDialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { api, save, confirm, statusNames } from '../composables/workbench';
const props = defineProps({ open: Boolean, order: Object, noteOnly: Boolean });
const emit = defineEmits(['update:open', 'saved']);
const current = ref(), note = ref(''), initial = ref(''), busy = ref(false), error = ref(''), conflict = ref(false);
const invalidState = computed(() => props.noteOnly && current.value?.status !== 'cancelled');
let generation = 0;
watch(() => [props.open, props.order?.id], () => {
  generation++;
  if (!props.open) return;
  current.value = props.order ? { ...props.order } : null;
  initial.value = props.noteOnly ? props.order?.cancelNote || '' : '';
  note.value = initial.value;
  error.value = ''; conflict.value = false;
}, { immediate: true });
async function close(done) {
  if (busy.value) return;
  if (note.value !== initial.value && !(await confirm('放弃尚未保存的取消备注？'))) return;
  emit('update:open', false);
  if (typeof done === 'function') done();
}
async function refresh() {
  if (busy.value || !current.value) return;
  busy.value = true;
  const serial = generation;
  try {
    const latest = (await api(`orders/${current.value.id}`)).order;
    if (serial !== generation) return;
    current.value = latest; conflict.value = false;
    error.value = props.noteOnly && latest.status !== 'cancelled'
      ? '该订单已恢复，当前状态不适用取消备注。请返回查看订单。'
      : '已读取最新订单，输入的备注已保留；请核对状态并再次确认。';
  } catch (e) { if (serial === generation) error.value = e.message; }
  finally { busy.value = false; }
}
async function submit() {
  if (busy.value || !current.value || conflict.value || invalidState.value) return;
  busy.value = true; error.value = '';
  try {
    const { order } = await save(`orders/${current.value.id}`, {
      version: current.value.version, cancelNote: note.value,
      ...(!props.noteOnly && current.value.status !== 'cancelled' ? { status: 'cancelled' } : {}),
    });
    initial.value = note.value;
    emit('saved', order); emit('update:open', false);
    ElMessage.success(props.noteOnly ? '取消备注已保存' : '订单已取消');
  } catch (e) { error.value = e.message; conflict.value = e.status === 409; }
  finally { busy.value = false; }
}
</script>
<style scoped>
.order-id { margin-top:0; font-weight:600; overflow-wrap:anywhere; }
.small-note { line-height:1.6; }
</style>
