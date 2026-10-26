<template>
  <ElDialog :model-value="modelValue" title="导入成本表" width="min(820px, 95vw)" class="cost-import-dialog" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @update:model-value="close">
    <p class="cost-import-help">仅填写系统成本表的“新成本”列。留空不修改，0 为零成本；预览确认后才保存，不支持通过 Excel 清空成本。</p>
    <div class="cost-import-file">
      <input ref="input" type="file" accept=".xlsx" hidden aria-label="选择成本表文件" @change="selectFile" />
      <ElButton :disabled="busy" @click="input.click()">{{ file?'更换文件':'选择成本表' }}</ElButton>
      <span class="cost-import-filename" :title="file?.name">{{ file?.name||'系统导出的 .xlsx，最多 2,000 款、10 MB' }}</span>
      <ElButton v-if="file" :loading="loading" :disabled="saving" @click="loadPreview">重新预览</ElButton>
    </div>
    <ElAlert v-if="error" class="cost-import-error" :title="error" type="error" :closable="false" />
    <div v-if="preview" class="cost-import-summary" role="status">
      <span>待更新 <b>{{ preview.summary.update }}</b></span><span>留空跳过 {{ preview.summary.blank }}</span><span>相同跳过 {{ preview.summary.same }}</span><span :class="{'cost-import-danger':preview.summary.error}">错误 {{ preview.summary.error }}</span>
    </div>
    <p v-if="preview?.summary.error" class="cost-import-danger cost-import-help">存在错误，本批不会保存。请按行号核对文件；版本冲突需重新导出。</p>
    <p v-else-if="canSave" class="cost-import-help">首次成本将补算此前 {{ preview.affectedOrders }} 个有效订单；后续修改仅用于保存后的新订单。保存时间由服务器统一确定，历史记录保留。</p>
    <div v-loading="loading" class="cost-import-table-scroll">
      <AdaptiveTable v-if="preview" :data="preview.rows" size="small" max-height="48vh" class="cost-import-table" :row-class-name="({row})=>row.status==='error'?'cost-import-error-row':''">
        <ElTableColumn label="款号" min-width="150"><template #default="{row}"><span>{{ row.styleCode||'未填写款号' }}</span><small class="cost-import-row-number">第 {{ row.rowNumber }} 行</small></template></ElTableColumn>
        <ElTableColumn label="原成本 CNY" width="120" align="right"><template #default="{row}">{{ row.oldCostCny??'未设置' }}</template></ElTableColumn>
        <ElTableColumn label="新成本 CNY" width="120" align="right"><template #default="{row}">{{ row.costCny??'—' }}</template></ElTableColumn>
        <ElTableColumn label="处理结果" min-width="200"><template #default="{row}"><span :class="{'cost-import-danger':row.status==='error'}">{{ row.message }}</span></template></ElTableColumn>
      </AdaptiveTable>
      <p v-else class="cost-import-empty">{{ loading?'正在校验成本表…':'选择文件后预览成本变化，不会立即写入。' }}</p>
    </div>
    <template #footer><ElButton :disabled="busy" @click="close(false)">取消</ElButton><ElButton type="primary" :disabled="!canSave||loading||stale" :loading="saving" @click="commit">确认保存</ElButton></template>
  </ElDialog>
</template>

<script setup>
import AdaptiveTable from "./AdaptiveTable";
import {computed,ref,watch} from 'vue';
import {ElMessage} from 'element-plus';
import {api,save} from '../composables/workbench';
const props=defineProps({modelValue:Boolean});
const emit=defineEmits(['update:modelValue','saved']);
const input=ref(null),file=ref(null),preview=ref(null),error=ref(''),loading=ref(false),saving=ref(false),stale=ref(false);
let pending=null;
const busy=computed(()=>loading.value||saving.value);
const canSave=computed(()=>Boolean(preview.value?.previewHash)&&preview.value.summary.error===0&&preview.value.summary.update>0);
watch(()=>props.modelValue,open=>{if(open){file.value=null;preview.value=null;error.value='';stale.value=false;pending=null;if(input.value)input.value.value='';}});
function close(value){if(!busy.value)emit('update:modelValue',value);}
async function selectFile(event){
  const selected=event.target.files?.[0];event.target.value='';if(!selected)return;
  file.value=selected;preview.value=null;pending=null;stale.value=false;error.value='';
  if(!selected.name.toLowerCase().endsWith('.xlsx')){error.value='请选择系统导出的 .xlsx 成本表';return;}
  if(selected.size>10*1024*1024){error.value='导入文件不能超过 10 MB';return;}
  await loadPreview();
}
async function loadPreview(){
  if(!file.value||busy.value)return;
  loading.value=true;error.value='';stale.value=true;pending=null;
  try{
    const body=new FormData();body.append('file',file.value);
    const data=await api('finance/costs/import/preview',{method:'POST',body});
    preview.value=data;stale.value=false;
    if(data.previewHash)pending={changes:data.changes.map(({styleCode,costCny,version})=>({styleCode,costCny,version})),previewHash:data.previewHash,requestId:crypto.randomUUID()};
  }catch(e){error.value=e.message;}finally{loading.value=false;}
}
async function commit(){
  if(!canSave.value||busy.value||stale.value||!pending)return;
  saving.value=true;error.value='';
  try{
    const data=await save('finance/costs/save',pending,'POST');
    ElMessage.success(`已导入 ${data.saved} 款成本`);emit('update:modelValue',false);emit('saved');
  }catch(e){error.value=e.message;if(e.status)stale.value=true;}
  finally{saving.value=false;}
}
</script>

<style scoped>
.cost-import-help{font-size:12px;line-height:1.7;color:#718198;margin:0 0 12px}.cost-import-file{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}.cost-import-filename{font-size:12px;color:#61738a;overflow-wrap:anywhere;flex:1;min-width:120px}.cost-import-file :deep(.el-button+.el-button){margin-left:0}.cost-import-summary{display:flex;flex-wrap:wrap;gap:8px 20px;margin:16px 0 12px;font-size:12px;color:#61738a}.cost-import-summary b{color:#2563eb}.cost-import-danger{color:#dc2626}.cost-import-error{margin:12px 0}.cost-import-row-number{display:block;font-size:11px;color:#8996a7;margin-top:3px}.cost-import-table-scroll{overflow-x:auto;min-height:100px}.cost-import-table{font-size:12px}.cost-import-table :deep(.cell){overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.cost-import-table :deep(.cost-import-error-row){--el-table-tr-bg-color:#fff7f7}.cost-import-empty{padding:32px 0;text-align:center;color:#8996a7;font-size:12px}@media(max-width:600px){.cost-import-table{min-width:620px}.cost-import-file{gap:8px}.cost-import-filename{flex-basis:calc(100% - 115px)}}
</style>
