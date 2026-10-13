<template>
  <section class="finance-panel">
    <div class="finance-tabs">
      <div class="finance-tab-nav"><ElButton :class="{'finance-tab-active':tab==='report'}" :aria-pressed="tab==='report'" @click="changeTab('report')">成本统计</ElButton><ElButton :class="{'finance-tab-active':tab==='costs'}" :aria-pressed="tab==='costs'" @click="changeTab('costs')">商品成本</ElButton></div>
      <div class="finance-header-actions">
        <div class="finance-rate-control">
          <span class="finance-rate-label">汇率 <span>1 USD =</span></span>
          <!-- Refresh InputNumber's mount-time aria-disabled after loading the saved value. -->
          <ElInputNumber :key="rateLoading?'loading':'ready'" v-model="filters.exchangeRate" :precision="6" :step="0.000001" :min="0.000001" :max="9999999999.99" :controls="false" :disabled="rateLoading||rateSaving" placeholder="填写汇率" aria-label="核算汇率" @input="value=>filters.exchangeRate=value" />
          <span class="finance-rate-currency">CNY</span>
        </div>
        <ElButton v-if="!rateLoaded" :loading="rateLoading" @click="loadRate()">重新读取汇率</ElButton>
        <ElButton v-else :loading="rateSaving" :disabled="!rateValid||!rateDirty" :title="rateDirty?'保存公共汇率，所有财务账号共用':'当前公共汇率已保存'" @click="saveRate">保存汇率</ElButton>
        <ElButton v-if="tab==='report'" :disabled="!result||reportLoading||exporting||reportOutdated" :loading="exporting" :title="reportOutdated?'条件或汇率已修改，请重新查询后导出':'导出全部筛选结果，不限当前页'" @click="exportReport">导出 Excel</ElButton>
      </div>
    </div>
    <ElAlert v-if="rateError" :title="rateError" type="error" :closable="false" class="finance-gap" />
    <ElAlert v-if="error" :title="error" type="error" :closable="false" class="finance-gap" />
    <template v-if="tab==='costs'">
      <form class="finance-filters finance-cost-filters" @submit.prevent="loadCosts(1)">
        <label>款号<ElInput v-model="costQuery.styleCodes" placeholder="多个款号用逗号分隔" clearable /></label>
        <label>SKU / 颜色<ElInput v-model="costQuery.keyword" placeholder="输入 SKU 或颜色" clearable /></label>
        <label>分类<ElSelect v-model="costQuery.category" clearable placeholder="全部分类"><ElOption v-for="c in options.categories" :key="c.key" :label="c.key" :value="c.key" /></ElSelect></label>
        <label>成本生效日期<ElDatePicker v-model="costQuery.effectiveDate" type="date" value-format="YYYY-MM-DD" :clearable="false" aria-label="成本生效日期" /></label>
        <ElCheckbox v-model="costQuery.missingOnly">仅未设置成本</ElCheckbox>
        <ElButton native-type="submit" type="primary" :loading="costLoading">查询 / 应用日期</ElButton>
      </form>
      <div class="finance-toolbar">
        <ElCheckbox :model-value="allSelected" :indeterminate="selected.length>0&&!allSelected" @change="selectAll">当前页全选</ElCheckbox>
        <span>已选 {{ selected.length }} 个颜色 SKU</span>
        <ElSelect v-model="bulkSize" placeholder="全部尺码" aria-label="批量成本尺码" style="width:160px"><ElOption label="全部尺码" value=""/><ElOption v-for="s in selectedSizes" :key="s" :label="s" :value="s"/></ElSelect>
        <ElInputNumber v-model="bulkCost" :min="0" :max="9999999999.99" :precision="2" controls-position="right" placeholder="成本（元）" aria-label="批量成本金额" />
        <ElButton :disabled="!selected.length||saving||costLoading" @click="applyBatch">批量应用</ElButton>
        <ElButton :disabled="!clearableTargets.length||saving||costLoading" title="清空勾选颜色的所选尺码，保存后变为未设置，保留历史" @click="clearBatch">清空</ElButton>
        <ElButton type="primary" :disabled="!dirty||saving||costLoading" @click="previewSave">保存成本（{{ changes.length }}）</ElButton>
      </div>
      <div class="finance-cost-note">
        <span>正在编辑 {{ costEffective }} 生效的成本</span>
        <ElPopover trigger="click" placement="bottom-start" :width="340" popper-style="max-width:calc(100vw - 32px)">
          <template #reference><ElButton text circle aria-label="成本填写说明"><ElIcon><QuestionFilled /></ElIcon></ElButton></template>
          <div class="finance-cost-help">空白表示未设置，0 为明确零成本。批量应用、清空都只修改草稿，保存后生效。<br/>更改生效日期后，点击“查询 / 应用日期”才切换编辑日期。<br/>清空从所选生效日期起改为未设置，至下一条成本生效前有效；保留历史，不删除记录。补录以前日期会影响重新查询的历史报表。</div>
        </ElPopover>
      </div>
      <div v-loading="costLoading">
        <ElEmpty v-if="!groups.length&&!costLoading" description="暂无匹配商品" />
        <article v-for="group in groups" :key="group.styleCode" class="cost-group">
          <header>
            <ElCheckbox :model-value="group.variants.every(v=>selected.includes(v.id))" :indeterminate="group.variants.some(v=>selected.includes(v.id))&&!group.variants.every(v=>selected.includes(v.id))" @change="value=>selectGroup(group,value)"><strong>{{ group.styleCode }}</strong></ElCheckbox>
            <small>{{ group.variants.length }} 个颜色</small>
            <div class="cost-header-actions"><span class="cost-unit">成本 CNY / 件</span><ElButton text class="cost-history-button" :aria-label="`${group.styleCode} 成本历史`" @click="showHistory(group)">成本历史</ElButton><ElButton text circle :aria-label="`${group.styleCode} ${group.collapsed?'展开尺码':'收起尺码'}`" :aria-expanded="!group.collapsed" @click="group.collapsed=!group.collapsed"><ElIcon :class="{'cost-expanded':!group.collapsed}"><ArrowDown /></ElIcon></ElButton></div>
          </header>
          <div v-show="!group.collapsed" class="finance-scroll"><table class="cost-matrix"><thead><tr><th>颜色 / SKU</th><th v-for="s in group.sizes" :key="s">{{ s }}</th></tr></thead><tbody>
            <tr v-for="variant in group.variants" :key="variant.id"><td><ElCheckbox :model-value="selected.includes(variant.id)" :aria-label="`选择 ${variant.sku}`" @change="value=>selectVariant(variant.id,value)"/><div><strong>{{ variant.sku }}</strong><small>{{ variant.color }}{{ variant.active?'':' · 已下架' }}</small></div></td>
              <td v-for="size in group.sizes" :key="size" :class="{'cost-changed':isChanged(variant,size)}">
                <template v-if="findSize(variant,size)"><ElInputNumber v-model="findSize(variant,size).draftCost" :precision="2" :min="0" :max="9999999999.99" :controls="false" :disabled="saving" placeholder="未设置" :aria-label="`${variant.sku} ${size} 成本`"/></template><span v-else>—</span>
              </td>
            </tr>
          </tbody></table></div>
        </article>
      </div>
      <ElPagination :current-page="costPage" :page-size="12" :total="costTotal" layout="total, prev, pager, next" @current-change="loadCosts" />
    </template>
    <template v-else>
      <form class="finance-filters finance-report-filters" @submit.prevent="queryReport(1)">
        <label class="report-date-field">下单日期<ElDatePicker v-model="reportDates" value-format="YYYY-MM-DD" type="daterange" popper-class="finance-report-date-popper" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" aria-label="下单日期范围" /></label>
        <label>客户名称<ElInput v-model="filters.customerName" placeholder="订单客户名称" clearable /></label>
        <label>业务员<ElSelect v-model="filters.salespersonIds" multiple filterable collapse-tags clearable placeholder="全部业务员"><ElOption label="未分配" value="unassigned"/><ElOption v-for="p in options.salespeople" :key="p.id" :value="p.id" :label="p.name+(p.status==='active'?'':'（已停用）')"/></ElSelect></label>
        <label>款号<ElSelect v-model="filters.styleCodes" multiple filterable allow-create default-first-option collapse-tags clearable placeholder="多选或逗号输入"><ElOption v-for="s in options.styles" :key="s" :value="s" :label="s"/></ElSelect></label>
        <div class="report-filter-actions"><ElButton type="primary" native-type="submit" :loading="reportLoading" :disabled="rateLoading||!rateValid">查询核算</ElButton><ElButton text :aria-expanded="advancedOpen" aria-controls="finance-advanced-filters" @click="advancedOpen=!advancedOpen">更多筛选<span v-if="advancedCount" class="report-filter-count">{{ advancedCount }}</span><ElIcon :class="{'cost-expanded':advancedOpen}"><ArrowDown /></ElIcon></ElButton><ElButton text @click="resetReportFilters">重置</ElButton></div>
        <div v-show="advancedOpen" id="finance-advanced-filters" class="report-advanced-filters">
          <label>商城账号<ElSelect v-model="filters.customerId" filterable clearable placeholder="全部账号"><ElOption v-for="c in options.customers" :key="c.id" :value="c.id" :label="`${c.name} · ${c.company||c.id}`"/></ElSelect></label>
          <label>订单状态<ElSelect v-model="filters.statuses" multiple collapse-tags placeholder="全部有效状态"><ElOption v-for="s in activeStates" :key="s" :value="s" :label="statusNames[s]"/></ElSelect></label>
        </div>
      </form>
      <div v-if="reportChips.length" class="report-filter-chips" aria-label="已选筛选条件"><ElTag v-for="chip in reportChips" :key="chip.key" :data-filter="chip.key" closable effect="plain" :title="chip.label" @close="removeReportFilter(chip.key)">{{ chip.label }}</ElTag></div>
      <p v-if="reportOutdated" class="finance-rate-notice" role="status">{{ reportRateChanged?'汇率已修改，请重新查询后导出；下方结果仍使用汇率 '+result.filters.exchangeRate+'。':'条件已修改，查询后更新；下方仍为上次查询结果。' }}</p>
      <div class="report-context"><span>商品核算 · 不含运费及其他费用</span><ElPopover trigger="click" placement="bottom-start" :width="340" popper-style="max-width:calc(100vw - 32px)"><template #reference><ElButton text aria-label="核算说明"><ElIcon><QuestionFilled /></ElIcon>核算说明</ElButton></template><div class="finance-cost-help">按北京时间下单日期匹配历史人民币成本，销售额使用订单成交价格。不含运费、税费及其他费用；包含未付款订单时不代表实际回款。<br/>人民币折算逐订单商品行四舍五入至分后汇总。历史成本补录、订单修改会影响重新查询结果。<br/>导出包含全部筛选结果及完整字段，不限当前分页，使用导出时的数据库快照核算。</div></ElPopover></div>
      <template v-if="result">
        <div class="finance-summary" aria-label="核算金额汇总">
          <article><span>商品销售额 <small>USD</small></span><strong>${{ result.summary.salesUsd }}</strong><small>折合 ¥{{ result.summary.salesCny }} CNY</small></article>
          <article><span>商品成本 <small>CNY</small></span><strong :class="{'summary-incomplete':result.summary.totalCostCny===null}">{{ result.summary.totalCostCny===null?'待补全':'¥'+result.summary.totalCostCny }}</strong><small v-if="result.summary.totalCostCny===null">已知成本 ¥{{ result.summary.knownCostCny }}</small><small v-else>按下单日期匹配成本</small></article>
          <article><span>商品毛利 <small>CNY</small></span><strong :class="{'summary-incomplete':result.summary.profitCny===null}">{{ result.summary.profitCny===null?'待补全':'¥'+result.summary.profitCny }}</strong><small v-if="result.summary.profitCny===null">已设置部分 ¥{{ result.summary.knownProfitCny }}</small><small v-else>折合销售额 − 商品成本</small></article>
        </div>
        <div class="report-quantity-summary"><span>{{ result.summary.orderCount }} 个订单</span><span>{{ result.summary.quantity }} 件商品</span><span v-if="result.summary.missingQuantity" class="report-missing" role="status">{{ result.summary.missingQuantity }} 件成本未设置 · 完整成本与毛利待补全</span></div>
        <p class="report-result-meta">{{ result.filters.dateFrom }} — {{ result.filters.dateTo }}（北京时间） · 汇率 {{ result.filters.exchangeRate }} · 生成 {{ dateTime(result.generatedAt) }}</p>
        <div class="report-table-scroll"><ElTable class="finance-report-table" :data="result.items" v-loading="reportLoading" row-key="rowKey" size="small" empty-text="暂无符合条件的订单商品">
          <ElTableColumn type="expand" width="36"><template #default="{row}"><div class="line-detail"><div class="report-row-context"><span>折合销售额 <b>¥{{ row.salesCny }} CNY</b></span><span>单件成本区间 <b>{{ costRange(row) }} CNY</b></span></div><ElTable :data="row.lines" max-height="420" size="small">
            <ElTableColumn prop="orderNo" label="订单号" min-width="230"/><ElTableColumn prop="customerName" label="客户" min-width="130"/><ElTableColumn prop="accountName" label="商城账号" min-width="130"/><ElTableColumn prop="salesperson" label="业务员" width="100"/>
            <ElTableColumn label="下单时间" width="175"><template #default="{row:line}">{{ dateTime(line.createdAt) }}</template></ElTableColumn>
            <ElTableColumn prop="quantity" label="数量" width="70"/><ElTableColumn prop="salesUsd" label="销售额 USD" width="110" align="right"/>
            <ElTableColumn label="单件成本 CNY" width="120" align="right"><template #default="{row:line}">{{ line.unitCostCny??'未设置' }}</template></ElTableColumn><ElTableColumn prop="costEffectiveDate" label="成本生效日期" width="120"/>
            <ElTableColumn label="成本 CNY" width="110" align="right"><template #default="{row:line}">{{ line.costCny??'待补全' }}</template></ElTableColumn><ElTableColumn label="商品毛利 CNY" width="120" align="right"><template #default="{row:line}">{{ line.profitCny??'待补全' }}</template></ElTableColumn>
          </ElTable></div></template></ElTableColumn>
          <ElTableColumn prop="styleCode" label="款号" min-width="125"/><ElTableColumn prop="sku" label="颜色 SKU" min-width="160"/><ElTableColumn prop="sizeCode" label="尺码" width="90"/><ElTableColumn prop="quantity" label="销量" width="80"/>
          <ElTableColumn prop="salesUsd" label="销售额 USD" min-width="120" align="right"/>
          <ElTableColumn label="成本 CNY" min-width="135" align="right"><template #default="{row}">{{ row.totalCostCny??('已知 '+row.knownCostCny) }}<small v-if="row.missingQuantity" class="missing">{{ row.missingQuantity }} 件待补全</small></template></ElTableColumn>
          <ElTableColumn label="毛利 CNY" min-width="135" align="right"><template #default="{row}">{{ row.profitCny??'待补全' }}</template></ElTableColumn>
        </ElTable></div>
        <ElPagination class="finance-gap" :current-page="result.page" :page-size="25" :total="result.total" layout="total, prev, pager, next" @current-change="page=>queryReport(page,true)" />
      </template><div v-else class="report-empty" role="status">{{ rateValid?'选择条件后点击“查询核算”':'填写核算汇率，选择条件后查询' }}</div>
    </template>
  </section>
  <ElDialog v-model="previewOpen" title="确认成本生效及影响范围" width="min(1050px, 95vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="preview"><ElAlert :title="`${preview.effectiveDate} 起生效，影响 ${preview.affectedOrders} 个有效订单。${preview.changes.some(c=>c.costCny===null)?'其中 '+preview.changes.filter(c=>c.costCny===null).length+' 项清空为未设置，历史记录保留。':''}历史报表重新查询时会重新计算。`" type="warning" :closable="false"/>
      <ElTable :data="preview.changes" max-height="430"><ElTableColumn prop="sku" label="SKU" min-width="140"/><ElTableColumn prop="sizeCode" label="尺码" width="90"/><ElTableColumn label="原成本"><template #default="{row}">{{ row.oldCostCny??'未设置' }}</template></ElTableColumn><ElTableColumn label="新成本 CNY"><template #default="{row}">{{ row.costCny??'未设置' }}</template></ElTableColumn><ElTableColumn prop="effectiveDate" label="生效日"/><ElTableColumn label="截止日（不含）"><template #default="{row}">{{ row.untilExclusive||'长期有效' }}</template></ElTableColumn><ElTableColumn prop="affectedOrders" label="影响订单数"/></ElTable>
    </template><template #footer><ElButton :disabled="saving" @click="previewOpen=false">返回修改</ElButton><ElButton type="primary" :loading="saving" @click="commitCosts">确认保存</ElButton></template>
  </ElDialog>
  <ElDialog v-model="historyOpen" :title="historyTitle" width="min(1000px,95vw)" class="cost-history-dialog" @close="closeHistory">
    <div class="cost-history-filters">
      <label>颜色 SKU<ElSelect v-model="historyFilters.productId" filterable clearable placeholder="全部颜色 SKU" aria-label="历史颜色 SKU" @change="loadHistory(1)"><ElOption v-for="v in historyOptions.variants" :key="v.productId" :value="v.productId" :label="v.sku+(v.deleted?'（已删除）':v.color?' · '+v.color:'')"/></ElSelect></label>
      <label>尺码<ElSelect v-model="historyFilters.sizeCode" clearable placeholder="全部尺码" aria-label="历史尺码" @change="loadHistory(1)"><ElOption v-for="s in historyOptions.sizes" :key="s" :value="s" :label="s"/></ElSelect></label>
    </div>
    <div v-if="historyError" class="cost-history-error"><ElAlert :title="historyError" type="error" :closable="false"/><ElButton :loading="historyLoading" @click="loadHistory(historyPage)">重试</ElButton></div>
    <ElTable v-if="historyLoading||history?.items.length" :data="history?.items||[]" v-loading="historyLoading" size="small" max-height="55vh" row-key="id">
      <ElTableColumn label="保存时间" width="175"><template #default="{row}">{{ dateTime(row.createdAt) }}</template></ElTableColumn>
      <ElTableColumn prop="sku" label="颜色 SKU" min-width="165"/>
      <ElTableColumn prop="sizeCode" label="尺码" width="90"/>
      <ElTableColumn label="原成本 CNY" width="110"><template #default="{row}">{{ row.oldCostCny??'未设置' }}</template></ElTableColumn>
      <ElTableColumn label="新成本 CNY" width="110"><template #default="{row}">{{ row.costCny??'未设置' }}</template></ElTableColumn>
      <ElTableColumn prop="effectiveDate" label="生效日期" width="115"/>
      <ElTableColumn label="操作者" min-width="110"><template #default="{row}">{{ row.actor?.name||'—' }}</template></ElTableColumn>
    </ElTable>
    <ElEmpty v-else-if="!historyError" description="暂无成本变动" :image-size="80"/>
    <ElPagination v-if="history&&!historyError&&history.total>0" class="finance-gap" :current-page="history.page" :page-size="20" :total="history.total" layout="total, prev, pager, next" @current-change="loadHistory"/>
  </ElDialog>
</template>

<script setup>
import {computed,onMounted,onBeforeUnmount,reactive,ref} from 'vue';
import {onBeforeRouteLeave} from 'vue-router';
import {ElMessage} from 'element-plus';
import {ArrowDown,QuestionFilled} from '@element-plus/icons-vue';
import {api,save,confirm,dateTime,statusNames} from '../composables/workbench';
import {API_BASE} from '../api';
import {useAdminAuthStore} from '../stores/auth';
import {financeToday,financeCodes,financeActiveStates,financeReportDates,financeReportKey,costChanges,costValue,batchTargets,clearBatchTargets} from '../utils/finance';
const auth=useAdminAuthStore(),tab=ref('report'),error=ref(''),options=reactive({customers:[],salespeople:[],styles:[],categories:[]});
const activeStates=financeActiveStates,today=financeToday();
const filters=reactive({...financeReportDates(today),customerName:'',customerId:null,salespersonIds:[],styleCodes:[],statuses:[...activeStates],exchangeRate:null});
const advancedOpen=ref(false);
const reportDates=computed({get:()=>[filters.dateFrom,filters.dateTo],set:dates=>{filters.dateFrom=dates?.[0]||'';filters.dateTo=dates?.[1]||'';}});
const statusesChanged=computed(()=>Boolean(filters.statuses.length)&&(filters.statuses.length!==activeStates.length||activeStates.some(s=>!filters.statuses.includes(s))));
const advancedCount=computed(()=>Number(Boolean(filters.customerId))+Number(statusesChanged.value));
function resetReportFilters(){Object.assign(filters,{...financeReportDates(),customerName:'',customerId:null,salespersonIds:[],styleCodes:[],statuses:[...activeStates]});}
const reportChips=computed(()=>{
  const chips=[],dates=financeReportDates();
  if(filters.dateFrom!==dates.dateFrom||filters.dateTo!==dates.dateTo)chips.push({key:'dates',label:`日期：${filters.dateFrom} 至 ${filters.dateTo}`});
  if(filters.customerName.trim())chips.push({key:'customerName',label:'客户：'+filters.customerName.trim()});
  if(filters.salespersonIds.length)chips.push({key:'salespersonIds',label:'业务员：'+filters.salespersonIds.map(id=>id==='unassigned'?'未分配':options.salespeople.find(p=>String(p.id)===String(id))?.name||id).join('、')});
  if(filters.styleCodes.length)chips.push({key:'styleCodes',label:'款号：'+financeCodes(filters.styleCodes.join(',')).join('、')});
  if(filters.customerId)chips.push({key:'customerId',label:'商城账号：'+(options.customers.find(c=>String(c.id)===String(filters.customerId))?.name||filters.customerId)});
  if(statusesChanged.value)chips.push({key:'statuses',label:'状态：'+filters.statuses.map(s=>statusNames[s]).join('、')});
  return chips;
});
function removeReportFilter(key){if(key==='dates')Object.assign(filters,financeReportDates());else filters[key]=key==='statuses'?[...activeStates]:key==='customerId'?null:key==='customerName'?'':[];}
const costRange=row=>row.minCostCny===null?'未设置':row.minCostCny===row.maxCostCny?row.minCostCny:row.minCostCny+' — '+row.maxCostCny;
const savedRate=ref(null),rateVersion=ref('0'),rateLoading=ref(true),rateLoaded=ref(false),rateSaving=ref(false),rateError=ref('');
const rateValid=computed(()=>Number.isFinite(filters.exchangeRate)&&filters.exchangeRate>0&&filters.exchangeRate<=9999999999.99);
const rateDirty=computed(()=>filters.exchangeRate!==savedRate.value);
async function loadRate(apply=true){
  rateLoading.value=true;rateError.value='';
  try{const data=await api('finance/preferences');savedRate.value=data.exchangeRate===null?null:Number(data.exchangeRate);rateVersion.value=data.version;rateLoaded.value=true;if(apply)filters.exchangeRate=savedRate.value;}
  catch(e){rateLoaded.value=false;rateError.value='保存的汇率读取失败：'+e.message;}
  finally{rateLoading.value=false;}
}
async function saveRate(){
  if(rateSaving.value||!rateLoaded.value||!rateValid.value)return;
  rateSaving.value=true;rateError.value='';
  try{const data=await save('finance/preferences',{exchangeRate:filters.exchangeRate,version:rateVersion.value});savedRate.value=Number(data.exchangeRate);rateVersion.value=data.version;ElMessage.success('公共汇率已保存，所有财务账号共用');}
  catch(e){
    if(e.status===409){await loadRate(false);rateError.value=rateLoaded.value?`公共汇率已被其他用户或窗口更新，最新保存值为 ${savedRate.value}。当前输入已保留，核对后可再次保存。`:rateError.value;}
    else rateError.value=e.message;
  }finally{rateSaving.value=false;}
}
const costQuery=reactive({keyword:'',styleCodes:'',category:'',missingOnly:false,effectiveDate:today});
const costEffective=ref(today),costPage=ref(1),costTotal=ref(0),groups=ref([]),selected=ref([]),bulkSize=ref(''),bulkCost=ref(null),costLoading=ref(false),saving=ref(false);
const variants=computed(()=>groups.value.flatMap(g=>g.variants)),changes=computed(()=>costChanges(variants.value)),dirty=computed(()=>changes.value.length>0);
const selectedSizes=computed(()=>[...new Set(variants.value.filter(v=>selected.value.includes(v.id)).flatMap(v=>v.sizes.map(s=>s.sizeCode)))]);
const allSelected=computed(()=>variants.value.length>0&&variants.value.every(v=>selected.value.includes(v.id)));
const clearableTargets=computed(()=>clearBatchTargets(variants.value,selected.value,bulkSize.value));
const findSize=(v,s)=>v.sizes.find(x=>x.sizeCode===s);
const isChanged=(v,s)=>{const x=findSize(v,s);return x&&costValue(x.draftCost)!==x.costCny;};
const selectVariant=(id,value)=>{selected.value=value?[...new Set([...selected.value,id])]:selected.value.filter(v=>v!==id);};
const selectGroup=(group,value)=>group.variants.forEach(v=>selectVariant(v.id,value));
const selectAll=value=>{selected.value=value?variants.value.map(v=>v.id):[];};
async function leaveDraft(){return !saving.value&&(!dirty.value||await confirm('有尚未保存的成本修改。确认放弃修改并离开？取消可继续编辑。'));}
onBeforeRouteLeave(leaveDraft);
function unload(event){if(dirty.value){event.preventDefault();event.returnValue='';}}
onMounted(async()=>{window.addEventListener('beforeunload',unload);await Promise.all([loadRate(),(async()=>{try{Object.assign(options,await api('finance/options'));}catch(e){error.value=e.message;}})()]);});
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',unload);closeHistory();});
async function changeTab(value){if(value===tab.value)return;if(tab.value==='costs'&&!await leaveDraft())return;tab.value=value;if(value==='costs')await loadCosts(1,true);else groups.value=[];}
async function loadCosts(page=1,discard=false){
  if(costLoading.value||saving.value||(!discard&&!await leaveDraft()))return;
  costLoading.value=true;error.value='';
  try{const response=await api('finance/costs?'+new URLSearchParams({...costQuery,page,pageSize:12}));
    groups.value=response.items.map(g=>({...g,variants:g.variants.map(v=>({...v,sizes:v.sizes.map(s=>({...s,draftCost:s.costCny===null?undefined:Number(s.costCny)}))}))}));
    costPage.value=response.page;costTotal.value=response.total;costEffective.value=response.effectiveDate;selected.value=[];bulkSize.value='';
  }catch(e){error.value=e.message;}finally{costLoading.value=false;}
}
async function applyBatch(){
  if(bulkCost.value===null||bulkCost.value===undefined||!Number.isFinite(bulkCost.value)){error.value='请填写批量成本';return;}
  const targets=batchTargets(variants.value,selected.value,bulkSize.value);
  if(!targets.length){error.value='所选颜色中没有该尺码';return;}
  const count=targets.filter(({size})=>costValue(size.draftCost)!==null&&costValue(size.draftCost)!==costValue(bulkCost.value)).length;
  if(count&&!await confirm(`将覆盖 ${count} 个尺码已有的不同成本，共应用 ${targets.length} 项。仅修改页面草稿，保存后才生效。`))return;
  targets.forEach(({size})=>size.draftCost=bulkCost.value);error.value='';
}
async function clearBatch(){
  if(saving.value||costLoading.value)return;
  const targets=clearableTargets.value;
  if(!targets.length)return;
  if(!await confirm(`将清空已勾选颜色中「${bulkSize.value||'全部尺码'}」的 ${targets.length} 项成本，改为未设置。仅修改页面草稿；保存后从 ${costEffective.value} 起生效，历史记录保留。`))return;
  targets.forEach(({size})=>size.draftCost=undefined);error.value='';
  ElMessage.success(`已清空 ${targets.length} 项草稿${dirty.value?'，保存成本后生效':'，已保存数据未改变'}`);
}
const preview=ref(null),previewOpen=ref(false);let pendingSave=null;
async function previewSave(){
  error.value='';
  saving.value=true;
  try{const body={effectiveDate:costEffective.value,changes:changes.value};preview.value=await save('finance/costs/preview',body,'POST');pendingSave={...body,previewHash:preview.value.previewHash,requestId:crypto.randomUUID()};previewOpen.value=true;}
  catch(e){error.value=e.message;}finally{saving.value=false;}
}
async function commitCosts(){
  saving.value=true;error.value='';
  try{await save('finance/costs/save',pendingSave,'POST');previewOpen.value=false;ElMessage.success('成本已保存');saving.value=false;await loadCosts(costPage.value,true);}
  catch(e){error.value=e.message;if(e.status)previewOpen.value=false;}finally{saving.value=false;}
}
const historyOpen=ref(false),history=ref(null),historyTitle=ref(''),historyStyle=ref(''),historyLoading=ref(false),historyError=ref(''),historyPage=ref(1);
const historyFilters=reactive({productId:null,sizeCode:''}),historyOptions=reactive({variants:[],sizes:[]});let historyRequest=0,historyController;
function closeHistory(){++historyRequest;historyController?.abort();historyLoading.value=false;history.value=null;}
async function showHistory(group){
  closeHistory();historyStyle.value=group.styleCode;historyTitle.value=`成本历史 · ${group.styleCode}`;
  Object.assign(historyFilters,{productId:null,sizeCode:''});
  Object.assign(historyOptions,{variants:group.variants.map(v=>({productId:v.id,sku:v.sku,color:v.color,deleted:false})),sizes:[...group.sizes]});
  historyError.value='';historyOpen.value=true;await loadHistory(1);
}
async function loadHistory(page=1){
  if(!historyOpen.value)return;
  const id=++historyRequest;historyController?.abort();historyController=new AbortController();historyPage.value=page;historyLoading.value=true;historyError.value='';history.value=null;
  const params={styleCode:historyStyle.value,page};if(historyFilters.productId)params.productId=historyFilters.productId;if(historyFilters.sizeCode)params.sizeCode=historyFilters.sizeCode;
  try{const data=await api('finance/costs/history?'+new URLSearchParams(params),{signal:historyController.signal,skipGlobalLoading:true});if(id===historyRequest&&historyOpen.value){history.value=data;Object.assign(historyOptions,data.options);}}
  catch(e){if(e.name!=='AbortError'&&id===historyRequest&&historyOpen.value)historyError.value=e.message;}
  finally{if(id===historyRequest)historyLoading.value=false;}
}
const result=ref(null),reportLoading=ref(false),exporting=ref(false);
const reportRateChanged=computed(()=>Boolean(result.value)&&(!rateValid.value||filters.exchangeRate!==Number(result.value.filters.exchangeRate)));
const reportOutdated=computed(()=>Boolean(result.value)&&financeReportKey(filters)!==financeReportKey(result.value.filters));
async function queryReport(page=1,existing=false){
  if(reportLoading.value)return;reportLoading.value=true;error.value='';
  try{const query=existing?result.value.filters:{...filters,styleCodes:financeCodes(filters.styleCodes.join(','))};
    const data=await save('finance/reports/query',{...query,page,pageSize:25},'POST');
    data.items.forEach(r=>r.rowKey=JSON.stringify([r.styleCode,r.productId,r.sku,r.sizeCode]));result.value=data;
  }catch(e){error.value=e.message;}finally{reportLoading.value=false;}
}
async function exportReport(){
  if(!result.value||reportOutdated.value||reportLoading.value||exporting.value)return;
  exporting.value=true;error.value='';
  try{const response=await fetch(`${API_BASE}/api/admin/finance/reports/export`,{method:'POST',headers:{Authorization:`Bearer ${auth.token}`,'Content-Type':'application/json'},body:JSON.stringify(result.value.filters)});
    if(!response.ok){if(response.status===401)window.dispatchEvent(new Event('admin-session-expired'));throw new Error((await response.json().catch(()=>({}))).message||'导出失败');}
    const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='财务成本核算.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){error.value=e.message;}finally{exporting.value=false;}
}
</script>

<style scoped>
.finance-panel{background:#fff;padding:22px;border:1px solid #e1e6ee;border-radius:10px}.finance-tabs,.finance-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.finance-tabs{padding-bottom:18px;border-bottom:1px solid #e8edf4}.finance-filters{display:flex;align-items:flex-end;flex-wrap:wrap;gap:14px;padding:20px 0}.finance-filters > label:not(.el-checkbox){display:flex;flex-direction:column;gap:7px;width:210px;color:#596b83;font-size:12px}.finance-filters :deep(.el-select),.finance-filters :deep(.el-date-editor),.finance-filters :deep(.el-input-number){width:100%}.finance-toolbar{background:#f4f7fb;padding:14px;border-radius:8px;font-size:12px}.finance-note{font-size:12px;line-height:1.8;color:#6b7b90;margin:15px 0}.finance-gap{margin-top:18px}.cost-group{border:1px solid #e1e6ee;border-radius:8px;margin:18px 0;overflow:hidden}.cost-group header{display:flex;gap:18px;align-items:center;padding:12px 16px;background:#f7f9fc;flex-wrap:wrap}.cost-group header small{color:#789}.finance-scroll{overflow:auto}.cost-matrix{border-collapse:collapse;min-width:100%;font-size:12px}.cost-matrix th,.cost-matrix td{padding:12px;border-bottom:1px solid #edf0f4;text-align:center;min-width:148px}.cost-matrix th{color:#5d718a;font-weight:500}.cost-matrix small{display:block;margin-top:5px;color:#8994a2;font-size:11px}.cost-matrix td:first-child{min-width:225px;text-align:left;white-space:nowrap}.cost-matrix td:first-child>div{display:inline-block;vertical-align:middle;margin-left:12px}.cost-matrix :deep(.el-input-number){width:132px}.cost-changed{background:#fff8e7}.finance-link{display:block;margin:6px auto 0;border:0;background:none;font-size:11px;color:#446d9e;cursor:pointer}.finance-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:20px 0}.finance-cards>div{background:#f6f8fb;border:1px solid #e3e9f0;border-radius:7px;padding:16px}.finance-cards span{display:block;font-size:12px;color:#61738c;margin-bottom:10px}.finance-cards strong{font-size:19px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.line-detail{padding:16px;background:#f6f8fb}.missing{display:block;color:#c17820;font-size:11px}.finance-panel :deep(.el-checkbox__inner){width:20px;height:20px}.finance-panel :deep(.el-checkbox__inner:after){left:7px;top:4px}.finance-panel :deep(.el-checkbox){min-height:32px}.finance-panel :deep(.el-table .cell){overflow-wrap:anywhere}@media(max-width:700px){.finance-panel{padding:12px}.finance-filters > label:not(.el-checkbox){width:calc(50% - 7px)}.finance-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.finance-toolbar{gap:10px}.cost-group header{gap:10px}.finance-tabs :deep(.el-button){flex:1}.finance-panel :deep(.el-pagination){overflow:auto}}
</style>

<style scoped>
.finance-tab-nav,.finance-header-actions,.finance-rate-control{display:flex;align-items:center;gap:10px;min-width:0}
.finance-header-actions{margin-left:auto;flex-wrap:wrap;justify-content:flex-end}
.finance-tab-nav :deep(.el-button+.el-button),.finance-header-actions :deep(.el-button+.el-button){margin-left:0}
.finance-rate-control{gap:8px;white-space:nowrap;color:#596b83;font-size:12px}
.finance-rate-label{font-weight:500}.finance-rate-label span{margin-left:6px;font-weight:400}
.finance-rate-control :deep(.el-input-number){width:144px}
.finance-rate-notice{margin:0 0 16px;font-size:12px;color:#b66a15;line-height:1.6}
.finance-report-filters{display:grid;grid-template-columns:minmax(245px,1.4fr) repeat(3,minmax(115px,1fr)) auto;align-items:end;gap:12px;padding:16px 0 12px}
.finance-filters>label:not(.el-checkbox){line-height:18px;white-space:nowrap}
.finance-report-filters>label:not(.el-checkbox){width:auto;min-width:0}
.finance-filters :deep(.el-select__wrapper),.finance-filters :deep(.el-input__wrapper){min-height:32px;box-sizing:border-box}
.finance-filters :deep(.el-input),.finance-filters :deep(.el-date-editor.el-input){height:32px}
.finance-report-filters>.el-button{margin:0}
@media(max-width:1300px){.finance-report-filters{grid-template-columns:minmax(245px,1.4fr) repeat(3,minmax(0,1fr))}.report-filter-actions{grid-column:1/-1;justify-content:flex-end}}
@media(max-width:1100px){.finance-header-actions{width:100%;margin-left:0;justify-content:flex-start}.finance-report-filters{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.finance-report-filters{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.finance-report-filters>label:not(.el-checkbox){width:auto}.report-date-field{grid-column:1/-1}.finance-tab-nav{width:100%}.finance-tabs .finance-header-actions :deep(.el-button){flex:none}.finance-rate-control{width:100%}.finance-rate-control :deep(.el-input-number){flex:1;width:auto}.finance-header-actions{gap:10px}.cost-matrix td:first-child,.cost-matrix th:first-child{min-width:148px}}
.finance-cost-filters{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr)) auto auto;align-items:end}
.finance-cost-filters>label:not(.el-checkbox){width:auto;min-width:0}.finance-cost-filters>.el-button{margin:0}
.finance-toolbar{padding:12px;gap:10px}.finance-toolbar>.el-button:last-child{margin-left:auto}
.finance-cost-note{display:flex;align-items:center;gap:6px;margin:10px 0;color:#6b7b90;font-size:12px;line-height:1.6}
.finance-cost-note :deep(.el-button){color:#8290a2}.finance-cost-help{font-size:12px;line-height:1.8;color:#61738a}
.cost-group{margin:12px 0;border-radius:7px}.cost-group header{padding:8px 12px;gap:12px}
.cost-group header small{font-size:11px}.cost-group header :deep(.el-checkbox__label){font-size:13px}
.cost-header-actions{margin-left:auto;display:flex;align-items:center;gap:6px;min-width:0}
.cost-header-actions :deep(.el-button+.el-button){margin-left:0}.cost-unit{font-size:11px;color:#8994a2;margin-right:6px;white-space:nowrap}
.cost-header-actions :deep(.el-icon){transition:transform .15s}.cost-expanded{transform:rotate(180deg)}
.cost-matrix th,.cost-matrix td{padding:10px 12px;min-width:136px;vertical-align:middle}
.cost-matrix th{background:#fbfcfe;padding-top:9px;padding-bottom:9px}.cost-matrix td:first-child,.cost-matrix th:first-child{position:sticky;left:0;min-width:200px;z-index:1;background:#fff}
.cost-matrix th:first-child{z-index:2;background:#fbfcfe}.cost-matrix td:first-child>div{margin-left:10px}.cost-matrix td:first-child strong{font-weight:500}
.cost-matrix :deep(.el-input-number){width:112px;height:32px}.cost-matrix :deep(.el-input__inner){font-size:12px;font-variant-numeric:tabular-nums}
.cost-matrix :deep(.el-input__inner::placeholder){font-size:11px}.cost-matrix small{margin-top:2px;font-size:11px}
.cost-history-filters{display:flex;gap:12px;margin-bottom:16px}.cost-history-filters>label{display:flex;flex-direction:column;gap:7px;font-size:12px;color:#596b83;flex:1;min-width:0}
.cost-history-error{display:flex;align-items:center;gap:10px}.cost-history-error>.el-alert{flex:1}.cost-history-dialog :deep(.el-table){font-size:12px}
.cost-history-dialog :deep(.el-pagination){overflow:auto}.cost-history-dialog :deep(.el-select__wrapper){min-height:32px}
@media(max-width:1250px){.finance-cost-filters{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.finance-cost-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.cost-group header{gap:8px}.cost-header-actions{gap:3px}.cost-unit{display:none}.cost-group header small{font-size:11px}.cost-matrix td:first-child,.cost-matrix th:first-child{min-width:148px}.cost-matrix th,.cost-matrix td{padding:10px;min-width:128px}.finance-toolbar>.el-button:last-child{margin-left:0}}
.finance-tabs{padding-bottom:12px;gap:12px}.finance-tab-nav{gap:12px}
.finance-tab-nav :deep(.el-button){border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;padding:8px 10px;color:#6b7b90}
.finance-tab-nav :deep(.finance-tab-active){border-bottom-color:#2563eb;color:#2563eb;font-weight:600}
.finance-report-filters :deep(.el-date-editor--daterange){width:100%;min-width:0;height:32px;box-sizing:border-box}
.finance-report-filters :deep(.el-range-input){font-size:12px;min-width:0}.finance-report-filters :deep(.el-range-separator){font-size:12px;flex:0}
.report-filter-actions{display:flex;gap:6px;align-items:center;min-height:32px;flex-wrap:wrap}
.report-filter-actions :deep(.el-button+.el-button){margin-left:0}.report-filter-actions :deep(.el-button){padding:8px 10px}
.report-filter-actions :deep(.el-icon){margin-left:4px}.report-filter-count{background:#eaf1ff;color:#2563eb;border-radius:9px;padding:0 5px;margin-left:4px;font-size:11px}
.report-advanced-filters{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,220px));gap:12px;padding-top:12px;border-top:1px dashed #e8edf4}
.report-advanced-filters>label{display:flex;flex-direction:column;gap:7px;font-size:12px;line-height:18px;color:#596b83;min-width:0}
.report-filter-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.report-filter-chips :deep(.el-tag){max-width:100%;height:24px;font-size:11px}.report-filter-chips :deep(.el-tag__content){max-width:240px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.report-context{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11px;color:#8290a2;line-height:1.6;margin-bottom:12px}
.report-context :deep(.el-button){font-size:11px;height:24px;padding:2px 4px;color:#71829a}.report-context :deep(.el-icon){margin-right:4px}
.finance-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));padding:14px 0;border-top:1px solid #e8edf4;border-bottom:1px solid #e8edf4}
.finance-summary>article{display:flex;flex-direction:column;gap:6px;padding:0 20px;border-left:1px solid #edf0f4;min-width:0}
.finance-summary>article:first-child{border-left:0;padding-left:0}.finance-summary>article>span{font-size:12px;color:#61738c}
.finance-summary small{font-size:11px;color:#8994a2;overflow-wrap:anywhere}.finance-summary strong{font-size:20px;color:#243348;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.finance-summary strong.summary-incomplete{font-size:14px;color:#b66a15;font-weight:500}
.report-quantity-summary{display:flex;align-items:center;flex-wrap:wrap;gap:8px 18px;font-size:12px;color:#61738c;margin-top:12px}
.report-quantity-summary .report-missing{color:#b66a15;font-size:11px}.report-result-meta{font-size:11px;color:#8994a2;margin:8px 0 12px;line-height:1.6}
.report-table-scroll{width:100%;min-width:0;overflow-x:auto}.finance-report-table{width:100%;font-size:12px}
.finance-report-table :deep(.el-table__cell){padding:10px 0}.finance-report-table :deep(th.el-table__cell){background:#fafbfd;font-weight:500}
.finance-report-table :deep(.cell){font-variant-numeric:tabular-nums;line-height:1.6}
.report-row-context{display:flex;gap:12px 24px;flex-wrap:wrap;font-size:12px;color:#61738c;margin-bottom:12px}.report-row-context b{font-weight:500;margin-left:6px}
.report-empty{text-align:center;padding:40px 12px;font-size:12px;color:#8994a2;border-top:1px solid #edf0f4}
@media(max-width:700px){.report-advanced-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.report-filter-actions{justify-content:flex-start}.finance-summary{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 0}.finance-summary>article{padding:0 10px}.finance-summary>article:first-child{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:0}.finance-summary>article:first-child>span{grid-column:1/-1}.finance-summary>article:first-child>small{align-self:center;text-align:right}.finance-summary>article:nth-child(2){border-left:0;padding-left:0}.finance-summary strong{font-size:17px}.finance-summary strong.summary-incomplete{font-size:13px}.report-table-scroll>.finance-report-table{min-width:900px}.report-filter-chips :deep(.el-tag__content){max-width:260px}.report-table-scroll .line-detail{padding:10px}}
@media(max-width:700px){:global(.finance-report-date-popper .el-date-range-picker){width:calc(100vw - 24px);max-width:646px;max-height:60vh;overflow-y:auto}:global(.finance-report-date-popper .el-date-range-picker__content){width:100%;float:none;box-sizing:border-box;padding:12px}:global(.finance-report-date-popper .el-date-range-picker__content.is-right){border-left:0;border-top:1px solid #e8edf4}}
</style>
