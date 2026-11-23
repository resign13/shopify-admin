<template>
  <ElDialog :model-value="open" :title="noteOnly ? '修改取消备注' : requiresApproval ? '申请取消订单' : '取消订单'" width="min(520px, 94vw)"
    append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!busy" :before-close="close">
    <template v-if="current">
      <p class="order-id">{{ current.orderNo }}</p>
      <p v-if="!noteOnly" class="small-note">{{ requiresApproval ? '提交后保持原订单状态和库存，审核通过后才取消；审核期间暂停修改和发货，可撤回申请。' : `${statusNames[current.status]} → 已取消；${cancellationStockNotice(current)}` }}</p>
      <ElForm label-position="top" @submit.prevent="submit">
        <ElFormItem :label="requiresApproval ? '申请原因（必填）' : '取消备注（选填）'">
          <ElInput v-model="note" type="textarea" :rows="4" maxlength="500" show-word-limit
            :aria-label="requiresApproval ? '申请原因（必填）' : '取消备注（选填）'" :disabled="busy" :placeholder="requiresApproval ? '请填写取消申请原因' : '填写取消原因，仅后台可见'" />
        </ElFormItem>
      </ElForm>
      <ElAlert v-if="error" :title="error" type="error" :closable="false">
        <ElButton v-if="conflict" link type="primary" :loading="busy" @click="refresh">刷新订单版本（保留备注）</ElButton>
      </ElAlert>
    </template>
    <template #footer>
      <ElButton :disabled="busy" @click="close()">返回</ElButton>
      <ElButton type="primary" :loading="busy" :disabled="!current || conflict || invalidState" @click="submit">
        {{ requiresApproval ? '提交取消申请' : noteOnly || current?.status === 'cancelled' ? '保存取消备注' : '确认取消订单' }}
      </ElButton>
    </template>
  </ElDialog>
</template>
<script setup>
import { errorMessage } from '../utils/adminErrors.js';
import { computed, ref, watch } from 'vue';
import { cancellationStockNotice } from '../utils/orderCancellation';
import { ElMessage } from 'element-plus';
import { api, save, confirm, statusNames } from '../composables/workbench';
const props = defineProps({ open: Boolean, order: Object, noteOnly: Boolean });
const emit = defineEmits(['update:open', 'saved']);
const current = ref(), note = ref(''), initial = ref(''), busy = ref(false), error = ref(''), conflict = ref(false);
const requiresApproval = computed(()=>!props.noteOnly && !!current.value?.cancelApprovalRequired);
const invalidState = computed(() => props.noteOnly && current.value?.status !== 'cancelled' || current.value?.cancelRequest?.state==='pending');
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
  } catch (e) { if (serial === generation) error.value = errorMessage(e); }
  finally { busy.value = false; }
}
async function submit() {
  if (busy.value || !current.value || conflict.value || invalidState.value) return;
  if(requiresApproval.value && !note.value.trim()){error.value='请填写申请原因';return;}
  busy.value = true; error.value = '';
  try {
    const { order } = requiresApproval.value ? await save(`orders/${current.value.id}/cancellation-requests`,{version:current.value.version,reason:note.value},'POST') : await save(`orders/${current.value.id}`, {
      version: current.value.version, cancelNote: note.value,
      ...(!props.noteOnly && current.value.status !== 'cancelled' ? { status: 'cancelled' } : {}),
    });
    initial.value = note.value;
    emit('saved', order); emit('update:open', false);
    ElMessage.success(requiresApproval.value ? '取消申请已提交，等待审核' : props.noteOnly ? '取消备注已保存' : '订单已取消');
  } catch (e) { error.value = errorMessage(e); conflict.value = e.status === 409; }
  finally { busy.value = false; }
}
</script>
<style scoped>
.order-id { margin-top:0; font-weight:600; overflow-wrap:anywhere; }
.small-note { line-height:1.6; }
</style>
