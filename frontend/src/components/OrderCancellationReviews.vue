<template>
  <ElDrawer :model-value="open" title="取消审批" size="min(960px, 100vw)" append-to-body :close-on-click-modal="false" :before-close="close">
    <ElTabs v-model="tab" @tab-change="page=1;load()"><ElTabPane label="待审核" name="pending"/><ElTabPane label="已处理" name="processed"/></ElTabs>
    <ElAlert v-if="error" :title="error" type="error" :closable="false"><ElButton link @click="load">刷新</ElButton></ElAlert>
    <div v-loading="loading"><article v-for="item in rows" :key="item.id" class="review-row">
      <div><strong>{{ item.orderNo }}</strong><ElTag size="small" :type="item.state==='pending'?'warning':'info'">{{ cancellationStateNames[item.state] }}</ElTag></div>
      <small>{{ item.requesterKind==='store'?'商城客户':'后台账号' }} · {{ item.requesterName }} · {{ dateTime(item.createdAt) }}</small>
      <p>{{ item.reason }}</p><p v-if="item.reviewNote">审核意见：{{ item.reviewNote }}</p>
      <ElButton link type="primary" :disabled="busy" @click="select(item)">{{ item.state==='pending'?'查看并审核':'查看记录' }}</ElButton>
    </article><ElEmpty v-if="!loading && !rows.length" description="暂无申请" /></div>
    <ElPagination :current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" @current-change="page=$event;load()" />
    <ElDialog v-model="detailOpen" title="取消申请详情" width="min(760px,94vw)" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy" :before-close="closeDetail">
      <ElAlert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <div v-if="selected" v-loading="detailLoading">
        <h3>{{ selected.item.orderNo }} · {{ cancellationStateNames[selected.item.state] }}</h3>
        <p class="review-note">{{ selected.item.reason }}</p>
        <p v-if="selected.order">当前状态：{{ statusNames[selected.order.status] }} · {{ selected.order.itemCount }} 件
          <span v-if="!auth.isWarehouse"> · 总额 {{ money(selected.order.totalAmount,selected.order.currency) }}</span></p>
        <ul v-if="selected.order"><li v-for="(line,index) in selected.order.items" :key="index">{{ line.sku }} · {{ line.sizeCode }} × {{ line.quantity }}</li></ul>
        <ElAlert v-if="selected.item.state==='pending'" title="审核通过后取消订单，并按现有规则返还商品库存。" type="warning" :closable="false" />
        <ElInput v-if="selected.item.state==='pending'" v-model="reviewNote" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="审核意见" placeholder="审核意见；驳回时必填，将向申请人显示" :disabled="busy" />
        <p v-else class="review-note">{{ selected.item.reviewNote || '未填写审核意见' }}<br>{{ selected.item.reviewerName }} · {{ dateTime(selected.item.closedAt) }}</p>
      </div>
      <template #footer><ElButton :disabled="busy" @click="closeDetail()">关闭</ElButton>
        <template v-if="selected?.item.state==='pending' && auth.canApproveCancellation"><ElButton type="danger" :loading="busy" @click="decide('reject')">驳回</ElButton><ElButton type="primary" :loading="busy" @click="decide('approve')">审核通过并取消</ElButton></template>
      </template>
    </ElDialog>
  </ElDrawer>
</template>
<script setup>
import {ref,watch} from 'vue';
import {ElMessage} from 'element-plus';
import {api,save,confirm,dateTime,money,statusNames} from '../composables/workbench';
import {useAdminAuthStore} from '../stores/auth';
import {errorMessage} from '../utils/adminErrors';
import {cancellationStateNames} from '../utils/orderCancellation';
const props=defineProps({open:Boolean});const emit=defineEmits(['update:open','changed','count']);const auth=useAdminAuthStore();
const tab=ref('pending'),page=ref(1),total=ref(0),rows=ref([]),loading=ref(false),error=ref(''),busy=ref(false);
const selected=ref(null),detailOpen=ref(false),detailLoading=ref(false),detailError=ref(''),reviewNote=ref('');let serial=0,detailSerial=0;
async function load(){
  const current=++serial;loading.value=true;error.value='';
  try{const r=await api('orders/cancellation-requests?'+new URLSearchParams({state:tab.value,page:page.value}));if(current!==serial)return;rows.value=r.items;total.value=r.total;emit('count',r.pendingCount);}
  catch(e){if(current===serial){rows.value=[];error.value=errorMessage(e);}}finally{if(current===serial)loading.value=false;}
}
async function select(item){
  const current=++detailSerial;
  selected.value=null;detailOpen.value=true;detailLoading.value=true;detailError.value='';reviewNote.value='';
  try{const result=await api(`orders/cancellation-requests/${item.id}`);if(current===detailSerial)selected.value=result;}catch(e){if(current===detailSerial)detailError.value=errorMessage(e);}finally{if(current===detailSerial)detailLoading.value=false;}
}
async function decide(action){
  if(busy.value || !selected.value)return;
  if(action==='reject'&&!reviewNote.value.trim()){detailError.value='请填写驳回原因';return;}
  if(!await confirm(action==='approve'?'确认审核通过并取消订单？商品库存按现有规则返还。':'确认驳回取消申请？订单状态和库存保持不变。'))return;
  busy.value=true;detailError.value='';
  try{await save(`orders/cancellation-requests/${selected.value.item.id}/${action}`,{version:selected.value.item.version,reviewNote:reviewNote.value},'POST');ElMessage.success(action==='approve'?'审核通过，订单已取消':'申请已驳回');detailOpen.value=false;await load();emit('changed');}
  catch(e){detailError.value=errorMessage(e);}finally{busy.value=false;}
}
function close(done){if(busy.value)return;emit('update:open',false);if(typeof done==='function')done();}
function closeDetail(done){if(busy.value)return;++detailSerial;detailOpen.value=false;if(typeof done==='function')done();}
watch(()=>props.open,value=>{if(value){page.value=1;load();}else ++serial;});
</script>
<style scoped>
.review-row{padding:16px 0;border-bottom:1px solid #e7edf5;overflow-wrap:anywhere}.review-row>div{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.review-row small{display:block;color:#64748b;margin-top:7px}.review-row p,.review-note{white-space:pre-wrap;overflow-wrap:anywhere}.el-textarea{margin-top:14px}
</style>
