<template>
  <section v-if="isPhone" class="mobile-finance" data-testid="mobile-finance">
    <header class="mf-heading"><div><h1>财务</h1><p>让每一笔经营，都心中有数</p></div><MobileActionMenu label="更多"><ElButton @click="mobileToolsOpen=true">公共汇率</ElButton><template v-if="tab==='report'"><ElButton :disabled="!result||reportLoading||exporting||reportOutdated" :loading="exporting" @click="exportReport">导出核算 Excel</ElButton></template><template v-else><ElButton :disabled="!appliedCostQuery||costOutdated||costLoading||costExporting" :loading="costExporting" @click="exportCosts">导出成本表</ElButton><ElButton :disabled="saving||costLoading||costExporting" @click="openCostImport">导入成本表</ElButton><ElButton @click="mobileBatchMode=!mobileBatchMode;selected=[]">{{ mobileBatchMode?'结束批量选择':'批量设置成本' }}</ElButton></template><ElButton @click="mobileExplanationOpen=true">核算说明</ElButton></MobileActionMenu></header>
    <nav class="mf-tabs" aria-label="财务视图"><button :class="{active:tab==='report'}" @click="changeTab('report')">成本统计</button><button :class="{active:tab==='costs'}" @click="changeTab('costs')">商品成本</button></nav>
    <ElAlert v-if="rateError||error" :title="rateError||error" type="error" :closable="false" class="mf-alert" />
    <template v-if="tab==='report'">
      <ResponsiveFilters class="mf-report-search" @submit="applyMobileFinanceFilters">
        <ElInput v-model="filters.customerName" clearable placeholder="搜索订单客户名称" @clear="applyMobileFinanceFilters"><template #prefix><ElIcon><Search /></ElIcon></template></ElInput>
        <ElDatePicker v-model="reportDates" type="daterange" value-format="YYYY-MM-DD" :clearable="false" start-placeholder="开始日期" end-placeholder="结束日期" popper-class="finance-report-date-popper"/>
        <label class="mobile-filter-field"><span>业务员</span><ElSelect v-model="filters.salespersonIds" multiple filterable collapse-tags clearable placeholder="全部业务员"><ElOption label="未分配" value="unassigned"/><ElOption v-for="p in options.salespeople" :key="p.id" :value="p.id" :label="p.name+(p.status==='active'?'':'（已停用）')"/></ElSelect></label>
        <label class="mobile-filter-field"><span>款号</span><ElSelect v-model="filters.styleCodes" multiple filterable allow-create default-first-option collapse-tags clearable placeholder="多选或逗号输入"><ElOption v-for="style in options.styles" :key="style" :value="style" :label="style"/></ElSelect></label>
        <label class="mobile-filter-field"><span>商城账号</span><ElSelect v-model="filters.customerId" filterable clearable placeholder="全部商城账号"><ElOption v-for="c in options.customers" :key="c.id" :value="c.id" :label="c.name+' · '+(c.company||c.id)"/></ElSelect></label>
        <label class="mobile-filter-field"><span>订单状态</span><ElSelect v-model="filters.statuses" multiple collapse-tags placeholder="全部有效状态"><ElOption v-for="state in activeStates" :key="state" :value="state" :label="statusNames[state]"/></ElSelect></label>
        <ElButton native-type="submit" type="primary" aria-label="查询核算" :loading="reportLoading" :disabled="rateLoading||!rateValid">查询</ElButton><ElButton @click="resetReportFilters">重置</ElButton>
      </ResponsiveFilters>
      <div v-if="reportChips.length" class="mf-filter-chips"><ElTag v-for="chip in reportChips" :key="chip.key" closable effect="plain" @close="removeReportFilter(chip.key)">{{ chip.label }}</ElTag></div>
      <div v-if="reportOutdated" class="mf-stale" role="status"><span>条件、汇率或成本已更改</span><ElButton text type="primary" :loading="reportLoading" @click="queryReport(1)">更新核算</ElButton></div>
      <ElSkeleton v-if="!result&&reportLoading" :rows="7" animated />
      <template v-if="result">
        <section class="mf-hero" v-loading="reportLoading"><div class="mf-hero-caption"><span>折合商品销售额 · CNY</span><ElTag v-if="result.summary.missingQuantity" size="small" type="warning">部分核算</ElTag></div><strong class="mf-hero-amount">¥{{ result.summary.salesCny }}</strong><p class="mf-original">USD {{ result.summary.salesUsd }} <span>＋ CNY {{ result.summary.nativeSalesCny }} 原币</span></p><div class="mf-profit-grid"><div><span>商品成本</span><strong>¥{{ result.summary.totalCostCny ?? result.summary.knownCostCny }}</strong><small v-if="result.summary.totalCostCny===null">已知成本 · 待补全</small></div><div><span>商品毛利</span><strong :class="{'is-profit':result.summary.profitCny!==null}">¥{{ result.summary.profitCny ?? result.summary.knownProfitCny }}</strong><small v-if="result.summary.profitCny===null">已设置部分 · 待补全</small></div></div><footer><span>{{ result.summary.orderCount }} 个订单 · {{ result.summary.quantity }} 件</span><small>汇率 {{ result.filters.exchangeRate }}</small></footer></section>
        <p v-if="result.summary.missingQuantity" class="mf-missing" role="status"><ElIcon><InfoFilled /></ElIcon>{{ result.summary.missingQuantity }} 件尚未设置成本，完整成本与毛利待补全</p>
        <div class="mf-section"><h2>款号核算</h2><small>{{ result.total }} 条 · 点击查看明细</small></div>
        <div class="mf-report-list"><button v-for="row in result.items" :key="row.rowKey" class="mf-report-card" @click="mobileReportRow=row;mobileReportOpen=true"><span class="mf-report-top"><strong>{{ row.styleCode }}</strong><span>{{ row.quantity }} 件<ElIcon><ArrowRight /></ElIcon></span></span><span class="mf-report-sku">{{ row.sku }} <i>·</i> {{ row.sizeCode }}</span><span class="mf-report-money"><span><small>商品销售额</small><b>USD {{ row.salesUsd }}</b><em v-if="Number(row.nativeSalesCny)">CNY {{ row.nativeSalesCny }}</em></span><span><small>成本 / 毛利 · CNY</small><b>{{ row.totalCostCny ?? ('已知 '+row.knownCostCny) }} / {{ row.profitCny ?? '待补全' }}</b><em v-if="row.missingQuantity">{{ row.missingQuantity }} 件待补成本</em></span></span></button><ElEmpty v-if="!result.items.length" description="当前筛选暂无核算结果" :image-size="64" /></div>
        <ElPagination class="mf-pagination" :current-page="result.page" :page-size="25" :total="result.total" :pager-count="5" layout="prev, pager, next" @current-change="page=>queryReport(page,true)"/><p class="mf-generated">生成于 {{ dateTime(result.generatedAt) }} · 北京时间</p>
      </template>
      <section v-else-if="!reportLoading" class="mf-empty"><ElIcon><DataAnalysis /></ElIcon><h2>{{ rateValid?'查看成本与商品毛利':'先设置核算汇率' }}</h2><p>{{ rateValid?'选择条件，掌握真实经营表现':'填入 1 USD 对应人民币金额，开始核算' }}</p><ElButton type="primary" @click="rateValid?queryReport(1):mobileToolsOpen=true">{{ rateValid?'查询核算':'设置汇率' }}</ElButton></section>
    </template>
    <template v-else>
      <ResponsiveFilters class="mf-cost-search" @submit="applyMobileFinanceFilters">
        <ElInput v-model="costQuery.styleCodes" clearable placeholder="搜索款号，多个用逗号分隔" @clear="loadCosts(1)"><template #prefix><ElIcon><Search /></ElIcon></template></ElInput>
        <label class="mobile-filter-field"><span>SKU / 颜色</span><ElInput v-model="costQuery.keyword" clearable placeholder="SKU / 颜色"/></label>
        <ElSelect v-model="costQuery.category" clearable placeholder="全部分类" aria-label="商品成本分类"><ElOption v-for="c in options.categories" :key="c.key" :value="c.key" :label="c.key"/></ElSelect>
        <label class="mobile-filter-field"><ElCheckbox v-model="costQuery.missingOnly">仅未设置成本</ElCheckbox></label>
        <ElButton native-type="submit" type="primary" :loading="costLoading" :disabled="saving">查询</ElButton><ElButton :disabled="saving||costLoading" @click="resetMobileCosts">重置</ElButton>
      </ResponsiveFilters>
      <p v-if="costOutdated" class="mf-stale">筛选已更改，查询后更新；当前不可导出成本表。</p>
      <div class="mf-section"><h2>{{ mobileBatchMode?'选择款号':'整款成本' }} <small>· {{ costTotal }} 款</small></h2><span v-if="mobileBatchMode"><ElCheckbox :model-value="allSelected" :indeterminate="selected.length>0&&!allSelected" :disabled="saving||costLoading||!groups.length" @change="selectAll">本页全选</ElCheckbox></span><small v-else>CNY / 件</small></div>
      <div ref="costWorkspace" class="mf-ledger" v-loading="costLoading"><article v-for="group in groups" :key="group.styleCode" class="mf-ledger-row" :class="{'is-dirty':isChanged(group)}"><ElCheckbox v-if="mobileBatchMode" :model-value="selected.includes(group.styleCode)" :disabled="saving||costLoading" :aria-label="'选择 '+group.styleCode" @change="value=>selectStyle(group.styleCode,value)"/><div class="mf-ledger-code"><RouterLink v-if="auth.can('products')" :to="{path:'/products',query:{status:'all',styleCode:group.styleCode}}">{{ group.styleCode }}</RouterLink><strong v-else>{{ group.styleCode }}</strong><small>{{ group.active===false?'已停用':isChanged(group)?'未保存':'整款颜色与尺码共用' }}</small></div><div class="cost-amount-cell mf-ledger-input"><span>¥</span><ElInputNumber v-model="group.draftCost" :min="0" :max="9999999999.99" :precision="2" :controls="false" :disabled="saving||costLoading" placeholder="未设置" :aria-label="group.styleCode+' 成本'" @keydown.enter.prevent="focusCostInput($event.shiftKey?-1:1)"/></div><ElButton text class="mf-history-button" :aria-label="group.styleCode+' 成本历史'" @click="showHistory(group)"><ElIcon><Clock /></ElIcon></ElButton></article><ElEmpty v-if="!groups.length&&!costLoading" description="没有找到匹配款号" :image-size="64"/></div>
      <ElPagination class="mf-pagination" :current-page="costPage" :page-size="financeCostPageSize" :total="costTotal" :pager-count="5" layout="prev, pager, next" @current-change="page=>loadCosts(page,false,true)"/>
      <div v-if="selected.length" class="mf-batch"><span>已选 {{ selected.length }} 款</span><ElInputNumber v-model="bulkCost" :min="0" :max="9999999999.99" :precision="2" :controls="false" placeholder="批量金额" aria-label="批量成本金额"/><ElButton :disabled="saving||costLoading" @click="applyBatch">应用</ElButton><ElButton text type="danger" :disabled="!clearableTargets.length||saving||costLoading" @click="clearBatch">清空</ElButton></div>
      <div v-if="dirty" class="mf-savebar" data-testid="mobile-cost-savebar"><span><i/>{{ changes.length }} 款未保存</span><ElButton type="primary" :loading="saving" :disabled="saving||costLoading" @click="previewSave">保存成本</ElButton></div>
    </template>
    <ElDrawer v-model="mobileToolsOpen" title="公共核算汇率" size="60%" direction="btt"><p class="mf-tool-note">所有财务账号共用，不改变订单成交币种和历史售价。</p><ElForm label-position="top"><ElFormItem label="1 USD = CNY"><ElInputNumber v-model="filters.exchangeRate" :precision="6" :step="0.000001" :min="0.000001" :max="9999999999.99" :controls="false" :disabled="rateLoading||rateSaving" aria-label="核算汇率"/></ElFormItem></ElForm><ElAlert v-if="rateError" :title="rateError" type="error" :closable="false"/><template #footer><ElButton v-if="!rateLoaded" :loading="rateLoading" @click="loadRate()">重新读取</ElButton><ElButton v-else type="primary" :disabled="!rateValid||!rateDirty" :loading="rateSaving" @click="saveRate">保存公共汇率</ElButton></template></ElDrawer>
    <ElDrawer v-model="mobileExplanationOpen" title="核算说明" size="75%" direction="btt"><div class="mf-explanation"><p>每款首次填写成本时补算此前订单；之后改价仅用于保存后的新订单，已有订单按对应历史成本核算。</p><p>清空后的新订单为未设置成本，再次填写不补算清空期间。空白不等于明确零成本，全部历史保留。</p><p>销售额使用订单成交价格；美元按本次核算汇率折算，人民币原币直接计入。不含运费、税费或其他费用；包含未付款订单时不代表实际回款。</p><p>人民币逐订单商品行四舍五入至分后汇总；导出为全部筛选结果及完整字段，不限当前分页，使用导出时的数据库快照。</p></div></ElDrawer>
    <ElDrawer v-model="mobileReportOpen" :title="mobileReportRow?.styleCode+' · 核算明细'" size="94%" direction="btt"><template v-if="mobileReportRow"><p class="mf-detail-context">{{ mobileReportRow.sku }} / {{ mobileReportRow.sizeCode }} · 折合销售额 ¥{{ mobileReportRow.salesCny }} · 单件成本 {{ costRange(mobileReportRow) }} CNY</p><article v-for="(line,index) in mobileReportRow.lines" :key="line.orderNo+'-'+index" class="mf-order-line"><h3>{{ line.orderNo }}</h3><p>{{ line.customerName }} <span>· {{ line.salesperson||'未分配业务员' }}</span></p><small>{{ dateTime(line.createdAt) }} · 商城账号 {{ line.accountName }}</small><div><span>{{ line.quantity }} 件 · {{ line.currency }} {{ line.originalAmount }}</span><strong>毛利 ¥{{ line.profitCny??'待补全' }}</strong></div><dl><dt>单件成本 CNY</dt><dd>{{ line.unitCostCny??'未设置' }}</dd><dt>成本 CNY</dt><dd>{{ line.costCny??'待补全' }}</dd><dt>成本生效时间</dt><dd>{{ line.costEffectiveAt?dateTime(line.costEffectiveAt):'—' }} {{ line.costMatch==='首次成本补算'?'· 首次补算':'' }}</dd></dl></article></template></ElDrawer>
  </section>
  <template v-else>
  <h1 class="mobile-finance-title">财务管理</h1>
  <section class="finance-panel" :class="{'finance-cost-mode':tab==='costs'}">
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
        <template v-else><ElButton :disabled="!appliedCostQuery||costOutdated||costLoading||costExporting" :loading="costExporting" :title="costOutdated?'筛选已修改，请先查询':'导出已查询条件下全部款号的已保存成本，不含页面草稿'" @click="exportCosts">导出成本表</ElButton><ElButton :disabled="saving||costLoading||costExporting" title="导入前请先保存或撤销页面成本修改" @click="openCostImport">导入成本表</ElButton></template>
      </div>
    </div>
    <ElAlert v-if="rateError" :title="rateError" type="error" :closable="false" class="finance-gap" />
    <ElAlert v-if="error" :title="error" type="error" :closable="false" class="finance-gap" />
    <template v-if="tab==='costs'">
      <div ref="costWorkspace" class="cost-workspace">
        <form class="finance-filters finance-cost-filters" @submit.prevent="loadCosts(1)">
          <label>款号<ElInput v-model="costQuery.styleCodes" placeholder="多个款号用逗号分隔" clearable><template #prefix><ElIcon><Search /></ElIcon></template></ElInput></label>
          <label>SKU / 颜色<ElInput v-model="costQuery.keyword" placeholder="输入 SKU 或颜色查找款号" clearable /></label>
          <label>分类<ElSelect v-model="costQuery.category" clearable placeholder="全部分类"><ElOption v-for="c in options.categories" :key="c.key" :label="c.key" :value="c.key" /></ElSelect></label>
          <div class="cost-filter-actions"><ElCheckbox v-model="costQuery.missingOnly">仅未设置</ElCheckbox><ElButton native-type="submit" type="primary" :loading="costLoading">查询</ElButton></div>
        </form>
        <p v-if="costOutdated" class="finance-rate-notice" role="status">条件已修改，查询后更新；重新查询前不可导出成本表。</p>
        <div class="cost-sheet">
          <div class="cost-sheet-caption">
            <div class="cost-sheet-selection"><ElCheckbox :model-value="allSelected" :indeterminate="selected.length>0&&!allSelected" :disabled="!groups.length||saving||costLoading" @change="selectAll">当前页全选</ElCheckbox><span class="cost-result-count">共 <b>{{ costTotal }}</b> 款</span></div>
            <div class="cost-sheet-meta"><span><span class="cost-shared-label">整款共用 <i>·</i></span> CNY / 件</span><ElPopover trigger="click" placement="bottom-end" :width="320" popper-style="max-width:calc(100vw - 32px)">
              <template #reference><ElButton text circle aria-label="成本填写说明"><ElIcon><QuestionFilled /></ElIcon></ElButton></template>
              <div class="finance-cost-help">每个款号一个人民币单件成本，全部颜色和尺码共用。空白表示未设置，0 为明确零成本。<br/>首次填写成本会补算此前订单；之后改价从保存时间起生效，旧订单按对应历史成本核算。<br/>清空后的新订单为未设置成本，再次填写不补算清空期间。批量应用和清空仅修改草稿，保存后生效，历史记录保留。</div>
            </ElPopover></div>
          </div>
          <div class="cost-ledger" v-loading="costLoading" :class="{'cost-ledger-single':costColumns.length<2}">
            <div v-for="(column,index) in costColumns" :key="index" class="cost-ledger-column">
              <table class="style-cost-table" :aria-label="costColumns.length>1?`整款成本 第 ${index+1} 组`:'整款成本'">
                <colgroup><col class="cost-select-col"/><col/><col class="cost-amount-col"/><col class="cost-history-col"/></colgroup>
                <thead><tr><th class="style-select" scope="col"><span class="cost-sr-only">选择</span></th><th scope="col">款号</th><th class="cost-amount-heading" scope="col">单件成本</th><th scope="col"><span class="cost-sr-only">历史操作</span></th></tr></thead>
                <tbody><tr v-for="group in column" :key="group.styleCode" :class="{'cost-changed':isChanged(group),'cost-selected':selected.includes(group.styleCode)}">
                  <td class="style-select"><ElCheckbox :model-value="selected.includes(group.styleCode)" :aria-label="`选择 ${group.styleCode}`" :disabled="saving||costLoading" @change="value=>selectStyle(group.styleCode,value)" /></td>
                  <td class="style-code"><RouterLink v-if="auth.can('products')" :to="{path:'/products',query:{status:'all',styleCode:group.styleCode}}" :title="`查看 ${group.styleCode} 商品`">{{ group.styleCode }}</RouterLink><span v-else :title="group.styleCode">{{ group.styleCode }}</span><small v-if="group.active===false" class="cost-history-note">已停用</small><span v-if="isChanged(group)" class="cost-edit-dot" :aria-label="`${group.styleCode} 未保存`" title="未保存"/></td>
                  <td class="cost-amount-cell"><div class="cost-input-shell" :class="{'cost-input-empty':costValue(group.draftCost)===null}"><span class="cost-currency" aria-hidden="true">¥</span><ElInputNumber v-model="group.draftCost" :precision="2" :min="0" :max="9999999999.99" :controls="false" :disabled="saving||costLoading" placeholder="未设置" :aria-label="`${group.styleCode} 成本`" title="Enter 下一个款号，Shift + Enter 上一个" @keydown.enter.prevent="focusCostInput($event.shiftKey?-1:1)" /></div></td>
                  <td class="cost-history-cell"><ElButton text class="cost-history-button" :aria-label="`${group.styleCode} 成本历史`" @click="showHistory(group)"><ElIcon><Clock /></ElIcon><span>历史</span></ElButton></td>
                </tr></tbody>
              </table>
            </div>
            <div v-if="!groups.length" class="style-cost-empty" role="status">{{ costLoading?'正在加载成本…':'暂无匹配款号，请调整筛选条件' }}</div>
          </div>
          <div class="cost-sheet-bottom"><span>每页 {{ financeCostPageSize }} 款<span class="cost-pagination-hint">，勾选后可批量填写</span></span><ElPagination :current-page="costPage" :page-size="financeCostPageSize" :total="costTotal" layout="prev, pager, next" @current-change="page=>loadCosts(page,false,true)" /></div>
        </div>
        <div class="cost-actionbar" :class="{'cost-actionbar-selected':selected.length>0}" aria-label="成本操作">
          <div v-if="selected.length" class="cost-batch-controls">
            <span class="cost-selected-count">已选 <b>{{ selected.length }}</b> 款</span>
            <div class="cost-batch-input"><span aria-hidden="true">¥</span><ElInputNumber v-model="bulkCost" :min="0" :max="9999999999.99" :precision="2" :controls="false" placeholder="批量成本" aria-label="批量成本金额" :disabled="saving||costLoading" /></div>
            <ElButton :disabled="saving||costLoading" @click="applyBatch">批量应用</ElButton>
            <ElButton text type="danger" :disabled="!clearableTargets.length||saving||costLoading" title="清空勾选款号的成本，保存后为未设置，保留历史" @click="clearBatch">清空</ElButton>
          </div>
          <span v-else class="cost-action-hint"><ElIcon><EditPen /></ElIcon>直接填写成本，或勾选款号批量设置</span>
          <div class="cost-save-controls"><span class="cost-save-state" :class="{'cost-save-pending':dirty}" role="status"><span class="cost-state-dot"/>{{ dirty?changes.length+' 款未保存':'暂无修改' }}</span><ElButton type="primary" :disabled="!dirty||saving||costLoading" :loading="saving" @click="previewSave">保存成本（{{ changes.length }}）</ElButton></div>
        </div>
      </div>
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
      <p v-if="reportOutdated" class="finance-rate-notice" role="status">{{ reportCostChanged?'整款成本已修改，请重新查询后导出；下方仍为上次查询结果。':reportRateChanged?'汇率已修改，请重新查询后导出；下方结果仍使用汇率 '+result.filters.exchangeRate+'。':'条件已修改，查询后更新；下方仍为上次查询结果。' }}</p>
      <div class="report-context"><span>首次成本补算历史，后续按下单时间匹配 · 不含运费及其他费用</span><ElPopover trigger="click" placement="bottom-start" :width="340" popper-style="max-width:calc(100vw - 32px)"><template #reference><ElButton text aria-label="核算说明"><ElIcon><QuestionFilled /></ElIcon>核算说明</ElButton></template><div class="finance-cost-help">每款首次填写成本时补算此前订单；之后改价只用于保存后的新订单，已有订单按对应历史成本核算。销售额使用订单成交价格；美元按本次核算汇率折算，人民币原币金额直接计入，不使用订单报价汇率重新折算。清空后的新订单为未设置成本，再次填写不补算清空期间。<br/>不含运费、税费及其他费用；包含未付款订单时不代表实际回款。人民币折算逐订单商品行四舍五入至分后汇总。<br/>导出包含全部筛选结果及完整字段，不限当前分页，使用导出时的数据库快照核算。</div></ElPopover></div>
      <template v-if="result">
        <div class="finance-summary" aria-label="核算金额汇总">
          <article><span>商品销售额 · 原币</span><strong>${{ result.summary.salesUsd }} <small>USD</small></strong><small>¥{{ result.summary.nativeSalesCny }} CNY 原币</small><small>折合 ¥{{ result.summary.salesCny }} CNY</small></article>
          <article><span>商品成本 <small>CNY</small></span><strong :class="{'summary-incomplete':result.summary.totalCostCny===null}">{{ result.summary.totalCostCny===null?'待补全':'¥'+result.summary.totalCostCny }}</strong><small v-if="result.summary.totalCostCny===null">已知成本 ¥{{ result.summary.knownCostCny }}</small><small v-else>按下单时的历史成本核算</small></article>
          <article><span>商品毛利 <small>CNY</small></span><strong :class="{'summary-incomplete':result.summary.profitCny===null}">{{ result.summary.profitCny===null?'待补全':'¥'+result.summary.profitCny }}</strong><small v-if="result.summary.profitCny===null">已设置部分 ¥{{ result.summary.knownProfitCny }}</small><small v-else>折合销售额 − 商品成本</small></article>
        </div>
        <div class="report-quantity-summary"><span>{{ result.summary.orderCount }} 个订单</span><span>{{ result.summary.quantity }} 件商品</span><span v-if="result.summary.missingQuantity" class="report-missing" role="status">{{ result.summary.missingQuantity }} 件成本未设置 · 完整成本与毛利待补全</span></div>
        <p class="report-result-meta">{{ result.filters.dateFrom }} — {{ result.filters.dateTo }}（北京时间） · 汇率 {{ result.filters.exchangeRate }} · 生成 {{ dateTime(result.generatedAt) }}</p>
        <div class="report-table-scroll"><AdaptiveTable class="finance-report-table" :data="result.items" v-loading="reportLoading" row-key="rowKey" size="small" empty-text="暂无符合条件的订单商品">
          <ElTableColumn type="expand" width="36"><template #default="{row}"><div class="line-detail"><div class="report-row-context"><span>折合销售额 <b>¥{{ row.salesCny }} CNY</b></span><span>单件成本区间 <b>{{ costRange(row) }} CNY</b></span></div><AdaptiveTable :data="row.lines" max-height="420" size="small">
            <ElTableColumn prop="orderNo" label="订单号" min-width="230"/><ElTableColumn prop="customerName" label="客户" min-width="130"/><ElTableColumn prop="accountName" label="商城账号" min-width="130"/><ElTableColumn prop="salesperson" label="业务员" width="100"/>
            <ElTableColumn label="下单时间" width="175"><template #default="{row:line}">{{ dateTime(line.createdAt) }}</template></ElTableColumn>
            <ElTableColumn prop="quantity" label="数量" width="70"/><ElTableColumn label="原币销售额" width="145" align="right"><template #default="{row:line}">{{ line.currency }} {{ line.originalAmount }}</template></ElTableColumn>
            <ElTableColumn label="单件成本 CNY" width="120" align="right"><template #default="{row:line}">{{ line.unitCostCny??'未设置' }}</template></ElTableColumn><ElTableColumn label="成本生效时间" width="175"><template #default="{row:line}">{{ line.costEffectiveAt?dateTime(line.costEffectiveAt):'—' }}<small v-if="line.costMatch==='首次成本补算'" class="cost-history-note">首次成本补算</small></template></ElTableColumn>
            <ElTableColumn label="成本 CNY" width="110" align="right"><template #default="{row:line}">{{ line.costCny??'待补全' }}</template></ElTableColumn><ElTableColumn label="商品毛利 CNY" width="120" align="right"><template #default="{row:line}">{{ line.profitCny??'待补全' }}</template></ElTableColumn>
          </AdaptiveTable></div></template></ElTableColumn>
          <ElTableColumn prop="styleCode" label="款号" min-width="125"/><ElTableColumn prop="sku" label="颜色 SKU" min-width="160"/><ElTableColumn prop="sizeCode" label="尺码" width="90"/><ElTableColumn prop="quantity" label="销量" width="80"/>
          <ElTableColumn label="原币销售额" min-width="155" align="right"><template #default="{row}"><span>USD {{ row.salesUsd }}</span><small class="cost-history-note">CNY {{ row.nativeSalesCny }}</small></template></ElTableColumn>
          <ElTableColumn label="成本 CNY" min-width="135" align="right"><template #default="{row}">{{ row.totalCostCny??('已知 '+row.knownCostCny) }}<small v-if="row.missingQuantity" class="missing">{{ row.missingQuantity }} 件待补全</small></template></ElTableColumn>
          <ElTableColumn label="毛利 CNY" min-width="135" align="right"><template #default="{row}">{{ row.profitCny??'待补全' }}</template></ElTableColumn>
        </AdaptiveTable></div>
        <ElPagination class="finance-gap" :current-page="result.page" :page-size="25" :total="result.total" layout="total, prev, pager, next" @current-change="page=>queryReport(page,true)" />
      </template><div v-else class="report-empty" role="status">{{ rateValid?'选择条件后点击“查询核算”':'填写核算汇率，选择条件后查询' }}</div>
    </template>
  </section>
  </template>
  <FinanceCostImportDialog v-model="costImportOpen" @saved="costImportSaved" />
  <ElDialog v-model="previewOpen" title="确认保存整款成本" width="min(760px, 95vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="preview"><ElAlert :title="preview.changes.some(row=>row.initialCost)?`首次填写的款号将补算此前 ${preview.affectedOrders} 个有效订单；已设置过成本的款号仅从保存时间起变更，不覆盖旧订单。清空后的历史区间不补算，全部记录保留。`:'本次均为后续修改，仅用于保存后的新订单；已有订单继续按对应历史成本核算。清空后仅影响新订单，全部历史记录保留。'" type="info" :closable="false"/>
      <AdaptiveTable :data="preview.changes" max-height="430"><ElTableColumn prop="styleCode" label="款号" min-width="140"/><ElTableColumn label="原成本 CNY"><template #default="{row}">{{ row.oldCostCny??'未设置' }}</template></ElTableColumn><ElTableColumn label="新成本 CNY"><template #default="{row}">{{ row.costCny??'未设置' }}</template></ElTableColumn><ElTableColumn label="生效范围" min-width="160"><template #default="{row}">{{ row.initialCost?'含历史订单':'保存后的新订单' }}</template></ElTableColumn></AdaptiveTable>
    </template><template #footer><ElButton :disabled="saving" @click="previewOpen=false">返回修改</ElButton><ElButton type="primary" :loading="saving" @click="commitCosts">确认保存</ElButton></template>
  </ElDialog>
  <ElDialog v-model="historyOpen" :title="historyTitle" width="min(680px,95vw)" class="cost-history-dialog" @close="closeHistory">
    <div v-if="historyError" class="cost-history-error"><ElAlert :title="historyError" type="error" :closable="false"/><ElButton :loading="historyLoading" @click="loadHistory(historyPage)">重试</ElButton></div>
    <AdaptiveTable v-if="historyLoading||history?.items.length" :data="history?.items||[]" v-loading="historyLoading" size="small" max-height="55vh" row-key="id">
      <ElTableColumn label="生效时间" min-width="175"><template #default="{row}">{{ dateTime(row.effectiveAt) }}<small v-if="row.initialCost" class="cost-history-note">首次设置 · 含历史订单</small></template></ElTableColumn>
      <ElTableColumn label="原成本 CNY" min-width="110"><template #default="{row}">{{ row.oldCostCny??'未设置' }}</template></ElTableColumn>
      <ElTableColumn label="新成本 CNY" min-width="110"><template #default="{row}">{{ row.costCny??'未设置' }}</template></ElTableColumn>
      <ElTableColumn label="操作者" min-width="110"><template #default="{row}">{{ row.actor?.name||'—' }}</template></ElTableColumn>
    </AdaptiveTable>
    <ElEmpty v-else-if="!historyError" description="暂无成本变动" :image-size="80"/>
    <ElPagination v-if="history&&!historyError&&history.total>0" class="finance-gap" :current-page="history.page" :page-size="20" :total="history.total" layout="total, prev, pager, next" @current-change="loadHistory"/>
  </ElDialog>
</template>

<script setup>
import { errorMessage } from '../utils/adminErrors.js';
import MobileActionMenu from '../components/MobileActionMenu.vue';
import AdaptiveTable from "../components/AdaptiveTable";
import ResponsiveFilters from "../components/ResponsiveFilters.vue";
import { useResponsive } from '../composables/responsive';
const { isPhone } = useResponsive();
import { authenticatedFetch } from '../authTransport';
import { responseError } from '../utils/adminErrors.js';

import {computed,onMounted,onBeforeUnmount,reactive,ref} from 'vue';
import {onBeforeRouteLeave,RouterLink} from 'vue-router';
import {useAdminAuthStore} from '../stores/auth';
const auth=useAdminAuthStore();
import {ElMessage} from 'element-plus';
import {ArrowDown,ArrowRight,InfoFilled,DataAnalysis,QuestionFilled,Search,Clock,EditPen} from '@element-plus/icons-vue';
import {api,save,confirm,dateTime,statusNames} from '../composables/workbench';
import {API_BASE} from '../api';
import FinanceCostImportDialog from '../components/FinanceCostImportDialog.vue';
import {financeCostPageSize,financeCostFilters,financeCostKey,financeToday,financeCodes,financeActiveStates,financeReportDates,financeReportKey,costChanges,costValue,batchTargets,clearBatchTargets} from '../utils/finance';
const tab=ref('report'),error=ref(''),options=reactive({customers:[],salespeople:[],styles:[],categories:[]});
const activeStates=financeActiveStates,today=financeToday();
const filters=reactive({...financeReportDates(today),customerName:'',customerId:null,salespersonIds:[],styleCodes:[],statuses:[...activeStates],exchangeRate:null});
const advancedOpen=ref(false);
const mobileToolsOpen=ref(false),mobileExplanationOpen=ref(false),mobileReportOpen=ref(false),mobileReportRow=ref(null),mobileBatchMode=ref(false);
async function applyMobileFinanceFilters(){if(tab.value==='report'){if(rateLoading.value||!rateValid.value)return;await queryReport(1);}else await loadCosts(1);}
async function resetMobileCosts(){if(costLoading.value||saving.value||!await leaveDraft())return;Object.assign(costQuery,{keyword:'',styleCodes:'',category:'',missingOnly:false});await loadCosts(1,true);}
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
  catch(e){rateLoaded.value=false;rateError.value='保存的汇率读取失败：'+errorMessage(e);}
  finally{rateLoading.value=false;}
}
async function saveRate(){
  if(rateSaving.value||!rateLoaded.value||!rateValid.value)return;
  rateSaving.value=true;rateError.value='';
  try{const data=await save('finance/preferences',{exchangeRate:filters.exchangeRate,version:rateVersion.value});savedRate.value=Number(data.exchangeRate);rateVersion.value=data.version;ElMessage.success('公共汇率已保存，所有财务账号共用');}
  catch(e){
    if(e.status===409){await loadRate(false);rateError.value=rateLoaded.value?`公共汇率已被其他用户或窗口更新，最新保存值为 ${savedRate.value}。当前输入已保留，核对后可再次保存。`:rateError.value;}
    else rateError.value=errorMessage(e);
  }finally{rateSaving.value=false;}
}
const costQuery=reactive({keyword:'',styleCodes:'',category:'',missingOnly:false});
const costPage=ref(1),costTotal=ref(0),groups=ref([]),selected=ref([]),bulkCost=ref(null),costLoading=ref(false),saving=ref(false);
const costWorkspace=ref(null);
const appliedCostQuery=ref(null),costExporting=ref(false),costImportOpen=ref(false);
const costOutdated=computed(()=>Boolean(appliedCostQuery.value)&&financeCostKey(costQuery)!==financeCostKey(appliedCostQuery.value));
const changes=computed(()=>costChanges(groups.value)),dirty=computed(()=>changes.value.length>0);
const costColumns=computed(()=>{const rows=groups.value;if(!rows.length)return [];if(rows.length===1)return [rows];const middle=Math.ceil(rows.length/2);return [rows.slice(0,middle),rows.slice(middle)];});
function focusCostInput(step){
  const inputs=[...(costWorkspace.value?.querySelectorAll('.cost-amount-cell input')||[])],index=inputs.indexOf(document.activeElement);
  if(index<0)return;
  const next=inputs[index+step];if(next&&!next.disabled){next.focus();next.select();}else inputs[index].blur();
}
const allSelected=computed(()=>groups.value.length>0&&groups.value.every(g=>selected.value.includes(g.styleCode)));
const clearableTargets=computed(()=>clearBatchTargets(groups.value,selected.value));
const isChanged=group=>costValue(group.draftCost)!==group.costCny;
const selectStyle=(code,value)=>{selected.value=value?[...new Set([...selected.value,code])]:selected.value.filter(v=>v!==code);};
const selectAll=value=>{selected.value=value?groups.value.map(g=>g.styleCode):[];};
async function leaveDraft(){return !saving.value&&(!dirty.value||await confirm('有尚未保存的成本修改。确认放弃修改并离开？取消可继续编辑。'));}
onBeforeRouteLeave(leaveDraft);
function unload(event){if(dirty.value){event.preventDefault();event.returnValue='';}}
onMounted(async()=>{window.addEventListener('beforeunload',unload);await Promise.all([loadRate(),(async()=>{try{Object.assign(options,await api('finance/options'));}catch(e){error.value=errorMessage(e);}})()]);if(isPhone.value&&rateValid.value)await queryReport(1);});
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',unload);closeHistory();});
async function changeTab(value){if(value===tab.value)return;if(tab.value==='costs'&&!await leaveDraft())return;tab.value=value;if(value==='costs')await loadCosts(1,true);else groups.value=[];}
async function loadCosts(page=1,discard=false,existing=false){
  if(costLoading.value||saving.value||(!discard&&!await leaveDraft()))return;
  costLoading.value=true;error.value='';
  const query=existing&&appliedCostQuery.value?{...appliedCostQuery.value}:financeCostFilters(costQuery);
  try{const response=await api('finance/costs?'+new URLSearchParams({...query,page,pageSize:financeCostPageSize}));
    groups.value=response.items.map(g=>({...g,draftCost:g.costCny===null?undefined:Number(g.costCny)}));
    costPage.value=response.page;costTotal.value=response.total;selected.value=[];appliedCostQuery.value=query;
  }catch(e){error.value=errorMessage(e);}finally{costLoading.value=false;}
}
async function exportCosts(){
  if(!appliedCostQuery.value||costOutdated.value||costLoading.value||costExporting.value)return;
  costExporting.value=true;error.value='';
  try{
    const response=await authenticatedFetch(`${API_BASE}/api/admin/finance/costs/export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(appliedCostQuery.value)});
    if(!response.ok)throw responseError(response.status,await response.json().catch(()=>({})),response.headers.get('Retry-After'),'成本表导出失败');
    const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='商品成本.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){error.value=errorMessage(e);}finally{costExporting.value=false;}
}
function openCostImport(){
  if(saving.value||costLoading.value)return;
  if(dirty.value){ElMessage.warning('有未保存的成本修改，请先保存，或手动撤销修改后再导入。当前草稿已保留。');return;}
  costImportOpen.value=true;
}
async function costImportSaved(){reportCostChanged.value=Boolean(result.value);await loadCosts(costPage.value,true,true);}
async function applyBatch(){
  if(saving.value||costLoading.value)return;
  if(bulkCost.value===null||bulkCost.value===undefined||!Number.isFinite(bulkCost.value)){error.value='请填写批量成本';return;}
  const targets=batchTargets(groups.value,selected.value);
  if(!targets.length)return;
  const count=targets.filter(g=>costValue(g.draftCost)!==null&&costValue(g.draftCost)!==costValue(bulkCost.value)).length;
  if(count&&!await confirm(`将覆盖 ${count} 款已有的不同成本，共应用 ${targets.length} 款。仅修改页面草稿，保存后才生效。`))return;
  targets.forEach(g=>g.draftCost=bulkCost.value);error.value='';
}
async function clearBatch(){
  if(saving.value||costLoading.value)return;
  const targets=clearableTargets.value;
  if(!targets.length)return;
  if(!await confirm(`将清空已勾选的 ${targets.length} 款成本，改为未设置。仅修改页面草稿；保存后仅新订单按未设置成本核算，旧订单仍使用当时的历史成本，历史记录保留。`))return;
  targets.forEach(g=>g.draftCost=undefined);error.value='';
  ElMessage.success(`已清空 ${targets.length} 款草稿${dirty.value?'，保存成本后生效':'，已保存数据未改变'}`);
}
const preview=ref(null),previewOpen=ref(false);let pendingSave=null;
async function previewSave(){
  error.value='';
  saving.value=true;
  try{const body={changes:changes.value};preview.value=await save('finance/costs/preview',body,'POST');pendingSave={...body,previewHash:preview.value.previewHash,requestId:crypto.randomUUID()};previewOpen.value=true;}
  catch(e){error.value=errorMessage(e);}finally{saving.value=false;}
}
async function commitCosts(){
  saving.value=true;error.value='';
  try{await save('finance/costs/save',pendingSave,'POST');previewOpen.value=false;reportCostChanged.value=Boolean(result.value);ElMessage.success('成本已保存');saving.value=false;await loadCosts(costPage.value,true,true);}
  catch(e){error.value=errorMessage(e);if(e.status)previewOpen.value=false;}finally{saving.value=false;}
}
const historyOpen=ref(false),history=ref(null),historyTitle=ref(''),historyStyle=ref(''),historyLoading=ref(false),historyError=ref(''),historyPage=ref(1);
let historyRequest=0,historyController;
function closeHistory(){++historyRequest;historyController?.abort();historyLoading.value=false;history.value=null;}
async function showHistory(group){
  closeHistory();historyStyle.value=group.styleCode;historyTitle.value=`成本历史 · ${group.styleCode}`;
  historyError.value='';historyOpen.value=true;await loadHistory(1);
}
async function loadHistory(page=1){
  if(!historyOpen.value)return;
  const id=++historyRequest;historyController?.abort();historyController=new AbortController();historyPage.value=page;historyLoading.value=true;historyError.value='';history.value=null;
  const params={styleCode:historyStyle.value,page};
  try{const data=await api('finance/costs/history?'+new URLSearchParams(params),{signal:historyController.signal,skipGlobalLoading:true});if(id===historyRequest&&historyOpen.value){history.value=data;}}
  catch(e){if(e.name!=='AbortError'&&id===historyRequest&&historyOpen.value)historyError.value=errorMessage(e);}
  finally{if(id===historyRequest)historyLoading.value=false;}
}
const result=ref(null),reportLoading=ref(false),exporting=ref(false),reportCostChanged=ref(false);
const reportRateChanged=computed(()=>Boolean(result.value)&&(!rateValid.value||filters.exchangeRate!==Number(result.value.filters.exchangeRate)));
const reportOutdated=computed(()=>Boolean(result.value)&&(reportCostChanged.value||financeReportKey(filters)!==financeReportKey(result.value.filters)));
async function queryReport(page=1,existing=false){
  if(reportLoading.value)return;reportLoading.value=true;error.value='';
  try{const query=existing?result.value.filters:{...filters,styleCodes:financeCodes(filters.styleCodes.join(','))};
    const data=await save('finance/reports/query',{...query,page,pageSize:25},'POST');
    data.items.forEach(r=>r.rowKey=JSON.stringify([r.styleCode,r.productId,r.sku,r.sizeCode]));result.value=data;reportCostChanged.value=false;
  }catch(e){error.value=errorMessage(e);}finally{reportLoading.value=false;}
}
async function exportReport(){
  if(!result.value||reportOutdated.value||reportLoading.value||exporting.value)return;
  exporting.value=true;error.value='';
  try{const response=await authenticatedFetch(`${API_BASE}/api/admin/finance/reports/export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(result.value.filters)});
    if(!response.ok)throw responseError(response.status,await response.json().catch(()=>({})),response.headers.get('Retry-After'),'导出失败');
    const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='财务成本核算.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){error.value=errorMessage(e);}finally{exporting.value=false;}
}
</script>

<style scoped>
.finance-panel{background:#fff;padding:22px;border:1px solid #e1e6ee;border-radius:10px;min-width:0}.finance-tabs{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.finance-tabs{border-bottom:1px solid #e8edf4}.finance-filters{display:flex;align-items:flex-end;flex-wrap:wrap;gap:14px;padding:20px 0}.finance-filters>label:not(.el-checkbox){display:flex;flex-direction:column;gap:7px;color:#596b83;font-size:12px}.finance-filters :deep(.el-select),.finance-filters :deep(.el-date-editor),.finance-filters :deep(.el-input-number){width:100%}.finance-gap{margin-top:18px}.cost-changed{background:#fff8e7}.line-detail{padding:16px;background:#f6f8fb}.missing{display:block;color:#c17820;font-size:11px}.finance-panel :deep(.el-checkbox__inner){width:20px;height:20px}.finance-panel :deep(.el-checkbox__inner:after){left:7px;top:4px}.finance-panel :deep(.el-checkbox){min-height:32px}.finance-panel :deep(.el-table .cell){overflow-wrap:anywhere}.cost-expanded{transform:rotate(180deg)}
.cost-history-error{display:flex;align-items:center;gap:10px}.cost-history-error>.el-alert{flex:1}.cost-history-dialog :deep(.el-table){font-size:12px}
.cost-history-note{display:block;font-size:11px;color:#8391a5;line-height:1.6}
@media(max-width:700px){.finance-panel{padding:12px}.finance-panel :deep(.el-pagination){overflow:auto}}
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
@media(max-width:700px){.finance-report-filters{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.finance-report-filters>label:not(.el-checkbox){width:auto}.report-date-field{grid-column:1/-1}.finance-tab-nav{width:100%}.finance-tabs .finance-header-actions :deep(.el-button){flex:none}.finance-rate-control{width:100%}.finance-rate-control :deep(.el-input-number){flex:1;width:auto}.finance-header-actions{gap:10px}}
.finance-cost-help{font-size:12px;line-height:1.8;color:#61738a}
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

<style scoped>
/* A compact ledger, not a full-width form stretched across the page. */
.cost-workspace{padding-top:20px;color:#334155;font-size:12px;--cost-line:#e7ecf2;--cost-muted:#8190a5}
.finance-cost-mode .finance-cost-filters{display:grid;grid-template-columns:minmax(200px,1.2fr) minmax(180px,1fr) minmax(140px,.65fr) auto;align-items:end;gap:14px;padding:0 0 20px}
.finance-cost-mode .finance-cost-filters>label{width:auto;min-width:0;gap:6px;font-size:11px;color:#6e7f95}
.finance-cost-filters :deep(.el-input__inner),.finance-cost-filters :deep(.el-select__placeholder){font-size:12px}
.cost-filter-actions{display:flex;align-items:center;gap:14px;height:32px;white-space:nowrap}
.cost-filter-actions :deep(.el-checkbox__label){font-size:12px;padding-left:6px}.cost-filter-actions>.el-button{margin:0;padding-inline:18px}
.cost-sheet{border:1px solid var(--cost-line);border-radius:9px;overflow:hidden;background:#fff}
.cost-sheet-caption{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 16px;background:#fafbfd;border-bottom:1px solid var(--cost-line)}
.cost-sheet-selection,.cost-sheet-meta{display:flex;align-items:center;gap:16px;min-width:0}
.cost-sheet-selection :deep(.el-checkbox__label){font-size:12px;color:#50627a;padding-left:8px}
.cost-result-count{color:var(--cost-muted);border-left:1px solid #e0e6ee;padding-left:16px;white-space:nowrap;font-size:11px}.cost-result-count b{font-weight:500;color:#50627a}
.cost-sheet-meta{gap:3px;color:var(--cost-muted);font-size:11px;white-space:nowrap}.cost-sheet-meta i{font-style:normal;margin:0 6px;color:#c0c9d4}.cost-sheet-meta :deep(.el-button){padding:4px;height:24px;width:24px;color:#8999ac}
.cost-ledger{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));min-height:100px;padding:0 16px}
.cost-ledger-column{min-width:0;padding-right:20px}.cost-ledger-column+ .cost-ledger-column{border-left:1px solid var(--cost-line);padding-left:20px;padding-right:0}
.cost-ledger-single{grid-template-columns:1fr}.cost-ledger-single .cost-ledger-column{padding-right:0;max-width:720px}
.style-cost-table{width:100%;border-collapse:collapse;table-layout:fixed;text-align:left;font-size:12px}
.cost-select-col{width:34px}.cost-amount-col{width:162px}.cost-history-col{width:72px}
.style-cost-table th{height:36px;font-weight:400;color:#8a98aa;font-size:11px;border-bottom:1px solid #edf1f5}
.style-cost-table th,.style-cost-table td{padding:7px 8px;box-sizing:border-box;vertical-align:middle}
.style-cost-table td{height:48px;border-bottom:1px solid #edf1f5;transition:background-color .12s}
.style-cost-table tr:last-child td{border-bottom:0}.style-cost-table tbody tr:hover{background:#f8fafc}
.style-cost-table .style-select{padding-left:0;padding-right:0}
.style-cost-table .style-code{color:#334155;font-weight:600;letter-spacing:.15px;overflow-wrap:anywhere}
.style-code>span:first-child{vertical-align:middle}.cost-edit-dot{display:inline-block;width:5px;height:5px;background:#c99135;border-radius:50%;margin-left:7px;vertical-align:middle}
.style-cost-table .cost-selected{background:#f5f8ff}.style-cost-table .cost-changed{background:#fffbf1}.style-cost-table .cost-changed:hover{background:#fff8e6}
.style-cost-table .cost-amount-heading{padding-left:8px}.cost-input-shell,.cost-batch-input{display:flex;align-items:center;border:1px solid #e0e6ee;border-radius:5px;background:#fff;min-width:0;transition:border-color .15s,box-shadow .15s}
.cost-input-shell:hover,.cost-batch-input:hover{border-color:#b9c8dc}.cost-input-shell:focus-within,.cost-batch-input:focus-within{border-color:#407cf5;box-shadow:0 0 0 2px #eaf1ff}
.cost-currency,.cost-batch-input>span{padding-left:10px;color:#91a0b4;font-size:12px;flex-shrink:0}
.cost-input-shell :deep(.el-input-number),.cost-batch-input :deep(.el-input-number){width:100%;min-width:0;height:32px}
.cost-input-shell :deep(.el-input__wrapper),.cost-batch-input :deep(.el-input__wrapper){padding:0 10px 0 5px;background:transparent;box-shadow:none!important;border-radius:5px}
.cost-input-shell :deep(.el-input__inner),.cost-batch-input :deep(.el-input__inner){height:30px;text-align:right;font-size:12px;font-variant-numeric:tabular-nums;color:#34455f}
.cost-input-shell :deep(.el-input__inner::placeholder),.cost-batch-input :deep(.el-input__inner::placeholder){font-size:11px;color:#9aa7b8;font-weight:400}
.cost-input-empty{border-color:#e9edf3;background:#fafbfd}.cost-input-empty .cost-currency{color:#b5becb}
.cost-history-cell{text-align:right}.cost-history-button :deep(.el-icon){font-size:13px;margin-right:4px}.style-cost-table .cost-history-button{font-size:11px;font-weight:400;color:#7e8ea3;padding:6px 0;height:32px}
.style-cost-table .cost-history-button:hover{color:#2563eb;background:transparent}
.style-cost-empty{grid-column:1/-1;text-align:center;padding:50px 12px;color:var(--cost-muted)}
.cost-sheet-bottom{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:54px;padding:8px 16px;border-top:1px solid var(--cost-line);color:#95a1b1;font-size:11px}
.cost-sheet-bottom :deep(.el-pagination){padding:0;font-size:12px}.cost-sheet-bottom :deep(.el-pager li){min-width:28px;font-size:12px}
.cost-actionbar{position:sticky;bottom:16px;z-index:3;display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-top:14px;padding:12px 14px;border:1px solid var(--cost-line);border-radius:8px;background:#fff;box-shadow:0 4px 16px #24385005}
.cost-actionbar-selected{border-color:#dce6f6;background:#fbfcff}.cost-batch-controls,.cost-save-controls{display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap}
.cost-selected-count{color:#58739b;white-space:nowrap;font-size:11px}.cost-selected-count b{font-weight:600;color:#2f65b8}
.cost-batch-input{width:126px}.cost-batch-controls>.el-button+.el-button{margin-left:0}.cost-batch-controls>.el-button{font-size:12px;height:32px;padding:8px 12px}
.cost-save-controls{margin-left:auto;gap:14px}.cost-save-controls>.el-button{margin:0;height:32px;padding-inline:18px;font-size:12px}
.cost-save-state{display:flex;align-items:center;gap:5px;color:#99a4b3;white-space:nowrap;font-size:11px}.cost-state-dot{width:5px;height:5px;background:#c2ccd8;border-radius:50%}.cost-save-pending{color:#b5802e}.cost-save-pending .cost-state-dot{background:#d6a247}
.cost-action-hint{display:flex;align-items:center;gap:6px;color:#93a0b1;font-size:11px}.cost-action-hint :deep(.el-icon){font-size:13px}
.finance-cost-mode :deep(.el-checkbox__inner){width:17px;height:17px;border-radius:3px}.finance-cost-mode :deep(.el-checkbox__inner:after){left:5px;top:2px}.finance-cost-mode :deep(.el-checkbox){height:32px;min-height:32px;margin-right:0}
.cost-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:1250px){.cost-actionbar{position:static}.finance-cost-mode .finance-cost-filters{grid-template-columns:repeat(3,minmax(0,1fr))}.cost-filter-actions{grid-column:1/-1;justify-content:flex-end}.cost-ledger{grid-template-columns:1fr}.cost-ledger-column,.cost-ledger-column+ .cost-ledger-column{border-left:0;padding:0}.cost-ledger-column+ .cost-ledger-column{border-top:1px solid var(--cost-line)}.cost-ledger-column+ .cost-ledger-column thead{display:none}.cost-amount-col{width:190px}.cost-history-col{width:80px}}
@media(max-width:700px){.cost-workspace{padding-top:16px}.finance-cost-mode .finance-cost-filters{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding-bottom:16px}.finance-cost-mode .finance-cost-filters>label:first-child{grid-column:1/-1}.cost-filter-actions{justify-content:space-between;gap:8px;grid-column:1/-1}.cost-sheet-caption{padding:8px 12px;gap:8px;flex-wrap:wrap}.cost-sheet-selection{gap:10px}.cost-result-count{padding-left:10px}.cost-sheet-meta{gap:0}.cost-sheet-meta>span{font-size:10px}.cost-shared-label{display:none}.cost-sheet-meta i{margin:0 3px}.cost-ledger{padding:0 10px}.cost-select-col{width:26px}.cost-amount-col{width:112px}.cost-history-col{width:42px}.style-cost-table th,.style-cost-table td{padding:6px 5px}.style-cost-table td{height:52px}.style-cost-table .style-code{font-size:11px}.style-code>span:first-child{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;max-height:34px;line-height:17px}.style-cost-table .style-code{position:relative}.style-code>span:first-child{padding-right:6px}.style-code .cost-edit-dot{position:absolute;right:3px;top:calc(50% - 2px);margin:0;width:4px;height:4px}.cost-currency{padding-left:7px}.cost-input-shell :deep(.el-input__wrapper){padding-right:7px}.style-cost-table .cost-history-button{font-size:11px}.cost-history-button :deep(.el-icon){display:none}.cost-sheet-bottom{padding:8px 10px;gap:4px}.cost-pagination-hint{display:none}.cost-actionbar{position:static;gap:12px;padding:12px;margin-top:12px}.cost-action-hint{width:100%}.cost-batch-controls{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.cost-selected-count{grid-column:1;grid-row:1;min-width:46px}.cost-batch-input{grid-column:1;grid-row:2;width:auto;min-width:95px;max-width:none}.cost-batch-controls>.el-button{padding-inline:8px}.cost-batch-controls>.el-button:nth-last-child(2){grid-column:2;grid-row:2}.cost-batch-controls>.el-button:last-child{grid-column:2;grid-row:1;justify-self:end}.cost-save-controls{width:100%;margin:0;justify-content:space-between;padding-top:10px;border-top:1px solid var(--cost-line);gap:8px}.cost-save-controls>.el-button{padding-inline:14px}}
</style>

<style scoped>
@media(max-width:767px){.mobile-finance{color:#182b49;padding-bottom:22px}.mf-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 20px}.mf-heading h1{font-size:26px;letter-spacing:-.04em;margin:0}.mf-heading p{color:#8c9ab0;font-size:11px;margin:7px 0 0}.mf-tabs{display:flex;border-bottom:1px solid #e5ebf5;margin-bottom:17px;gap:28px}.mf-tabs button{border:0;border-bottom:2px solid transparent;background:none;color:#9aabc3;font-size:13px;min-height:44px;padding:6px 0 12px}.mf-tabs button.active{color:#2f69eb;border-bottom-color:#2f69eb;font-weight:600}.mf-filter-line{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:14px}.mf-filter-line>button{display:flex;align-items:center;gap:7px;color:#8fa3c0;border:0;background:none;font-size:11px;padding:8px 0}.mf-filter-chips{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:12px}.mf-filter-chips :deep(.el-tag){max-width:100%;font-size:10px}.mf-filter-chips :deep(.el-tag__content){overflow:hidden;text-overflow:ellipsis}.mf-stale{display:flex;justify-content:space-between;align-items:center;border:1px solid #f2e6ce;background:#fffaf0;color:#a88a56;font-size:11px;padding:8px 12px;border-radius:10px;margin:10px 0}.mf-hero{background:#fff;border:1px solid #e7edf7;border-radius:19px;padding:21px 20px 0}.mf-hero-caption{display:flex;justify-content:space-between;align-items:center;gap:8px;color:#91a4bf;font-size:11px}.mf-hero-caption :deep(.el-tag){font-size:10px}.mf-hero-amount{display:block;color:#213e69;font-size:32px;line-height:1.4;letter-spacing:-.05em;font-weight:650;margin:13px 0 5px;overflow-wrap:anywhere}.mf-original{font-size:11px;color:#7891b5;line-height:1.8;margin:0}.mf-original span{color:#a3b0c4}.mf-profit-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:19px 0;margin-top:14px;border-top:1px solid #eef2f8}.mf-profit-grid>div{display:flex;flex-direction:column;gap:7px;min-width:0}.mf-profit-grid>div+div{padding-left:17px;border-left:1px solid #eef2f8}.mf-profit-grid span{font-size:11px;color:#93a5bd}.mf-profit-grid strong{font-size:18px;letter-spacing:-.04em;color:#46648d;overflow-wrap:anywhere}.mf-profit-grid strong.is-profit{color:#2d9381}.mf-profit-grid small{font-size:10px;color:#b3a078}.mf-hero footer{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;background:#fafcff;border-top:1px solid #eef2f8;margin:0 -20px;padding:12px 20px;border-radius:0 0 19px 19px;color:#90a3bf;font-size:11px}.mf-hero footer small{font-size:10px;color:#a9b6c9}.mf-missing{display:flex;gap:6px;align-items:flex-start;color:#ac956b;font-size:11px;line-height:1.8;margin:13px 2px}.mf-missing :deep(.el-icon){flex-shrink:0;margin-top:3px}.mf-section{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:23px 0 13px}.mf-section h2{font-size:13px;font-weight:600;margin:0}.mf-section small{font-size:10px;color:#a2b0c6;font-weight:400}.mf-report-list{display:flex;flex-direction:column;gap:11px}.mf-report-card{display:flex;flex-direction:column;text-align:left;width:100%;border:1px solid #e8edf6;border-radius:17px;background:#fff;padding:15px 16px;color:inherit;gap:6px}.mf-report-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.mf-report-top>strong{font-size:14px}.mf-report-top>span{display:flex;align-items:center;gap:8px;font-size:11px;color:#8c9fba}.mf-report-sku{font-size:11px;color:#91a3bd;overflow-wrap:anywhere}.mf-report-sku i{font-style:normal;margin:0 5px}.mf-report-money{display:grid;grid-template-columns:1fr 1fr;gap:12px;width:100%;margin-top:9px;padding-top:12px;border-top:1px solid #f0f3f8}.mf-report-money>span{display:flex;flex-direction:column;gap:5px;min-width:0}.mf-report-money small{font-size:10px;color:#a2b0c5}.mf-report-money b{font-size:12px;color:#627d9f;font-weight:550;overflow-wrap:anywhere}.mf-report-money em{font-size:10px;color:#b09b76;font-style:normal}.mf-pagination{justify-content:center;margin-top:20px;max-width:100%;overflow:auto}.mf-generated{font-size:10px;color:#b0bdce;text-align:center;margin-top:17px}.mf-ledger{background:#fff;border:1px solid #e7edf6;border-radius:17px;overflow:hidden;min-height:60px}.mf-ledger-row{display:flex;align-items:center;gap:8px;padding:14px 10px 14px 15px;min-height:76px;border-bottom:1px solid #eff3f8}.mf-ledger-row:last-child{border:0}.mf-ledger-row.is-dirty{background:#fbfcff}.mf-ledger-row :deep(.el-checkbox){margin:0}.mf-ledger-code{display:flex;flex-direction:column;gap:5px;flex:1;min-width:0}.mf-ledger-code>a,.mf-ledger-code>strong{font-size:13px;font-weight:600;color:#486b9a;overflow-wrap:anywhere}.mf-ledger-code>small{font-size:10px;color:#a7b6cb}.mf-ledger-row.is-dirty .mf-ledger-code>small{color:#b89b65}.mf-ledger-input{width:104px;display:flex;align-items:center;background:#f7f9fd;border:1px solid #e9eef7;border-radius:9px;padding-left:9px;flex:0 0 104px}.mf-ledger-input>span{font-size:11px;color:#a3b3cc}.mf-ledger-input :deep(.el-input-number){width:100%;min-width:0;height:36px}.mf-ledger-input :deep(.el-input__wrapper){box-shadow:none!important;background:none;padding:0 8px 0 3px}.mf-ledger-input :deep(.el-input__inner){text-align:right;font-size:15px;color:#6d89ae}.mf-ledger-input :deep(.el-input__inner::placeholder){font-size:11px;color:#b4bfd0}.mf-history-button{padding:0;width:25px;flex:0 0 25px;margin:0!important;color:#a7b6cd}.mf-batch{display:flex;align-items:center;flex-wrap:wrap;gap:8px;background:#fff;border:1px solid #e4ecfb;border-radius:13px;padding:12px;margin-top:14px;font-size:11px;color:#7c95ba}.mf-batch>.el-input-number{width:100px}.mf-batch>.el-button{margin:0}.mf-savebar{position:sticky;bottom:0;z-index:4;display:flex;justify-content:space-between;align-items:center;gap:15px;background:#fff;border:1px solid #e6edf9;border-radius:14px;padding:12px 14px;margin-top:16px;box-shadow:0 -5px 20px #274d7b08}.mf-savebar>span{font-size:11px;color:#98a9c2;display:flex;align-items:center;gap:7px}.mf-savebar i{width:5px;height:5px;border-radius:50%;background:#d0a35b}.mf-savebar>.el-button{border-radius:10px}.mf-empty{text-align:center;background:#fff;border:1px solid #e8eef7;border-radius:18px;padding:35px 16px}.mf-empty>.el-icon{font-size:32px;color:#afc5e5}.mf-empty h2{font-size:15px;margin:15px 0 8px}.mf-empty p{font-size:11px;color:#9aacc5;line-height:1.8}.mf-empty>.el-button{margin-top:10px}.mf-advanced{margin-top:12px}.mf-advanced summary{color:#8a9fbd;font-size:12px;padding:10px 0 18px}.mf-tool-note,.mf-explanation p,.mf-detail-context{font-size:12px;color:#8ca0bc;line-height:1.9}.mf-order-line{background:#fff;border:1px solid #e8eef8;border-radius:15px;padding:15px;margin:12px 0}.mf-order-line h3{font-size:13px;margin:0 0 8px;overflow-wrap:anywhere}.mf-order-line>p{font-size:12px;color:#6683aa;margin:0 0 5px}.mf-order-line>p span{color:#9aacbf}.mf-order-line>small{font-size:10px;color:#a5b3c6}.mf-order-line>div{display:flex;justify-content:space-between;gap:12px;font-size:11px;color:#7a94b5;margin:15px 0;padding-bottom:12px;border-bottom:1px solid #edf2f8}.mf-order-line>div strong{font-weight:550;color:#679f90}.mf-order-line dl{display:grid;grid-template-columns:auto 1fr;gap:9px 14px;font-size:11px;margin:0}.mf-order-line dt{color:#a6b4c8}.mf-order-line dd{margin:0;text-align:right;color:#7a92b4;overflow-wrap:anywhere}.mobile-finance :deep(.el-date-editor--daterange){width:100%;min-width:0}}
</style>

<style scoped>
@media(max-width:767px){.mf-filter-drawer :deep(.el-date-editor--daterange){width:100%;min-width:0;max-width:100%;box-sizing:border-box}.mf-filter-drawer :deep(.el-select){width:100%}.mf-ledger-row :deep(.el-checkbox__inner),.mf-section :deep(.el-checkbox__inner){width:17px;height:17px}.mf-ledger-row :deep(.el-checkbox__inner:after),.mf-section :deep(.el-checkbox__inner:after){left:5px;top:2px}.mf-section :deep(.el-checkbox){min-height:38px}.mf-ledger-row :deep(.el-checkbox){min-height:38px;flex-shrink:0}}
</style>
