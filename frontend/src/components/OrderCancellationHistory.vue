<template>
  <section v-if="order?.cancelRequest" class="cancellation-summary" data-testid="cancellation-summary">
    <ElTag size="small" :type="order.cancelRequest.state==='pending'?'warning':'info'">{{ cancellationStateNames[order.cancelRequest.state] }}</ElTag>
    <span v-if="order.cancelRequest.state==='pending'">审核期间暂停修改和发货</span>
    <span v-else-if="order.cancelRequest.state==='rejected'">{{ order.cancelRequest.reviewNote }}</span>
    <ElButton v-if="order.cancelRequest.canWithdraw" link type="primary" :loading="busy" @click="withdraw">撤回申请</ElButton>
    <ElButton link @click="showHistory">申请记录</ElButton>
    <ElDialog v-model="historyOpen" title="取消申请记录" width="min(620px, 94vw)" append-to-body>
      <ElAlert v-if="error" :title="error" type="error" :closable="false" />
      <div v-loading="loading"><article v-for="row in rows" :key="row.id" class="cancellation-record">
        <strong>{{ cancellationStateNames[row.state] }}</strong> · {{ row.requesterName }} · {{ dateTime(row.createdAt) }}
        <p>{{ row.reason }}</p><p v-if="row.reviewNote">审核意见：{{ row.reviewNote }}</p>
        <small v-if="row.closedAt">{{ row.reviewerName || row.requesterName }} · {{ dateTime(row.closedAt) }}</small>
      </article></div>
    </ElDialog>
  </section>
</template>
<script setup>
import {ref,watch} from 'vue';
import {ElMessage} from 'element-plus';
import {api,save,confirm,dateTime} from '../composables/workbench';
import {errorMessage} from '../utils/adminErrors';
import {cancellationStateNames} from '../utils/orderCancellation';
const props=defineProps({order:Object});const emit=defineEmits(['changed']);
const historyOpen=ref(false),rows=ref([]),loading=ref(false),busy=ref(false),error=ref('');
watch(()=>props.order?.id,()=>{historyOpen.value=false;rows.value=[];error.value='';});
async function showHistory(){
  historyOpen.value=true;loading.value=true;error.value='';rows.value=[];
  const id=props.order.id;
  try{const result=await api(`orders/${id}/cancellation-requests`);if(props.order?.id===id)rows.value=result.items;}
  catch(e){error.value=errorMessage(e);}finally{loading.value=false;}
}
async function withdraw(){
  if(busy.value || !await confirm('撤回取消申请？订单保持原状态，随后可继续编辑。'))return;
  busy.value=true;
  try{await save(`orders/cancellation-requests/${props.order.cancelRequest.id}/withdraw`,{version:props.order.cancelRequest.version},'POST');ElMessage.success('取消申请已撤回');emit('changed');}
  catch(e){ElMessage.error(errorMessage(e));}finally{busy.value=false;}
}
</script>
<style scoped>
.cancellation-summary{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:#64748b;margin:10px 0}.cancellation-record{padding:14px 0;border-bottom:1px solid #e7edf5;overflow-wrap:anywhere}.cancellation-record p{white-space:pre-wrap;margin:8px 0}.cancellation-record small{color:#64748b}
</style>
