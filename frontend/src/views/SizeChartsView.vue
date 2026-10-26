<template>
  <PageHeader title="商品尺码表" eyebrow="PRODUCT / 尺码资料" description="每款一份尺寸资料，全部颜色共用；独立维护，不改变商品库存、价格或商城尺码表图片。">
    <MobileActionMenu><ElButton :disabled="!selected.length || exporting" @click="exportCharts(selected, 'maintenance')">导出维护表（{{ selected.length }}）</ElButton>
    <ElButton :disabled="!selected.length || exporting" @click="exportCharts(selected, 'english')">导出英文客户表</ElButton></MobileActionMenu>
    <ElButton type="primary" @click="openImport">导入覆盖</ElButton>
  </PageHeader>
  <section class="panel">
    <ResponsiveFilters :active="{category:categories.find(c => c.key === applied.category)?.label || applied.category,status:statuses[applied.status] || ''}" @remove="key => { filters[key] = ''; query(); }" @submit.prevent="query">
      <ElInput v-model="filters.keyword" placeholder="款号或商品标题" clearable />
      <ElSelect v-model="filters.category" placeholder="全部分类" clearable><ElOption v-for="c in categories" :key="c.key" :value="c.key" :label="c.label" /></ElSelect>
      <ElSelect v-model="filters.status" placeholder="全部填写状态" clearable><ElOption v-for="(v,k) in statuses" :key="k" :value="k" :label="v" /></ElSelect>
      <ElButton type="primary" native-type="submit">查询</ElButton><ElButton @click="reset">重置</ElButton>
    </ResponsiveFilters>
    <ElAlert v-if="listError" :title="listError" type="error" :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <AdaptiveTable ref="table" :data="rows" v-loading="loading" row-key="styleCode" @selection-change="selected = $event.map(r => r.styleCode)">
      <ElTableColumn type="selection" width="45" />
      <ElTableColumn label="代表图" width="88"><template #default="{row}"><ElImage v-if="row.image" :src="imageUrl(row.image,160)" fit="contain" style="width:54px;height:64px" /><span v-else class="muted">未设置</span></template></ElTableColumn>
      <ElTableColumn prop="styleCode" label="款号" width="180" />
      <ElTableColumn prop="title" label="商品标题" min-width="240" />
      <ElTableColumn label="填写状态" width="120"><template #default="{row}"><ElTag :type="row.status === 'complete' ? 'success' : 'info'">{{ statuses[row.status] }}</ElTag></template></ElTableColumn>
      <ElTableColumn prop="updatedDate" label="尺码更新时间" width="150"><template #default="{row}">{{ row.updatedDate || '未保存' }}</template></ElTableColumn>
      <ElTableColumn label="操作" width="130"><template #default="{row}"><ElButton link type="primary" @click="open(row.styleCode)">编辑</ElButton><ElButton link @click="open(row.styleCode, true)">预览</ElButton></template></ElTableColumn>
    </AdaptiveTable>
    <ElPagination v-model:current-page="page" :page-size="25" :total="total" layout="total, prev, pager, next" @current-change="load" class="section-gap" />
  </section>

  <component :is="readonly ? ElDialog : ElDrawer" v-model="editorOpen" :class="{ 'chart-preview-window': readonly }" :title="(readonly ? '预览尺码表 · ' : '编辑尺码表 · ') + (form?.styleCode || '')" size="min(1280px, 94vw)" width="min(1040px, 94vw)" :align-center="readonly" :before-close="closeEditor" :close-on-click-modal="false">
    <template v-if="form">
      <div class="chart-heading">
        <div><strong>{{ form.styleCode }}</strong><span class="muted">　尺码更新时间：{{ form.updatedDate || '未保存' }}</span></div>
        <div class="chart-preview-actions">
          <ElRadioGroup v-if="readonly" :model-value="previewUnit" @update:model-value="setPreviewUnit" aria-label="预览单位" title="仅切换预览单位，不修改已保存数据" :disabled="exporting"><ElRadioButton value="cm">cm</ElRadioButton><ElRadioButton value="in">in</ElRadioButton></ElRadioGroup>
          <ElRadioGroup v-model="mode"><ElRadioButton value="zh">中文完整表</ElRadioButton><ElRadioButton value="en">英文客户表</ElRadioButton></ElRadioGroup>
        </div>
      </div>
      <ElAlert v-if="error" :title="error" type="error" :closable="false" class="section-gap"><ElButton @click="refresh">重新读取（先确认放弃修改）</ElButton></ElAlert>
      <template v-if="!readonly && mode === 'zh'">
        <ElForm label-position="top" class="section-gap">
          <div class="chart-form-grid">
            <ElFormItem label="商品标题"><ElInput v-model="form.title" maxlength="255" /></ElFormItem>
            <ElFormItem label="英文标题"><ElInput v-model="form.titleEn" maxlength="255" /></ElFormItem>
            <ElFormItem label="材质"><ElInput v-model="form.material" maxlength="255" /></ElFormItem>
            <ElFormItem label="英文材质"><ElInput v-model="form.materialEn" maxlength="255" /></ElFormItem>
          </div>
          <ElFormItem label="代表图（商品首图）">
            <ElImage v-if="form.image" :src="imageUrl(form.image,160)" fit="contain" class="chart-representative-image" />
            <span v-else class="muted">商品尚未设置图片</span>
          </ElFormItem>
        </ElForm>
        <div class="chart-heading"><h3>测量维度与数值</h3><div class="chart-unit-actions"><span>整款单位</span><ElSelect :model-value="form.unit" @update:model-value="unit" aria-label="整款单位" style="width:130px" :disabled="saving"><ElOption label="厘米 cm" value="cm" /><ElOption label="英寸 in" value="in" /></ElSelect><ElButton @click="addDimension" :disabled="form.dimensions.length >= 64">＋ 添加维度</ElButton></div></div>
        <p class="muted">整款统一 {{ form.unit }}；1 in = 2.54 cm，切换时自动换算，四舍五入保留两位小数，保存后生效。空白表示未填写，0 表示零。</p>
        <div class="chart-matrix-scroll">
          <table class="chart-matrix">
            <thead><tr><th>中文维度</th><th>English</th><th>单位</th><th>英文展示</th><th v-for="size in form.sizes" :key="size">{{ size }}</th><th>操作</th></tr></thead>
            <tbody><tr v-for="(d,i) in form.dimensions" :key="d.id">
              <td><ElInput v-model="d.name" :aria-label="`维度 ${i+1} 中文名称`" maxlength="80" /></td>
              <td><ElInput v-model="d.nameEn" :aria-label="`维度 ${i+1} 英文名称`" maxlength="80" /></td>
              <td>{{ form.unit }}</td>
              <td><ElCheckbox v-model="d.showEn" :aria-label="`${d.name} 英文展示`" /></td>
              <td v-for="size in form.sizes" :key="size"><ElInput v-model="form.values[d.id][size]" inputmode="decimal" :aria-label="`${d.name} ${size}`" placeholder="未填写" /></td>
              <td class="dimension-actions"><ElButton link :disabled="i === 0" title="上移" @click="move(i,-1)">↑</ElButton><ElButton link :disabled="i === form.dimensions.length-1" title="下移" @click="move(i,1)">↓</ElButton><ElButton link type="danger" @click="removeDimension(d)">删除</ElButton></td>
            </tr></tbody>
          </table>
        </div>
        <ElAlert v-if="!form.sizes.length" title="该款尚未配置真实尺码，请先在商品管理中配置。" type="warning" :closable="false" />
      </template>
      <template v-else>
        <ElAlert v-if="mode === 'en' && englishError" :title="englishError" type="warning" :closable="false" />
        <section class="chart-preview section-gap">
          <div class="chart-preview-summary">
            <ElImage v-if="form.image" :src="imageUrl(form.image,640)" :preview-src-list="[form.image]" preview-teleported fit="contain" class="chart-preview-image" />
            <div class="chart-preview-info">
            <h2>{{ mode === 'en' ? form.titleEn : form.title }}</h2>
            <dl class="chart-preview-meta">
              <div><dt>{{ mode === 'en' ? 'Style No.' : '款号' }}</dt><dd>{{ form.styleCode }}</dd></div>
              <div><dt>{{ mode === 'en' ? 'Material' : '材质' }}</dt><dd>{{ (mode === 'en' ? form.materialEn : form.material) || '—' }}</dd></div>
              <div><dt>{{ mode === 'en' ? 'Updated' : '更新日期' }}</dt><dd>{{ form.updatedDate || '—' }}</dd></div>
            </dl>
            </div>
          </div>
          <div class="chart-matrix-scroll"><table class="chart-matrix preview-matrix"><thead><tr><th>{{ mode === 'en' ? 'Measurement' : '测量维度' }}</th><th>{{ mode === 'en' ? 'Unit' : '单位' }}</th><th v-for="size in form.sizes" :key="size">{{ size }}</th></tr></thead><tbody><tr v-for="d in previewDimensions" :key="d.id"><td>{{ mode === 'en' ? d.nameEn : d.name }}</td><td>{{ d.unit }}</td><td v-for="size in form.sizes" :key="size">{{ display(previewForm.values[d.id][size]) }}</td></tr></tbody></table></div>
        </section>
        <p v-if="!readonly" class="muted">英文展示维度在中文维护表中勾选。隐藏不会删除尺寸数据。</p>
      </template>
    </template>
    <template #footer><div class="chart-heading"><span class="muted">{{ dirty ? '有未保存修改' : '' }}</span><div><ElButton @click="closeEditor()" :disabled="saving">关闭</ElButton><ElButton :loading="exporting" @click="exportCharts([form.styleCode],mode === 'en' ? 'english' : 'maintenance',readonly ? previewUnit : null)">导出当前版本</ElButton><ElButton v-if="!readonly" type="primary" :loading="saving" :disabled="!dirty || !form?.sizes.length" @click="submit">保存尺码表</ElButton></div></div></template>
  </component>

  <ElDialog v-model="importOpen" class="chart-import-window" title="导入商品尺码表" width="min(1000px, 94vw)" align-center :close-on-click-modal="false" :close-on-press-escape="!importBusy" :show-close="!importBusy">
    <ElAlert title="请选择完整维护表。可新增、删除、改名或调整测量维度行；删除行会删除对应维度，数值空白会清空原值。请保留表头、真实尺码列、款号和整款单位。英文客户表不支持导入。" type="warning" :closable="false" />
    <ElButton class="section-gap" :disabled="importBusy" @click="fileInput.click()">选择 .xlsx 文件</ElButton><span class="small-note">　{{ fileName }}　最多 10 MB／100 款</span>
    <input ref="fileInput" type="file" accept=".xlsx" hidden @change="upload" />
    <ElAlert v-if="importError" :title="importError" type="error" :closable="false" class="section-gap" />
    <template v-if="proposal">
      <p>完整款号 {{ proposal.styleCount }} 个 · 数值变更 {{ proposal.valueChangedCount }} 项 · 维度变更 {{ proposal.dimensionChangedCount }} 项 · <strong class="negative">删除维度 {{ proposal.removedDimensionCount }} 项／清空数值 {{ proposal.clearCount }} 项</strong> · 错误 {{ proposal.errors.length }} 项</p>
      <AdaptiveTable :data="proposal.errors" v-if="proposal.errors.length" max-height="180"><ElTableColumn prop="sheet" label="工作表" /><ElTableColumn prop="message" label="错误" /></AdaptiveTable>
      <template v-if="proposal.dimensionRows.length">
        <h3>维度变更</h3>
        <AdaptiveTable :data="proposal.dimensionRows" max-height="240" aria-label="维度变更预览"><ElTableColumn prop="styleCode" label="款号" width="120" /><ElTableColumn label="操作" width="85"><template #default="{row}"><span :class="{negative:row.kind==='remove'}">{{ row.action }}</span></template></ElTableColumn><ElTableColumn prop="old" label="原维度／顺序"><template #default="{row}">{{ row.old || '—' }}</template></ElTableColumn><ElTableColumn prop="new" label="新维度／顺序"><template #default="{row}">{{ row.new || '删除' }}</template></ElTableColumn><ElTableColumn label="说明" width="170"><template #default="{row}">{{ row.kind==='remove' ? `已填 ${row.filledCount} 项，历史保留` : row.kind==='add' ? '新维度默认在英文版展示' : '原英文展示设置保留' }}</template></ElTableColumn></AdaptiveTable>
      </template>
      <template v-if="proposal.rows.length"><h3>数值变更</h3><AdaptiveTable :data="proposal.rows" max-height="320"><ElTableColumn prop="styleCode" label="款号" /><ElTableColumn prop="dimension" label="维度" /><ElTableColumn prop="size" label="尺码" /><ElTableColumn prop="cell" label="位置" /><ElTableColumn prop="unit" label="保存单位" width="90" /><ElTableColumn label="原值"><template #default="{row}">{{ display(row.old) }}</template></ElTableColumn><ElTableColumn label="新值"><template #default="{row}"><span :class="{negative:row.cleared}">{{ row.cleared ? '清空' : display(row.new) }}</span></template></ElTableColumn></AdaptiveTable></template>
      <p v-if="!proposal.changedCount && !proposal.errors.length">维度与数值均未变化，不需要保存。</p>
    </template>
    <template #footer><ElButton :disabled="importBusy" @click="importOpen=false">取消</ElButton><ElButton type="primary" :loading="importBusy" :disabled="!proposal?.changedCount || !!proposal?.errors.length" @click="importConfirm">确认覆盖</ElButton></template>
  </ElDialog>
</template>

<script setup>
import AdaptiveTable from "../components/AdaptiveTable";
import ResponsiveFilters from "../components/ResponsiveFilters.vue";
import MobileActionMenu from "../components/MobileActionMenu.vue";
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElDialog, ElDrawer } from 'element-plus';
import 'element-plus/es/components/dialog/style/css';
import 'element-plus/es/components/drawer/style/css';
import PageHeader from '../components/PageHeader.vue';
import { api, save, download, confirm, notifyError, useDirty } from '../composables/workbench';
import { imageUrl } from '../utils/imageUrl';
import { changeChartUnit, previewChartInUnit } from '../utils/sizeChartUnits';
const rows=ref([]), categories=ref([]), page=ref(1), total=ref(0), selected=ref([]), table=ref();
const filters=reactive({keyword:'',category:'',status:''}); let applied={...filters};
const loading=ref(false),listError=ref(''),editorOpen=ref(false),readonly=ref(false),form=ref(null),error=ref(''),mode=ref('zh'),saving=ref(false),exporting=ref(false);
const previewUnit=ref('cm');
const statuses={empty:'未填写',partial:'部分填写',complete:'已填完整'};
const {dirty,markClean,canLeave}=useDirty(()=>editorOpen.value ? form.value : null);
let sequence=0, saveAttempt=null; const unitAnchors=new Map();
async function load(){const seq=++sequence;loading.value=true;listError.value='';try{const r=await api('size-charts?'+new URLSearchParams({...applied,page:page.value,pageSize:25}));if(seq!==sequence)return;rows.value=r.items;total.value=r.total;categories.value=r.categories;selected.value=[];table.value?.clearSelection();}catch(e){if(seq===sequence)listError.value=e.message;}finally{if(seq===sequence)loading.value=false;}}
function query(){applied={...filters};page.value=1;load();}
function reset(){Object.assign(filters,{keyword:'',category:'',status:''});query();}
async function open(code, preview=false){if(!(await canLeave()))return;try{const data=await api('size-charts/detail?'+new URLSearchParams({styleCode:code}));form.value=data;previewUnit.value=data.unit;unitAnchors.clear();readonly.value=preview;mode.value='zh';error.value='';editorOpen.value=true;saveAttempt=null;markClean();}catch(e){notifyError(e);}}
async function closeEditor(done){if(saving.value)return;if(await canLeave()){editorOpen.value=false;markClean();if(typeof done==='function')done();}}
async function refresh(){await open(form.value.styleCode,readonly.value);}
function addDimension(){const id=crypto.randomUUID();form.value.dimensions.push({id,name:'',nameEn:'',unit:form.value.unit,showEn:true});form.value.values[id]=Object.fromEntries(form.value.sizes.map(s=>[s,null]));}
async function removeDimension(d){if(form.value.dimensions.length===1){ElMessage.warning('至少保留一个维度');return;}const has=Object.values(form.value.values[d.id]).some(v=>v!==null&&v!=='');if(!(await confirm(has?'该维度有测量值，删除后不再展示，历史记录仍保留。确认删除？':'确认删除该维度？','删除维度')))return;form.value.dimensions=form.value.dimensions.filter(x=>x.id!==d.id);delete form.value.values[d.id];}
function move(i,step){const list=form.value.dimensions;[list[i],list[i+step]]=[list[i+step],list[i]];}
async function unit(value){if(value===form.value.unit)return;if(!(await confirm('整款所有维度将按 1 in = 2.54 cm 自动换算，四舍五入保留两位小数；保存后生效。','换算整款单位')))return;try{changeChartUnit(form.value,value,unitAnchors);}catch(e){notifyError(e);}}
const englishError=computed(()=>{if(!form.value)return '';const f=form.value;if(!f.titleEn||/[\u3400-\u9fff]/.test(f.titleEn))return '请填写不含中文的英文标题';if((f.material||f.materialEn)&&(!f.materialEn||/[\u3400-\u9fff]/.test(f.materialEn)))return '请填写不含中文的英文材质';const dims=f.dimensions.filter(d=>d.showEn);if(!dims.length)return '至少勾选一个英文展示维度';if(dims.some(d=>!d.nameEn||/[\u3400-\u9fff]/.test(d.nameEn)))return '请补全展示维度的英文名称';return '';});
function setPreviewUnit(value){try{previewChartInUnit(form.value,value);previewUnit.value=value;}catch(e){notifyError(e);}}
const previewForm=computed(()=>form.value && readonly.value ? previewChartInUnit(form.value,previewUnit.value) : form.value);
const previewDimensions=computed(()=>previewForm.value?.dimensions.filter(d=>mode.value!=='en'||d.showEn)||[]);
const display=v=>v==null||v===''?'—':Number.isFinite(Number(v))?Number(v).toFixed(2):v;
async function submit(){if(saving.value)return;saving.value=true;error.value='';try{const serialized=JSON.stringify(form.value);if(saveAttempt?.serialized!==serialized)saveAttempt={serialized,requestId:crypto.randomUUID()};const r=await save('size-charts/save',{requestId:saveAttempt.requestId,changes:[form.value]},'POST');form.value=r.items[0];unitAnchors.clear();markClean();saveAttempt=null;ElMessage.success(r.updated.length?'尺码表已保存':'数值未变化');await load();}catch(e){error.value=e.message;}finally{saving.value=false;}}
async function exportCharts(codes,version,unit){if(exporting.value)return;if(dirty.value){ElMessage.warning('请先保存或撤销页面修改，导出仅包含已保存数据');return;}exporting.value=true;try{await download('size-charts/export',version==='english'?'size-charts-english.xlsx':'商品尺码表.xlsx',{method:'POST',body:JSON.stringify({styleCodes:codes,mode:version,...(unit?{unit}:{})}),headers:{'Content-Type':'application/json'}});}catch(e){notifyError(e);}finally{exporting.value=false;}}
const importOpen=ref(false),importBusy=ref(false),fileInput=ref(),fileName=ref(''),proposal=ref(null),importError=ref('');let importId='';
function openImport(){if(dirty.value){ElMessage.warning('请先保存或撤销页面修改，再导入尺码表');return;}proposal.value=null;fileName.value='';importError.value='';importOpen.value=true;}
async function upload(event){const f=event.target.files[0];event.target.value='';if(!f||importBusy.value)return;fileName.value=f.name;proposal.value=null;importError.value='';if(f.size>10*1024*1024){importError.value='文件不能超过 10 MB';return;}importBusy.value=true;try{const body=new FormData();body.append('file',f);proposal.value=await api('size-charts/import/preview',{method:'POST',body});importId=crypto.randomUUID();}catch(e){importError.value=e.message;}finally{importBusy.value=false;}}
async function importConfirm(){if(importBusy.value)return;if(!(await confirm(`将更新 ${proposal.value.dimensionChangedCount} 项维度和 ${proposal.value.valueChangedCount} 项数值，其中删除 ${proposal.value.removedDimensionCount} 个维度、清空 ${proposal.value.clearCount} 项原值。确认保存？`,'确认导入覆盖')))return;importBusy.value=true;importError.value='';try{await save('size-charts/import/confirm',{requestId:importId,proposal:proposal.value.proposal,previewToken:proposal.value.previewToken},'POST');ElMessage.success('尺码表已更新');importOpen.value=false;if(editorOpen.value)await open(form.value.styleCode,readonly.value);await load();}catch(e){importError.value=e.message;}finally{importBusy.value=false;}}
onMounted(()=>{markClean();load();});
</script>

<style scoped>
.chart-preview-actions{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap}
.chart-unit-actions{display:flex;align-items:center;gap:12px}.chart-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.chart-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 20px}.chart-representative-image{width:86px;height:110px;border:1px solid #e4eaf3;border-radius:6px}.chart-matrix-scroll{max-width:100%;overflow-x:auto;border:1px solid #e4eaf3;border-radius:8px}.chart-matrix{width:100%;border-collapse:collapse;font-size:12px;white-space:normal}.chart-matrix th{background:#f4f7fc;font-weight:500;color:#64748b}.chart-matrix th,.chart-matrix td{padding:10px;border-bottom:1px solid #e4eaf3;text-align:center;min-width:100px}.chart-matrix td:first-child{min-width:140px}.chart-matrix td:nth-child(2){min-width:170px}.chart-matrix .dimension-actions{white-space:nowrap;min-width:100px}.chart-preview{display:grid;gap:16px;min-width:0}
.chart-preview-summary{display:flex;align-items:center;gap:18px;min-width:0;padding:14px 16px;background:#f7f9fc;border:1px solid #e4eaf3;border-radius:8px}
.chart-preview-info{min-width:0;flex:1}
.chart-preview-summary h2{margin:0 0 12px;font-size:18px;line-height:1.4;overflow-wrap:anywhere}
.chart-preview-meta{display:flex;flex-wrap:wrap;gap:8px 24px;margin:0;font-size:12px;line-height:1.5}
.chart-preview-meta>div{display:flex;gap:8px;min-width:0}
.chart-preview-meta dt{color:#64748b;flex-shrink:0}
.chart-preview-meta dd{margin:0;overflow-wrap:anywhere}
.chart-preview-image{display:block;flex:0 0 88px;width:88px;height:88px;border-radius:6px}
.chart-preview>.chart-matrix-scroll{min-width:0}
.chart-preview .preview-matrix th,.chart-preview .preview-matrix td{padding:8px 10px;min-width:64px}
.chart-preview .preview-matrix th:first-child,.chart-preview .preview-matrix td:first-child{min-width:160px;text-align:left;padding-left:16px}
.preview-matrix td:nth-child(2){min-width:80px}.negative{color:#d33}
</style>



<style>
.chart-preview-window.el-dialog{padding:20px;max-height:calc(100dvh - 40px);display:flex;flex-direction:column;border-radius:12px}
.chart-preview-window .el-dialog__header{padding:0;height:12px;flex-shrink:0}
.chart-preview-window .el-dialog__title{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
.chart-preview-window .el-dialog__headerbtn{top:4px;right:4px;width:32px;height:32px}
.chart-preview-window .el-dialog__body{padding:4px 0 0;overflow:auto;min-height:0}
.chart-preview-window .el-dialog__footer{padding:14px 0 0;margin-top:16px;border-top:1px solid #e4eaf3;flex-shrink:0}
.chart-import-window.el-dialog{max-height:calc(100dvh - 40px);display:flex;flex-direction:column}
.chart-import-window .el-dialog__header,.chart-import-window .el-dialog__footer{flex-shrink:0}
.chart-import-window .el-dialog__body{min-height:0;overflow:auto}
</style>

<style scoped>
@media (max-width:767px) {
  .chart-form-grid { grid-template-columns:minmax(0,1fr); }
  .chart-heading { flex-direction:column; align-items:stretch; gap:12px; }
  .chart-unit-actions { flex-wrap:wrap; gap:8px; }
  .chart-preview-actions { justify-content:flex-start; }
  .chart-heading > div { min-width:0; }
}
</style>
<style>
@media (max-width:767px) {
  .chart-preview-window.el-dialog, .chart-import-window.el-dialog { max-height:var(--mobile-viewport-height,100dvh); padding:0; border-radius:0; }
  .chart-preview-window .el-dialog__header { height:auto; min-height:56px; padding:14px 54px 12px 16px; }
  .chart-preview-window .el-dialog__headerbtn { width:44px; height:44px; }
  .chart-preview-window .el-dialog__body { padding:16px; }
  .chart-preview-window .el-dialog__footer { padding:12px 16px calc(12px + env(safe-area-inset-bottom)); margin-top:0; }
}
</style>
