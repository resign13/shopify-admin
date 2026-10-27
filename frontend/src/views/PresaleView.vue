<template>
  <PageHeader title="预售管理" mobile-title="预售选品" :mobile-description="`${draft.styleCodes.length} 个完整款号`" eyebrow="STOREFRONT / 商城运营" description="按整个款号展示全部颜色；仅展示选品，购买仍按可用现货执行。">
    <MobileActionMenu v-if="isPhone" icon-only label="选品操作"><ElButton :disabled="loading || saving" @click="pickerOpen = true">添加完整款号</ElButton><ElButton :disabled="loading || saving" @click="mobileReordering = !mobileReordering">{{ mobileReordering ? '完成顺序调整' : '调整展示顺序' }}</ElButton><ElButton :disabled="loading || saving" @click="resetOrder">恢复按上架时间排序</ElButton><ElButton :disabled="loading || saving" @click="reload">读取最新配置</ElButton><ElButton @click="mobileSummary = true">查看配置摘要</ElButton></MobileActionMenu>
    <template v-else><ElButton :disabled="loading || saving" @click="reload">读取最新配置</ElButton>
    <ElButton type="primary" :loading="saving" :disabled="loading || !dirty" @click="persist">保存修改</ElButton></template>
  </PageHeader>
  <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon class="section-gap" />
  <section v-if="isPhone" class="goods-list-panel" v-loading="loading"><div class="mobile-goods-heading"><small>{{ draft.sortMode === 'manual' ? '手动顺序' : '按首次上架时间，最新在前' }}</small><ElButton v-if="mobileReordering" text @click="mobileReordering = false">完成排序</ElButton><small v-else>按可用现货购买</small></div><ElEmpty v-if="!rows.length" description="尚未选择预售款号"/><div class="mobile-goods-list"><MobileGoodsCard v-for="(row,index) in rows" :key="row.styleCode" :title="row.styleCode" :subtitle="row.name" :disabled="!row.variants.length" @open="preview = row"><template #leading><span class="mobile-goods-position">{{ String(index+1).padStart(2,'0') }}</span></template><span>{{ row.missing ? '款号需要重新选择' : !row.active ? '整款已下架 · 配置保留' : `${row.variants.length} 个颜色 · ${row.sizeCodes.slice(0,4).join(' / ')}${row.sizeCodes.length > 4 ? '…' : ''}` }}</span><template #footer><template v-if="mobileReordering"><span>调整展示顺序</span><div class="mobile-goods-order-actions"><ElButton :disabled="index === 0 || saving" :aria-label="`上移 ${row.styleCode}`" @click="move(index,index-1)">↑</ElButton><ElButton :disabled="index === rows.length-1 || saving" :aria-label="`下移 ${row.styleCode}`" @click="move(index,index+1)">↓</ElButton></div></template><span v-else>{{ row.missing ? '待核对' : '全部颜色一起展示' }}</span></template><template v-if="!mobileReordering" #actions><MobileActionMenu label="更多"><ElButton :disabled="!row.variants.length" @click="preview = row">查看全部颜色</ElButton><ElButton type="danger" :disabled="saving" @click="remove(row.styleCode)">从选品中移除</ElButton></MobileActionMenu></template></MobileGoodsCard></div><div v-if="dirty" class="mobile-goods-selection"><span>有未保存修改</span><ElButton type="primary" :loading="saving" :disabled="loading" @click="persist">保存修改</ElButton></div></section>
  <section v-else class="panel presale-panel" v-loading="loading">
    <div class="presale-toolbar"><h3>预售款号 <small>共 {{ draft.styleCodes.length }} 款 · {{ draft.sortMode === 'manual' ? '手动排序' : '按首次上架时间，最新在前' }}</small></h3>
      <ElButton :disabled="loading || saving" @click="pickerOpen = true">＋ 添加款号</ElButton>
      <ElButton :disabled="loading || saving" @click="resetOrder">恢复按上架时间排序</ElButton>
    </div>
    <p class="muted">拖动或上下移动进入手动排序，可跨分类调整；保存后商城生效。新增款号在手动模式追加末尾。</p>
    <ElEmpty v-if="!rows.length" description="尚未选择预售款号" />
    <article v-for="(row, index) in rows" :key="row.styleCode" class="presale-row" :class="{ 'missing-style': row.missing }"
      draggable="true" @dragstart="dragging = index" @dragover.prevent @drop.prevent="move(dragging,index)" @dragend="dragging = -1">
      <span class="drag-grip" title="拖动排序">⠿</span><span class="row-number">{{ index + 1 }}</span>
      <div class="style-copy"><strong>{{ row.styleCode }}</strong><span>{{ row.name }}</span>
        <small v-if="row.missing">需要重新选择</small><small v-else-if="!row.active">整款已下架 · 商城暂不展示，配置保留</small>
        <small v-else>{{ row.variants.length }} 个颜色 · {{ row.sizeCodes.join(' / ') }} · 首次上架 {{ dateTime(row.firstListedAt) }}</small>
      </div>
      <ElButton :disabled="!row.variants.length" @click="preview = row">查看颜色</ElButton>
      <ElButton :disabled="index === 0 || saving" @click="move(index,index-1)">上移</ElButton>
      <ElButton :disabled="index === rows.length-1 || saving" @click="move(index,index+1)">下移</ElButton>
      <ElButton type="danger" text :disabled="saving" @click="remove(row.styleCode)">移除</ElButton>
    </article>
  </section>
  <ElDrawer v-if="isPhone" v-model="mobileSummary" title="预售配置摘要" size="100%"><ElDescriptions :column="1" border><ElDescriptionsItem label="完整款号">{{ draft.styleCodes.length }} 款</ElDescriptionsItem><ElDescriptionsItem label="展示顺序">{{ draft.sortMode === 'manual' ? '手动排序' : '首次上架时间，最新在前' }}</ElDescriptionsItem><ElDescriptionsItem label="保存状态">{{ dirty ? '有待保存修改' : '已保存' }}</ElDescriptionsItem></ElDescriptions><p class="mobile-goods-description section-gap">预售仅决定商城选品展示，购买仍按可用现货执行。整款下架后配置保留，商城暂不展示。</p></ElDrawer>
  <ElDialog v-model="pickerOpen" title="添加完整款号（全部颜色）" width="min(900px, 94vw)" :close-on-click-modal="false">
    <ElInput v-model="keyword" clearable placeholder="搜索款号、名称、颜色或 SKU" />
    <AdaptiveTable ref="pickerTable" :data="available" row-key="styleCode" height="420" @selection-change="picked = $event">
      <ElTableColumn type="selection" width="48" :selectable="row => !draft.styleCodes.includes(row.styleCode)" reserve-selection />
      <ElTableColumn prop="styleCode" label="款号" width="150" /><ElTableColumn prop="name" label="商品名称" />
      <ElTableColumn label="颜色" width="85"><template #default="{row}">{{ row.variants.length }}</template></ElTableColumn>
      <ElTableColumn label="状态" width="100"><template #default="{row}">{{ row.active ? '已上架' : '已下架' }}</template></ElTableColumn>
    </AdaptiveTable>
    <template #footer><ElButton @click="pickerOpen = false">取消</ElButton><ElButton type="primary" :disabled="!picked.length || saving" @click="addPicked">添加 {{ picked.length }} 款</ElButton></template>
  </ElDialog>
  <ElDialog :model-value="Boolean(preview)" title="全部颜色" width="min(820px, 94vw)" @close="preview = null">
    <div class="presale-colors"><div v-for="variant in preview?.variants || []" :key="variant.id">
      <ProductImage :src="variant.image" :alt="variant.colorName" /><strong>{{ variant.colorName || '未设置颜色' }}</strong>
      <small>{{ variant.sku }} · {{ variant.active ? '已上架' : '已下架' }}</small><small>{{ variant.sizes.join(' / ') }}</small>
    </div></div>
  </ElDialog>
</template>
<script setup>
import { useResponsive } from '../composables/responsive';
import MobileActionMenu from '../components/MobileActionMenu.vue';
import MobileGoodsCard from '../components/mobile-goods/MobileGoodsCard.vue';
import AdaptiveTable from "../components/AdaptiveTable";
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '../components/PageHeader.vue'
import ProductImage from '../components/ProductImage.vue'
import { api, save, useDirty, confirm, dateTime } from '../composables/workbench'
import { selectedStyles, moveStyle } from '../utils/presale'
const { isPhone } = useResponsive();
const mobileReordering=ref(false),mobileSummary=ref(false);
const items=ref([]), loading=ref(true), saving=ref(false), error=ref(''), pickerOpen=ref(false), keyword=ref(''), picked=ref([]), pickerTable=ref(), preview=ref(null), dragging=ref(-1)
const draft=reactive({styleCodes:[],sortMode:'automatic',version:0})
const {dirty,markClean}=useDirty(()=>({styleCodes:draft.styleCodes,sortMode:draft.sortMode}))
const rows=computed(()=>selectedStyles(draft.styleCodes,items.value,draft.sortMode))
const available=computed(()=>items.value.filter(row => [row.styleCode,row.name,...row.variants.map(v=>v.sku+' '+v.colorName)].join(' ').toLowerCase().includes(keyword.value.trim().toLowerCase())))
async function reload(){
  if(dirty.value && !(await confirm('读取最新配置将放弃当前草稿，是否继续？'))) return
  loading.value=true; error.value=''
  try{const data=await api('presale'); items.value=data.items; Object.assign(draft,data.config); markClean()}
  catch(e){error.value=e.message} finally{loading.value=false}
}
function addPicked(){
  if(saving.value) return
  draft.styleCodes=[...draft.styleCodes,...picked.value.map(r=>r.styleCode).filter(c=>!draft.styleCodes.includes(c))]
  pickerTable.value?.clearSelection(); picked.value=[]; pickerOpen.value=false
}
function remove(code){draft.styleCodes=draft.styleCodes.filter(c=>c!==code)}
function move(from,to){
  if(saving.value || loading.value || from<0 || from===to) return
  draft.styleCodes=moveStyle(rows.value.map(r=>r.styleCode),from,to); draft.sortMode='manual'
}
function resetOrder(){draft.sortMode='automatic'}
async function persist(){
  saving.value=true; error.value=''
  try{const result=await save('presale',JSON.parse(JSON.stringify(draft))); Object.assign(draft,result.config); markClean(); ElMessage.success('预售配置已保存')}
  catch(e){error.value=e.message} finally{saving.value=false}
}
onMounted(reload)
</script>
<style scoped>
.presale-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.presale-toolbar h3{margin-right:auto}.presale-toolbar small{font-size:12px;font-weight:400;color:#64748b;margin-left:12px}
.presale-row{display:flex;align-items:center;gap:12px;padding:18px 10px;border-top:1px solid #e6ebf3}.drag-grip{font-size:24px;cursor:grab;color:#94a3b8}.row-number{color:#94a3b8;min-width:24px}.style-copy{display:flex;flex:1;flex-direction:column;gap:6px;min-width:0}.style-copy small{color:#64748b}.missing-style{background:#fff8ed}.missing-style small{color:#b45309}.presale-colors{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.presale-colors>div{display:flex;flex-direction:column;gap:8px}.presale-colors :deep(img){width:100%;height:200px;object-fit:contain}.presale-colors small{color:#64748b}@media(max-width:800px){.presale-row{flex-wrap:wrap}.style-copy{flex-basis:65%}.presale-colors{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>

<style scoped src="../components/mobile-goods/mobileGoods.css"></style>
