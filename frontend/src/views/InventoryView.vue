<template>
  <PageHeader
    title="库存管理"
    mobile-title="库存"
    :mobile-description="`${list.total} 个颜色 SKU · 按真实尺码管理`"
    description="商品按分类顺序展示，采购入库与独立临时入库分开登记，清晰掌握尺码到货进度。"
    eyebrow="INVENTORY / 商品与库存"
    ><template v-if="isPhone"><MobileActionMenu :label="canEdit ? '库存操作' : '库存排序'"><ElButton v-if="canEdit" @click="mobileSelection = !mobileSelection; clearSelection()">{{ mobileSelection ? '退出选择模式' : '批量入库 / 打回' }}</ElButton><ElButton v-if="canEdit" :loading="exporting" @click="exportFile">导出库存</ElButton><ElButton v-if="canEdit" :loading="importing" @click="input.click()">导入库存</ElButton><ElButton @click="list.sort({prop:'stock',order:'descending'})">现货余额降序</ElButton><ElButton @click="list.sort({prop:'stock',order:'ascending'})">现货余额升序</ElButton><ElButton @click="list.sort({prop:'category',order:'ascending'})">默认分类顺序</ElButton></MobileActionMenu><input v-if="canEdit" ref="input" type="file" accept=".xlsx" hidden @change="previewFile"/></template><template v-else><template v-if="canEdit"
      ><ElButton :loading="exporting" @click="exportFile">导出库存</ElButton
      ><ElButton type="primary" :loading="importing" @click="input.click()"
        >导入库存</ElButton
      ><input
        ref="input"
        type="file"
        accept=".xlsx"
        hidden
        @change="previewFile" /></template
  ></template></PageHeader>
  <div v-if="isPhone" class="m-stock-summary"><div><span>现货余额</span><strong>{{ Number(list.summary.stock || 0).toLocaleString() }}<small>件</small></strong></div><div><span>{{ canEdit ? '欠货待处理' : '零库存尺码' }}</span><strong class="is-amber">{{ canEdit ? list.summary.shortageUnits || 0 : list.summary.zeroSizes || 0 }}<small>{{ canEdit ? '件' : '个' }}</small></strong></div></div>
  <div v-else
    class="metric-grid inventory-overview"
    :class="{'is-expanded': summaryExpanded}"
    :style="{ gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))' }"
  >
    <div class="metric">
      <span>颜色 SKU 数</span><strong>{{ list.total }}</strong>
    </div>
    <div class="metric">
      <span>现货余额合计</span><strong>{{ list.summary.stock || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric"><span>可用现货</span><strong>{{ list.summary.availableStock || 0 }}</strong></div>
    <div v-if="canEdit" class="metric"><span>欠货件数 / 尺码数</span><strong class="negative">{{ list.summary.shortageUnits || 0 }} / {{ list.summary.shortageSizeCount || 0 }}</strong></div>
    <div v-if="canEdit" class="metric">
      <span>合同未送合计</span
      ><strong>{{ list.summary.contractPending || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>待验货合计</span
      ><strong>{{ list.summary.pendingInspection || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>待打回次品</span><strong>{{ list.summary.defectivePending || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>合格合计</span
      ><strong>{{ list.summary.pendingInbound || 0 }}</strong>
    </div>
    <div class="metric">
      <span>零库存尺码数</span
      ><strong>{{ list.summary.zeroSizes || 0 }}</strong>
    </div>
    <div v-if="canEdit" class="metric">
      <span>临时待入库合计</span><strong>{{ list.summary.temporaryInbound || 0 }}</strong>
    </div>
  </div>
  <button v-if="isPhone" class="mobile-summary-toggle" :aria-expanded="summaryExpanded" @click="summaryExpanded = !summaryExpanded">{{ summaryExpanded ? '收起库存概览' : '查看全部库存阶段' }} <span aria-hidden="true">{{ summaryExpanded ? '−' : '+' }}</span></button>
  <section v-if="isPhone && summaryExpanded" class="m-stock-extra-summary"><span v-for="field in (canEdit ? mobileStageFields : mobileStageFields.slice(0,1))" :key="field.key">{{ field.label }}<b>{{ field.key === 'stock' ? list.summary.stock || 0 : list.summary[field.key] || 0 }}</b></span></section>
  <section class="panel">
    <ResponsiveFilters :active="list.query" @remove="key => { filters[key] = ''; apply(); }" @submit.prevent="apply">
      <ElInput
        v-model="filters.keyword"
        clearable
        :placeholder="isPhone ? 'SKU、款号或颜色' : '商品名、款式、SKU、颜色'"
      /><ElSelect v-model="filters.category" clearable placeholder="全部分类"
        ><ElOption
          v-for="c in categories"
          :key="c.key"
          :value="c.key"
          :label="c.labels?.zh || c.key" /></ElSelect
      ><ElSelect v-if="canEdit" v-model="filters.stock" clearable placeholder="全部库存"><ElOption label="欠货" value="backordered"/><ElOption label="有可用现货" value="available"/><ElOption label="无可用现货" value="empty"/></ElSelect><ElButton native-type="submit" type="primary">查询</ElButton
      ><ElButton @click="reset">重置</ElButton
      ><span class="small-note">汇总和导出覆盖全部筛选结果</span>
    </ResponsiveFilters>
    <div v-if="isPhone" class="m-stock-stage"><ElSelect v-model="mobileStage" aria-label="查看库存阶段"><ElOption v-for="field in (canEdit ? mobileStageFields : mobileStageFields.slice(0,1))" :key="field.key" :value="field.key" :label="field.label"/></ElSelect><span>{{ mobileSelection ? '选择商品后统一处理' : '当前尺码余额' }}</span></div>
    <div v-if="isPhone && mobileSelection && canEdit" class="m-stock-batch" data-testid="mobile-inventory-selection"><strong>已选 {{ selectedRows.length }} 个</strong><ElButton text @click="inventoryTable.selectCurrentPage()">本页全选</ElButton><ElButton text @click="mobileSelection=false;clearSelection()">完成</ElButton><MobileActionMenu label="批量处理"><ElButton :disabled="!selectedRows.length || receiving || preparingBatch" @click="prepareSelectedReceipt('normal')">合格一键入库</ElButton><ElButton :disabled="!selectedRows.length || receiving || preparingBatch" @click="prepareSelectedReceipt('defective')">次品一键打回</ElButton><ElButton :disabled="!selectedRows.length || receiving || preparingBatch" @click="prepareSelectedReceipt('temporary')">临时入库</ElButton><ElButton @click="clearSelection">清空选择</ElButton></MobileActionMenu></div>
    <DataTable
      :mobile-selection="false" :mobile-actions="false" :mobile-tools="false"
      ref="inventoryTable"
      expandable
      :selectable="canEdit"
      large-selection
      @selection-change="selectedRows = $event"
      :expanded-keys="expandedKeys"
      @expand-change="(_, rows) => (expandedKeys = rows.map((row) => row.id))"
      storage-key="inventory-v2"
      :rows="orderedRows"
      :columns="columns"
      :total="list.total"
      :page="list.query.page"
      :page-size="list.query.pageSize"
      :loading="list.loading"
      :error="list.error"
      @retry="list.load"
      @sort-change="list.sort"
      @page="list.query.page = $event"
      @page-size="list.query = { ...list.query, page: 1, pageSize: $event }"
      ><template #mobile-card="{row,selected:rowSelected,toggleSelection}"><article v-if="isPhone" class="m-stock-card" :class="{'is-selected':mobileSelection && rowSelected}"><button class="m-stock-head" @click="mobileSelection ? toggleSelection() : canEdit ? edit(row) : inventoryTable.toggleExpansion(row)"><span v-if="mobileSelection" class="m-stock-check">{{ rowSelected ? '✓' : '' }}</span><ProductImage v-else :src="row.image" :alt="productName(row)"/><span class="m-stock-copy"><strong>{{ row.sku }}</strong><small>{{ shortName(row) }}</small></span><strong class="m-stock-total">{{ total(row,mobileStage) }}<small>件</small></strong></button><div class="m-stock-sizes"><button v-for="size in row.sizePrices" :key="size.sizeCode" :class="{'is-negative':size[mobileStage] < 0}" @click="mobileSelection ? toggleSelection() : canEdit ? edit(row,size.sizeCode) : inventoryTable.toggleExpansion(row)"><span>{{ inventorySizeLabel(size.sizeCode) }}</span><b>{{ size[mobileStage] || 0 }}</b></button></div><div class="m-stock-foot"><span :class="{'is-negative':canEdit && row.shortageUnits}">{{ canEdit && row.shortageUnits ? `欠货 ${row.shortageUnits} 件 · ${row.shortageSizeCount} 个尺码` : `${row.sizePrices.length} 个真实尺码 · ${row.categoryLabel}` }}</span><ElButton v-if="canEdit && !mobileSelection" text @click="edit(row)">登记</ElButton></div></article></template><template #toolbar
        ><template v-if="canEdit"><span class="small-note">已勾选 {{ selectedRows.length }} 个商品</span>
          <ElButton :disabled="list.loading || !list.rows.length || receiving || preparingBatch" @click="inventoryTable.selectCurrentPage()">全部勾选</ElButton>
          <ElButton :disabled="!selectedRows.length || receiving || preparingBatch" @click="clearSelection">清空勾选</ElButton>
          <ElButton type="primary" :disabled="!selectedRows.length || list.loading || receiving || preparingBatch" @click="prepareSelectedReceipt('normal')">一键入库</ElButton>
          <ElButton type="danger" :disabled="!selectedRows.length || list.loading || receiving || preparingBatch" @click="prepareSelectedReceipt('defective')">一键打回</ElButton>
          <ElButton type="success" :disabled="!selectedRows.length || list.loading || receiving || preparingBatch" @click="prepareSelectedReceipt('temporary')">临时入库</ElButton>
        </template><ElButton
          :disabled="list.loading || !list.rows.length"
          @click="toggleAllSizes"
          >{{ allSizesExpanded ? "一键收起" : "一键展开" }}</ElButton
        ></template
      ><template #name="{ row }"
        ><div class="product-cell">
          <ProductImage :src="row.image" :alt="productName(row)" />
          <div>
            <span class="product-name" :title="productName(row)">{{
              shortName(row)
            }}</span
            ><small class="sku" :title="row.sku">{{ row.sku }}</small><ElTag v-if="canEdit && row.shortageUnits" type="danger">欠货 {{ row.shortageUnits }} 件 · {{ row.shortageSizeCount }} 个尺码</ElTag><ElTag v-if="canEdit && row.isActive === false" type="info">已下架</ElTag
            ><small
              >{{ row.colorName }} · {{ row.categoryLabel }} ·
              <a href="#" @click.prevent="inventoryTable.toggleExpansion(row)"
                >{{ row.sizePrices.length }} 个尺码，查看明细</a
              ></small
            >
          </div>
        </div></template
      ><template #expanded="{ row }"
        ><div class="inventory-expanded">
          <div class="panel-title">
            <strong>真实尺码明细</strong
            ><span class="small-note"
              >现货余额可为负数，表示欠货；到货后入库抵减欠货</span
            >
          </div>
          <div class="stock-grid">
            <div
              v-for="size in row.sizePrices"
              :key="size.sizeCode"
              class="stock-cell"
            >
              <strong :title="'原始尺码：' + size.sizeCode">{{
                inventorySizeLabel(size.sizeCode)
              }}</strong>
              <div class="stock-line">
                <span>现货</span
                ><b :class="{ negative: size.stock <= 0 }">{{ size.stock }}</b>
              </div>
              <template v-if="canEdit"
                ><div class="stock-line">
                  <span>合同未送</span><b>{{ size.contractPending }}</b>
                </div>
                <div class="stock-line inbound">
                  <span>待验货</span><b>{{ size.pendingInspection || 0 }}</b
                  ></div><div class="stock-line"><span>次品</span><b>{{ size.defectivePending || 0 }}</b></div><div class="stock-line"><span>合格</span><b>{{ size.pendingInbound }}</b>
                </div><div class="stock-line temporary"><span>临时待入库</span><b>{{ size.temporaryInbound || 0 }}</b></div></template
              >
            </div>
          </div>
        </div></template
      ><template #pending="{ row }">{{
        total(row, "contractPending")
      }}</template
      ><template #inspection="{ row }">{{
        total(row, "pendingInspection")
      }}</template
      ><template #defective="{ row }"><ElTag :type="total(row, 'defectivePending') ? 'danger' : 'info'">{{ total(row, "defectivePending") }}</ElTag></template
      ><template #inbound="{ row }"
        ><ElTag :type="total(row, 'pendingInbound') ? 'warning' : 'info'">{{
          total(row, "pendingInbound")
        }}</ElTag></template
      ><template #temporary="{ row }"><ElTag :type="total(row, 'temporaryInbound') ? 'success' : 'info'">{{ total(row, 'temporaryInbound') }}</ElTag></template
      ><template #actions="{ row }"
        ><ElButton link type="primary" @click="edit(row)">登记数量</ElButton
        ></template
      ></DataTable
    >
  </section>
  <ElDrawer
    v-model="editing"
    :title="isPhone ? '登记库存' : '登记库存与到货进度'"
    size="min(1140px, 96vw)"
    :before-close="close"
    class="inventory-registration"
    ><template v-if="product"
      ><div class="registration-product">
        <ProductImage :src="product.image" :alt="productName(product)" />
        <div class="registration-product__content">
          <h3>{{ productName(product) }}</h3>
          <div class="registration-product__meta"><span class="registration-sku">{{ product.sku }}</span><span>{{ product.colorName }}</span><span>{{ draft.length }} 个尺码</span></div>
        </div>
      </div>
      <div class="registration-guide">
        <span>填写调整后的数量，<strong>保存后生效</strong>；入库与打回需另行执行。</span>
        <ElPopover trigger="click" placement="bottom-end" :width="320">
          <template #reference><ElButton text class="registration-rule-trigger">规则说明 <ElIcon><InfoFilled /></ElIcon></ElButton></template>
          <div class="registration-rules">
            <strong>库存登记规则</strong>
            <ul>
              <li><b>待验货：</b>增加时先扣合同未送；超量按原合同总数累计 15%，按尺码向下取整。点击尺码下的“验货额度”查看明细。</li>
              <li><b>次品：</b>仅暂存并预留待验货；打回优先处理超量次品，普通次品返合同，已使用超量额度不返还。</li>
              <li><b>合格：</b>增加时扣减可转移的待验货；入库时增加现货并清零合格。</li>
              <li><b>临时待入库：</b>独立登记与入库，不影响采购阶段。</li>
            </ul>
          </div>
        </ElPopover>
      </div>
      <div v-if="isPhone" class="m-registration" data-testid="mobile-inventory-registration"><nav class="m-registration-sizes" aria-label="登记真实尺码"><button v-for="row in draft" :key="row.sizeCode" :class="{active:mobileRegistrationRow?.sizeCode === row.sizeCode,changed:registrationRowChanged(row)}" @click="registrationSize=row.sizeCode">{{ inventorySizeLabel(row.sizeCode) }}</button></nav><section v-if="mobileRegistrationRow" class="m-registration-card"><div class="m-registration-title"><strong>{{ inventorySizeLabel(mobileRegistrationRow.sizeCode) }} · 登记数量</strong><InventoryInspectionAllowance :row="mobileRegistrationRow"/></div><div class="m-registration-grid"><label v-for="field in mobileStageFields" :key="field.key"><span>{{ field.label }}</span><ElInputNumber :model-value="mobileRegistrationRow[field.key]" :min="field.key === 'stock' ? -2147483648 : 0" :max="2147483647" :precision="0" :controls="false" :aria-label="`${field.label} ${mobileRegistrationRow.sizeCode}`" @update:model-value="value => setMobileRegistration(field.key,value)"/><InventoryQuantityChange :value="mobileRegistrationRow[field.key]" :original="mobileRegistrationRow[field.original]"/></label></div></section></div>
      <AdaptiveTable v-else :data="draft" class="registration-table" :row-class-name="({ row }) => registrationRowChanged(row) ? 'registration-row-changed' : ''"
        ><ElTableColumn
          prop="sizeCode"
          label="真实尺码"
          width="108"
          fixed="left"
        ><template #default="{ row }"><div class="registration-size"><strong>{{ inventorySizeLabel(row.sizeCode) }}</strong><InventoryInspectionAllowance :row="row" /></div></template></ElTableColumn
        ><ElTableColumn label="现货余额" min-width="155" align="center"
          ><template #default="{ row }"
            ><div class="registration-quantity"><ElInputNumber
              v-model="row.stock"
              :min="-2147483648"
              :max="2147483647"
              :precision="0"
              controls-position="right"
              :aria-label="`现货余额 ${row.sizeCode}`"
            /><InventoryQuantityChange :value="row.stock" :original="row.originalStock" /></div></template
          ></ElTableColumn
        ><ElTableColumn label="合同未送" min-width="155" align="center"
          ><template #default="{ row }"
            ><div class="registration-quantity"><ElInputNumber
              v-model="row.contractPending"
              :min="0"
              :precision="0"
              controls-position="right"
              :aria-label="`合同未送 ${row.sizeCode}`"
            /><InventoryQuantityChange :value="row.contractPending" :original="row.originalPending" /></div></template
          ></ElTableColumn
        ><ElTableColumn label="待验货" min-width="155" align="center"
          ><template #default="{ row }"><div class="registration-quantity">
            <ElInputNumber
              :model-value="row.pendingInspection"
              :min="0"
              :precision="0"
              controls-position="right"
              :aria-label="`待验货 ${row.sizeCode}`"
              @update:model-value="(value) => moveStage(row, 'inspection', value)"
            />
            <InventoryQuantityChange :value="row.pendingInspection" :original="row.originalInspection" />
          </div></template></ElTableColumn
        ><ElTableColumn label="次品" min-width="155" align="center"><template #default="{ row }"><div class="registration-quantity">
            <ElInputNumber v-model="row.defectivePending" :min="0" :max="2147483647" :precision="0" controls-position="right" :aria-label="`次品 ${row.sizeCode}`" />
            <InventoryQuantityChange :value="row.defectivePending" :original="row.originalDefective" />
          </div></template></ElTableColumn
        ><ElTableColumn label="合格" min-width="155" align="center"
          ><template #default="{ row }"
            ><div class="registration-quantity"><ElInputNumber
              :model-value="row.pendingInbound"
              @update:model-value="(value) => moveStage(row, 'inbound', value)"
              :min="0"
              :precision="0"
              controls-position="right"
              :aria-label="`合格 ${row.sizeCode}`"
            /><InventoryQuantityChange :value="row.pendingInbound" :original="row.originalInbound" /></div></template
          ></ElTableColumn
        ><ElTableColumn label="临时待入库" min-width="155" align="center"><template #default="{ row }"><div class="registration-quantity">
            <ElInputNumber v-model="row.temporaryInbound" :min="0" :max="2147483647" :precision="0" controls-position="right" :aria-label="`临时待入库 ${row.sizeCode}`" />
            <InventoryQuantityChange :value="row.temporaryInbound" :original="row.originalTemporary" />
          </div></template></ElTableColumn
        ></AdaptiveTable
      ><ElAlert v-if="error" :title="error" type="error" :closable="false"
        ><ElButton v-if="conflict" text @click="readLatest"
          >读取最新数据（保留草稿）</ElButton
        ></ElAlert
      >
      <div v-if="latest" class="section-gap">
        <h3>线上最新数量</h3>
        <p v-for="s in latest.sizePrices" :key="s.sizeCode">
          {{ inventorySizeLabel(s.sizeCode) }}：库存 {{ s.stock }} / 合同未送
          {{ s.contractPending }} / 待验货 {{ s.pendingInspection }} / 次品 {{ s.defectivePending || 0 }} / 合格
          {{ s.pendingInbound }}
          / 临时待入库 {{ s.temporaryInbound || 0 }}
        </p>
        <ElButton @click="adoptLatest">使用最新数据重新编辑</ElButton>
      </div>
      <details v-if="isPhone" class="m-registration-history"><summary>登记操作记录 <small>{{ operationHistory.total }} 次</small></summary>      <section class="inventory-history">
        <div class="panel-title">
          <strong>登记操作记录</strong>
          <span class="small-note">每次成功保存或打回记为一次操作 · 最新记录在前 · 每页 10 条</span>
        </div>
        <ElAlert v-if="operationHistory.error" :title="operationHistory.error" type="error" :closable="false">
          <ElButton link type="primary" @click="loadOperations">重新加载记录</ElButton>
        </ElAlert>
        <AdaptiveTable v-loading="operationHistory.loading" :data="operationHistory.items" row-key="id" empty-text="暂无登记操作记录">
          <ElTableColumn label="操作时间" width="165"><template #default="{ row }">{{ dateTime(row.occurredAt) }}</template></ElTableColumn>
          <ElTableColumn label="操作人" width="110"><template #default="{ row }">
            {{ row.actor.name || '未知操作人' }}<small class="history-role">{{ roleNames[row.actor.role] || row.actor.role }}</small>
          </template></ElTableColumn>
          <ElTableColumn label="登记数量 / 变化明细" min-width="400"><template #default="{ row }">
            <div v-for="change in row.changes" :key="change.sizeCode" class="history-size">
              <ElTag v-if="change.operation === 'defective_return'" type="danger">次品打回</ElTag>
              <strong>{{ inventorySizeLabel(change.sizeCode) }}</strong>
              <span v-for="field in change.fields" :key="field.field" class="history-field">
                {{ inventoryFieldLabels[field.field] || field.field }} {{ field.before }} → {{ field.after }}
                <b :class="field.delta < 0 ? 'negative' : 'positive'">（{{ delta(field.after, field.before) }}）</b>
              </span>
            </div>
            <span v-if="!row.changes.length" class="small-note">本次保存数量未变化</span>
          </template></ElTableColumn>
        </AdaptiveTable>
        <ElPagination v-model:current-page="operationHistory.page" :page-size="10" :total="operationHistory.total" layout="total,prev,pager,next" class="section-gap" />
      </section></details><template v-else>      <section class="inventory-history">
        <div class="panel-title">
          <strong>登记操作记录</strong>
          <span class="small-note">每次成功保存或打回记为一次操作 · 最新记录在前 · 每页 10 条</span>
        </div>
        <ElAlert v-if="operationHistory.error" :title="operationHistory.error" type="error" :closable="false">
          <ElButton link type="primary" @click="loadOperations">重新加载记录</ElButton>
        </ElAlert>
        <AdaptiveTable v-loading="operationHistory.loading" :data="operationHistory.items" row-key="id" empty-text="暂无登记操作记录">
          <ElTableColumn label="操作时间" width="165"><template #default="{ row }">{{ dateTime(row.occurredAt) }}</template></ElTableColumn>
          <ElTableColumn label="操作人" width="110"><template #default="{ row }">
            {{ row.actor.name || '未知操作人' }}<small class="history-role">{{ roleNames[row.actor.role] || row.actor.role }}</small>
          </template></ElTableColumn>
          <ElTableColumn label="登记数量 / 变化明细" min-width="400"><template #default="{ row }">
            <div v-for="change in row.changes" :key="change.sizeCode" class="history-size">
              <ElTag v-if="change.operation === 'defective_return'" type="danger">次品打回</ElTag>
              <strong>{{ inventorySizeLabel(change.sizeCode) }}</strong>
              <span v-for="field in change.fields" :key="field.field" class="history-field">
                {{ inventoryFieldLabels[field.field] || field.field }} {{ field.before }} → {{ field.after }}
                <b :class="field.delta < 0 ? 'negative' : 'positive'">（{{ delta(field.after, field.before) }}）</b>
              </span>
            </div>
            <span v-if="!row.changes.length" class="small-note">本次保存数量未变化</span>
          </template></ElTableColumn>
        </AdaptiveTable>
        <ElPagination v-model:current-page="operationHistory.page" :page-size="10" :total="operationHistory.total" layout="total,prev,pager,next" class="section-gap" />
      </section></template></template
    ><template #footer
      ><div class="registration-footer"><span class="registration-save-note">{{ changedSizeCount ? `已调整 ${changedSizeCount} 个尺码，尚未保存` : '尚未修改数量' }}</span><div class="registration-footer__actions"><ElButton :disabled="saving" @click="close()">取消</ElButton
      ><ElButton
        type="primary"
        :disabled="!dirty"
        :loading="saving"
        @click="submit"
        >保存修改</ElButton
      ></div></div></template
    ></ElDrawer
  >
  <ElDrawer
    v-model="previewOpen"
    title="库存导入"
    size="min(1120px, 96vw)"
    :close-on-click-modal="false"
    :before-close="closeImport"
    ><ElSteps
      :active="importResult ? 3 : preview ? 1 : 0"
      finish-status="success"
      simple
      ><ElStep title="上传文件" /><ElStep title="校验预览" /><ElStep
        title="确认更新" /><ElStep title="结果"
    /></ElSteps>
    <p class="small-note section-gap">
      {{ importFile?.name }} · 上传不会直接修改库存
    </p>
    <ElAlert
      v-if="importError"
      :title="importError"
      type="error"
      :closable="false"
    /><ElResult
      v-if="importResult"
      icon="success"
      title="库存导入完成"
      :sub-title="`实际更新 ${importResult.updatedProducts} 个商品、${importResult.updatedRows} 个尺码、${importResult.updatedFields} 个字段`"
    />
    <template v-else-if="preview"
      ><div class="batch-bar">
        商品 {{ preview.summary.productCount }} · 尺码行
        {{ preview.summary.rowCount }} · 待改行
        {{ preview.summary.changedRowCount }} · 错误 {{ preview.errors.length }}
      </div>
      <ElRadioGroup
        v-model="previewFilter"
        class="section-gap"
        @change="previewPage = 1"
        ><ElRadioButton value="all">全部</ElRadioButton
        ><ElRadioButton value="stock">库存变化</ElRadioButton
        ><ElRadioButton value="pending">合同未送变化</ElRadioButton
        ><ElRadioButton value="inspection">待验货变化</ElRadioButton
        ><ElRadioButton value="inbound">合格变化</ElRadioButton
        ><ElRadioButton value="temporary">临时待入库变化</ElRadioButton
        ><ElRadioButton value="errors">错误</ElRadioButton></ElRadioGroup
      ><AdaptiveTable
        :data="previewRows.slice((previewPage - 1) * 25, previewPage * 25)"
        class="section-gap"
        ><ElTableColumn
          v-if="previewFilter === 'errors'"
          prop="row"
          label="行号"
          width="70"
        /><ElTableColumn
          v-if="previewFilter === 'errors'"
          prop="message"
          label="错误原因"
        /><template v-else
          ><ElTableColumn label="商品 / SKU" min-width="220"
            ><template #default="{ row }"
              >{{ row.title
              }}<small style="display: block">{{ row.sku }}</small></template
            ></ElTableColumn
          ><ElTableColumn
            prop="sizeCode"
            :formatter="(row) => inventorySizeLabel(row.sizeCode)"
            label="尺码"
            width="90"
          /><ElTableColumn label="库存"
            ><template #default="{ row }"
              ><span :class="{ positive: row.stockChanged }"
                >{{ row.originalStock }} → {{ row.stock }}</span
              ></template
            ></ElTableColumn
          ><ElTableColumn label="合同未送"
            ><template #default="{ row }"
              ><span :class="{ positive: row.contractPendingChanged }"
                >{{ row.originalContractPending }} →
                {{ row.contractPending }}</span
              ></template
            ></ElTableColumn
          ><ElTableColumn label="待验货"
            ><template #default="{ row }"
              >{{ row.originalPendingInspection }} →
              {{ row.pendingInspection }}</template
            ></ElTableColumn
          ><ElTableColumn label="合格"
            ><template #default="{ row }"
              ><span :class="{ positive: row.pendingInboundChanged }"
                >{{ row.originalPendingInbound ?? "保持" }} →
                {{ row.pendingInbound ?? "保持" }}</span
              ></template
            ></ElTableColumn
          ><ElTableColumn label="临时待入库"><template #default="{ row }"><span :class="{ positive: row.temporaryInboundChanged }">{{ row.originalTemporaryInbound ?? "保持" }} → {{ row.temporaryInbound ?? "保持" }}</span></template></ElTableColumn
          ></template
        ></AdaptiveTable
      ><ElPagination
        v-model:current-page="previewPage"
        :page-size="25"
        :total="previewRows.length"
        layout="total,prev,pager,next"
        class="section-gap" /><ElAlert
        v-if="preview.errors.length"
        title="请修正全部错误后重新上传；本次不会写入任何库存。"
        type="error"
        :closable="false" /></template
    ><template #footer
      ><ElButton :disabled="importing" @click="closeImport()">{{
        importResult ? "完成" : "取消"
      }}</ElButton
      ><ElButton
        v-if="!importResult"
        type="primary"
        :loading="importing"
        :disabled="!preview || !!preview.errors.length"
        @click="confirmImport"
        >确认更新全部有效行</ElButton
      ></template
    ></ElDrawer
  >
  <ElDialog
    v-model="receiptOpen"
    :title="receiptTitle"
    width="860px"
    :close-on-click-modal="false"
    :before-close="closeReceipt"
    ><template v-if="receipt"
      ><p>
        本次将为 <strong>{{ productName(receipt) }}</strong> {{ receiptSource === 'defective' ? '打回' : '入库' }}
        <strong>{{ total(receipt, receiptField) }}</strong> 件，来源为<strong>{{ receiptSource === 'defective' ? '已保存次品' : receiptSource === 'temporary' ? '独立临时待入库' : '采购合格' }}</strong>。
      </p>
      <p v-if="receiptBatch" class="small-note">已勾选 {{ receiptBatch.selectedProducts }} 个商品，可处理 {{ receiptBatch.processableProducts }} 个，无数量 {{ receiptBatch.selectedProducts - receiptBatch.processableProducts }} 个将跳过。全部勾选仅选当前页；本次仅执行预览中的所选商品。</p>
      <ElAlert
        :title="receiptExplanation"
        type="info"
        :closable="false" /><ElAlert v-if="receiptBatch" title="全部所选商品在同一事务中提交；版本冲突或任一商品处理失败，整批不生效。" type="info" :closable="false"/><AdaptiveTable
        :data="receipt.sizePrices.filter((s) => s[receiptField] > 0)"
        ><ElTableColumn v-if="receiptBatch" prop="sku" label="颜色 SKU" min-width="140"/><ElTableColumn
          prop="sizeCode"
          :formatter="(row) => inventorySizeLabel(row.sizeCode)"
          label="尺码"
        /><ElTableColumn
          :prop="receiptField"
          :label="receiptSource === 'defective' ? '本次打回' : '本次入库'"
          align="right"
        /><ElTableColumn label="现货"
          ><template #default="{ row }"
            >{{ row.stock }} → {{ receiptSource === 'defective' ? row.stock : row.stock + row[receiptField] }}</template
          ></ElTableColumn
        ><ElTableColumn label="合同未送"
          ><template #default="{ row }"
            >{{ row.contractPending }} → {{ receiptSource === 'defective' ? defectiveReturnPreview(row).contractAfter : row.contractPending }}</template
          ></ElTableColumn
        ><ElTableColumn v-if="receiptSource === 'defective'" label="待验货"><template #default="{ row }">{{ row.pendingInspection }} → {{ defectiveReturnPreview(row).inspectionAfter }}</template></ElTableColumn
        ><ElTableColumn v-if="receiptSource === 'defective'" label="次品"><template #default="{ row }">{{ row.defectivePending }} → 0</template></ElTableColumn
        ></AdaptiveTable
      ><ElAlert
        v-if="receiptError"
        :title="receiptError"
        type="error"
        :closable="false" /><ElButton v-if="receiptConflict" link type="primary" @click="receiptBatch ? prepareSelectedReceipt(receiptSource, receiptBatch.items.map(p => p.id)) : prepareReceipt(receipt, receiptSource)">读取最新数量并重新确认</ElButton></template
    ><template #footer
      ><ElButton :disabled="receiving" @click="receiptOpen = false"
        >取消</ElButton
      ><ElButton
        type="primary"
        :loading="receiving"
        :disabled="!receipt || !total(receipt, receiptField) || receiptConflict"
        @click="receive"
        >{{ receiptSource === 'defective' ? '确认打回' : '确认入库' }}</ElButton
      ></template
    ></ElDialog
  >
</template>
<script setup>
import MobileActionMenu from "../components/MobileActionMenu.vue";
import { useResponsive } from "../composables/responsive";
import ResponsiveFilters from "../components/ResponsiveFilters.vue";
import AdaptiveTable from "../components/AdaptiveTable";
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from "vue";
import { inventorySizeLabel } from "../utils/inventorySizes";
import { registrationError, moveProcurementStage, defectiveReturnPreview } from "../utils/inventoryStages";
import { sortProductsByCategory } from "../utils/catalogOrder";
import { ElMessage } from "element-plus";
import { useAdminAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import DataTable from "../components/DataTable.vue";
import ProductImage from "../components/ProductImage.vue";
import InventoryQuantityChange from "../components/InventoryQuantityChange.vue";
import InventoryInspectionAllowance from "../components/InventoryInspectionAllowance.vue";
import { InfoFilled } from "@element-plus/icons-vue";
import { registrationRowChanged } from "../utils/inventoryRegistrationUI";
import {
  api,
  save,
  useList,
  useDirty,
  download,
  notifyError,
  confirm,
  productName,
  shortName,
  dateTime,
  roleNames,
} from "../composables/workbench";
const { isPhone } = useResponsive();
const mobileSelection = ref(false), mobileStage = ref('stock'), registrationSize = ref('');
const mobileStageFields = [{key:'stock',label:'现货余额',original:'originalStock'},{key:'contractPending',label:'合同未送',original:'originalPending'},{key:'pendingInspection',label:'待验货',original:'originalInspection'},{key:'defectivePending',label:'次品',original:'originalDefective'},{key:'pendingInbound',label:'合格',original:'originalInbound'},{key:'temporaryInbound',label:'临时待入库',original:'originalTemporary'}];
const mobileRegistrationRow = computed(() => draft.value.find(row=>row.sizeCode === registrationSize.value) || draft.value[0]);
function setMobileRegistration(key,value){const row=mobileRegistrationRow.value;if(!row)return;if(key==='pendingInspection')return moveStage(row,'inspection',value);if(key==='pendingInbound')return moveStage(row,'inbound',value);row[key]=value;}
const auth = useAdminAuthStore(),
  summaryExpanded = ref(false),
  canEdit = computed(() => auth.userRole !== "customer"),
  list = useList("inventory", { sort: "category" }),
  categories = ref([]),
  filters = reactive({
    keyword: list.query.keyword || "",
    category: list.query.category || "",
    stock: list.query.stock || "",
  });
const orderedRows = computed(() => sortProductsByCategory(list.rows || [], categories.value));
const inventoryTable = ref();
const selectedRows = ref([]);
function clearSelection() {
  selectedRows.value = [];
  inventoryTable.value?.clearSelection();
}
watch(() => [list.query.keyword, list.query.category, list.query.stock], clearSelection);
const expandedKeys = ref([]);
const allSizesExpanded = computed(
  () =>
    list.rows.length > 0 &&
    list.rows.every((row) => expandedKeys.value.includes(row.id)),
);
function toggleAllSizes() {
  expandedKeys.value = allSizesExpanded.value
    ? []
    : list.rows.map((row) => row.id);
}
watch(
  () => list.rows,
  () => {
    expandedKeys.value = [];
  },
);
const total = (row, field) =>
  row.sizePrices.reduce((sum, size) => sum + Number(size[field] || 0), 0);
const columns = computed(() => [
  { prop: "name", label: "商品 / 颜色 SKU", width: 300 },
  {
    prop: "stock",
    label: "现货余额",
    width: 100,
    numeric: true,
    sortable: true,
  },
  ...(canEdit.value
    ? [
        { prop: "availableStock", label: "可用现货", width: 100, numeric: true },
        { prop: "shortageUnits", label: "欠货件数", width: 100, numeric: true },
        { prop: "pending", label: "合同未送", width: 100, numeric: true },
        { prop: "inspection", label: "待验货", width: 100, numeric: true },
        { prop: "defective", label: "次品", width: 100, numeric: true, defaultVisible: true },
        { prop: "inbound", label: "合格", width: 100, numeric: true },
        { prop: "temporary", label: "临时待入库", width: 110, numeric: true, defaultVisible: true },
        { prop: "actions", label: "操作", width: 110 },
      ]
    : []),
]);
const editing = ref(false),
  product = ref(),
  draft = ref([]),
  error = ref(""),
  saving = ref(false),
  latest = ref(),
  conflict = ref(false),
  input = ref(),
  exporting = ref(false);
const { dirty, markClean, canLeave } = useDirty(() => draft.value);
const changedSizeCount = computed(() => draft.value.filter(registrationRowChanged).length);
const inventoryFieldLabels = { stock: '现货余额', contractPending: '合同未送', pendingInspection: '待验货', pendingInbound: '合格', defectivePending: '次品', temporaryInbound: '临时待入库', overdeliveryUsed: '累计使用超量额度', overdeliveryInspection: '待验货超量', overdeliveryQualified: '合格超量' };
const operationHistory = reactive({ items: [], total: 0, page: 1, loading: false, error: '' });
let operationController, operationSerial = 0;
async function loadOperations() {
  if (!editing.value || !product.value) return;
  operationController?.abort();
  operationController = new AbortController();
  const serial = ++operationSerial;
  operationHistory.loading = true;
  operationHistory.error = '';
  try {
    const result = await api(`inventory/${product.value.id}/operations?page=${operationHistory.page}&pageSize=10`, { signal: operationController.signal });
    if (serial === operationSerial) {
      operationHistory.items = result.items;
      operationHistory.total = result.total;
    }
  } catch (e) {
    if (serial === operationSerial && e.name !== 'AbortError') operationHistory.error = e.message;
  } finally {
    if (serial === operationSerial) operationHistory.loading = false;
  }
}
watch(() => [editing.value, product.value?.id, operationHistory.page], ([open]) => {
  if (open) loadOperations();
  else {
    operationController?.abort();
    operationSerial++;
    operationHistory.loading = false;
  }
});
onBeforeUnmount(() => operationController?.abort());
function delta(a, b) {
  const n = Number(a) - b;
  return n > 0 ? "+" + n : String(n);
}
function populate(item) {
  product.value = item;
  draft.value = item.sizePrices.map((s) => ({
    ...s,
    registrationBase: { ...s },
    originalStock: s.stock,
    originalPending: s.contractPending,
    originalInbound: s.pendingInbound,
    originalInspection: s.pendingInspection || 0,
    defectivePending: s.defectivePending || 0,
    originalDefective: s.defectivePending || 0,
    temporaryInbound: s.temporaryInbound || 0,
    originalTemporary: s.temporaryInbound || 0,
  }));
  markClean();
  error.value = "";
  conflict.value = false;
  latest.value = null;
}
async function edit(row, sizeCode) {
  try {
    populate((await api(`inventory/${row.id}`)).product);
    Object.assign(operationHistory, { items: [], total: 0, page: 1, error: '' });
    registrationSize.value = typeof sizeCode === "string" ? sizeCode : draft.value[0]?.sizeCode || "";
    editing.value = true;
  } catch (e) {
    notifyError(e);
  }
}
async function close(done) {
  if (saving.value) return;
  if (await canLeave()) {
    markClean();
    editing.value = false;
    if (typeof done === "function") done();
  }
}
async function apply() {
  if (await canLeave()) list.apply(filters);
}
async function reset() {
  if (await canLeave()) {
    Object.assign(filters, { keyword: "", category: "", stock: "" });
    list.apply(filters);
  }
}
async function moveStage(row, stage, value) {
  const target = stage === "inspection" ? "pendingInspection" : "pendingInbound";
  const source = stage === "inspection" ? "contractPending" : "pendingInspection";
  const old = row[target];
  // InputNumber updates the model while typing, before its change event. Use
  // the last accepted model value, not the component's potentially stale value.
  if (!Number.isInteger(value) || value < 0 || value > 2147483647) {
    error.value = "阶段数量须为范围内的非负整数";
    return;
  }
  if (value === old) return;
  const candidate = { ...row, [target]: value };
  const message = moveProcurementStage(candidate, stage, value, old);
  row[target] = value;
  if (message) {
    // Flush the attempted value so reverting also resets the input display.
    await nextTick();
    row[target] = old;
  } else {
    row[source] = candidate[source];
    for (const key of ['overdeliveryUsed', 'overdeliveryInspection', 'overdeliveryQualified', 'overdeliveryRemaining', 'contractPending', 'contractReceived']) row[key] = candidate[key];
  }
  error.value = message;
}
async function submit() {
  if (saving.value) return;
  error.value = registrationError(draft.value);
  if (error.value) return;
  saving.value = true;
  error.value = "";
  try {
    await save(`inventory/${product.value.id}`, {
      version: product.value.version,
      sizeStocks: Object.fromEntries(
        draft.value
          .filter((s) => s.stock !== s.originalStock)
          .map((s) => [s.sizeCode, s.stock]),
      ),
      contractPendingBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.contractPending !== s.originalPending)
          .map((s) => [s.sizeCode, s.contractPending]),
      ),
      pendingInspectionBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.pendingInspection !== s.originalInspection)
          .map((s) => [s.sizeCode, s.pendingInspection]),
      ),
      pendingInboundBySize: Object.fromEntries(
        draft.value
          .filter((s) => s.pendingInbound !== s.originalInbound)
          .map((s) => [s.sizeCode, s.pendingInbound]),
      ),
      defectivePendingBySize: Object.fromEntries(draft.value.filter((s) => s.defectivePending !== s.originalDefective).map((s) => [s.sizeCode, s.defectivePending])),
      temporaryInboundBySize: Object.fromEntries(draft.value.filter((s) => s.temporaryInbound !== s.originalTemporary).map((s) => [s.sizeCode, s.temporaryInbound])),
      // A phone user may arrive then qualify the same quantity, leaving inspection
      // equal to its original value. Send both final procurement targets so the
      // server does not infer a different inspection balance from a partial map.
      ...(isPhone.value ? {
        pendingInspectionBySize: Object.fromEntries(draft.value.map(s => [s.sizeCode, s.pendingInspection])),
        pendingInboundBySize: Object.fromEntries(draft.value.map(s => [s.sizeCode, s.pendingInbound])),
      } : {}),
    });
    markClean();
    editing.value = false;
    ElMessage.success("库存已更新");
    list.load();
  } catch (e) {
    error.value = e.message;
    conflict.value = e.status === 409;
  } finally {
    saving.value = false;
  }
}
async function readLatest() {
  try {
    latest.value = (await api(`inventory/${product.value.id}`)).product;
    loadOperations();
  } catch (e) {
    notifyError(e);
  }
}
async function adoptLatest() {
  if (await confirm("放弃当前草稿，使用最新数量？")) populate(latest.value);
}
async function exportFile() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    await download(
      "inventory/export?" +
        new URLSearchParams({ ...list.query, view: "workbench" }),
      "当前库存.xlsx",
    );
  } catch (e) {
    notifyError(e);
  } finally {
    exporting.value = false;
  }
}
const previewOpen = ref(false),
  preview = ref(),
  importFile = ref(),
  importing = ref(false),
  importError = ref(""),
  importResult = ref(),
  previewFilter = ref("all"),
  previewPage = ref(1);
const previewRows = computed(() =>
  !preview.value
    ? []
    : previewFilter.value === "errors"
      ? preview.value.errors
      : preview.value.rows.filter(
          (r) =>
            previewFilter.value === "all" ||
            (previewFilter.value === "stock"
              ? r.stockChanged
              : previewFilter.value === "temporary"
                ? r.temporaryInboundChanged
              : previewFilter.value === "inbound"
                ? r.pendingInboundChanged
                : previewFilter.value === "inspection"
                  ? r.pendingInspectionChanged
                  : r.contractPendingChanged),
        ),
);
async function previewFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.error("文件不能超过 10 MB");
    return;
  }
  importFile.value = file;
  preview.value = null;
  importResult.value = null;
  importError.value = "";
  previewOpen.value = true;
  importing.value = true;
  previewFilter.value = "all";
  previewPage.value = 1;
  try {
    const body = new FormData();
    body.append("file", file);
    preview.value = await api("inventory/import/preview", {
      method: "POST",
      body,
    });
    if (preview.value.errors.length) previewFilter.value = "errors";
  } catch (e) {
    importError.value = e.message;
  } finally {
    importing.value = false;
  }
}
async function confirmImport() {
  if (
    importing.value ||
    !(await confirm(
      `将处理 ${preview.value.summary.rowCount} 个尺码行，只修改相对导出原值发生变化的字段。`,
      "确认导入",
    ))
  )
    return;
  importing.value = true;
  try {
    const body = new FormData();
    body.append("file", importFile.value);
    body.append("fileHash", preview.value.fileHash);
    importResult.value = await api("inventory/import/confirm", {
      method: "POST",
      body,
    });
    list.load();
  } catch (e) {
    importError.value = e.message;
  } finally {
    importing.value = false;
  }
}
function closeImport(done) {
  if (importing.value) return;
  previewOpen.value = false;
  if (typeof done === "function") done();
}
const receipt = ref(),
  receiptBatch = ref(null),
  preparingBatch = ref(false),
  receiptOpen = ref(false),
  receiving = ref(false),
  receiptError = ref(""),
  receiptRequest = ref(""),
  receiptSource = ref('normal'),
  receiptConflict = ref(false);
const receiptField = computed(() => receiptSource.value === 'defective' ? 'defectivePending' : receiptSource.value === 'temporary' ? 'temporaryInbound' : 'pendingInbound');
const receiptTitle = computed(() => (receiptBatch.value ? '批量' : '') + (receiptSource.value === 'defective' ? '确认次品一键打回' : receiptSource.value === 'temporary' ? '确认临时入库' : '确认一键入库'));
const receiptExplanation = computed(() => receiptSource.value === 'defective'
  ? '仅处理已保存次品：等量减少待验货、增加合同未送并清零次品。现货、合格和临时待入库不变；打回不做反向撤销，各尺码整笔提交。'
  : receiptSource.value === 'temporary' ? '现货增加、临时待入库清零；合同未送、待验货、次品和合格保持不变，各尺码整笔提交。' : '现货增加、合格清零；合同未送、待验货、次品和临时待入库保持不变，各尺码整笔提交。');
async function prepareReceipt(row, source = 'normal') {
  if (receiving.value || saving.value) return;
  if (editing.value) {
    if (!(await canLeave())) return;
    markClean();
    editing.value = false;
  }
  try {
    receiptBatch.value = null;
    receipt.value = (await api(`inventory/${row.id}`)).product;
    receiptSource.value = source;
    receiptConflict.value = false;
    receiptRequest.value = crypto.randomUUID();
    receiptError.value = "";
    receiptOpen.value = true;
  } catch (e) {
    notifyError(e);
  }
}
function closeReceipt(done) {
  if (!receiving.value) done();
}
async function prepareSelectedReceipt(source, ids = selectedRows.value.map(p => p.id)) {
  if (receiving.value || saving.value || preparingBatch.value || !ids.length) return;
  if (editing.value) {
    if (!(await canLeave())) return;
    markClean();
    editing.value = false;
  }
  preparingBatch.value = true;
  try {
    const preview = await api(`inventory/batch/preview?${new URLSearchParams({ ids: ids.join(','), source })}`);
    const field = source === 'defective' ? 'defectivePending' : source === 'temporary' ? 'temporaryInbound' : 'pendingInbound';
    receiptBatch.value = preview;
    receipt.value = {
      name: { zh: `${preview.selectedProducts} 个已勾选商品` },
      sizePrices: preview.items.flatMap(p => p.sizePrices.filter(s => s[field] > 0).map(s => ({ ...s, sku: p.sku, productId: p.id }))),
    };
    receiptSource.value = source;
    receiptRequest.value = crypto.randomUUID();
    receiptConflict.value = false;
    receiptError.value = preview.units ? '' : '所选商品没有已保存的可处理数量';
    receiptOpen.value = true;
  } catch (e) {
    notifyError(e);
  } finally {
    preparingBatch.value = false;
  }
}
async function receive() {
  if (receiving.value) return;
  receiving.value = true;
  receiptError.value = "";
  try {
    const result = await save(
      `inventory/${receiptBatch.value ? 'batch' : receipt.value.id}/${receiptSource.value === 'defective' ? 'defective/return' : receiptSource.value === 'temporary' ? 'temporary/receive' : 'receive'}`,
      receiptBatch.value ? { items: receiptBatch.value.items.map(p => ({ productId: p.id, version: p.version })), requestId: receiptRequest.value } : { version: receipt.value.version, requestId: receiptRequest.value },
      "POST",
    );
    receiptOpen.value = false;
    ElMessage.success(
      receiptBatch.value ? `${receiptSource.value === 'defective' ? '打回' : '入库'}完成：${result.processedProducts} 个商品，共 ${result.units} 件，跳过 ${result.skippedProductIds.length} 个无数量商品` : receiptSource.value === 'defective' ? `打回完成：${result.returnedSizes} 个尺码，共 ${result.returnedUnits} 件` : `入库完成：${result.receivedSizes} 个尺码，共 ${result.receivedUnits} 件`,
    );
    if (receiptBatch.value) clearSelection();
    list.load();
  } catch (e) {
    receiptError.value = e.message;
    receiptConflict.value = e.status === 409;
  } finally {
    receiving.value = false;
  }
}
onMounted(async () => {
  try {
    categories.value = (await api("catalog-options")).items;
  } catch (e) {
    notifyError(e);
  }
});
</script>

<style scoped>
.registration-product { display: flex; align-items: center; gap: 14px; padding: 2px 0 20px; }
.registration-product :deep(img) { width: 56px; height: 64px; border-radius: 8px; object-fit: cover; }
.registration-product__content { min-width: 0; }
.registration-product h3 { margin: 0 0 9px; font-size: 16px; line-height: 1.5; color: #1e293b; }
.registration-product__meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; color: #7a8699; font-size: 12px; }
.registration-sku { padding: 2px 7px; border-radius: 4px; background: #f1f5f9; color: #475569; font-weight: 600; }
.registration-guide { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; margin-bottom: 16px; background: #f6f8fb; border: 1px solid #edf0f5; border-radius: 8px; color: #64748b; font-size: 12px; line-height: 1.7; }
.registration-guide strong { color: #475569; font-weight: 500; }
.registration-rule-trigger { flex-shrink: 0; color: #64748b; padding: 5px 6px; font-size: 12px; height: 30px; }
.registration-rule-trigger :deep(.el-icon) { margin-left: 6px; }
.registration-rules { color: #475569; font-size: 12px; line-height: 1.8; }
.registration-rules > strong { color: #1e293b; font-size: 14px; }
.registration-rules ul { margin: 10px 0 0; padding-left: 18px; }
.registration-rules li + li { margin-top: 8px; }
.registration-table { border: 1px solid #e8edf3; border-radius: 8px; --el-table-border-color: #edf0f5; --el-table-header-bg-color: #f7f9fc; --el-table-row-hover-bg-color: #f8faff; }
.registration-table :deep(th.el-table__cell) { height: 44px; color: #64748b; font-weight: 600; }
.registration-table :deep(td.el-table__cell) { padding: 14px 0; }
.registration-table :deep(.registration-row-changed) { --el-table-tr-bg-color: #f8fbff; }
.registration-size { display: flex; flex-direction: column; align-items: flex-start; padding-left: 4px; }
.registration-size > strong { color: #334155; font-size: 13px; font-weight: 600; }
.registration-quantity { width: 124px; margin: 0 auto; }
.registration-quantity :deep(.el-input-number) { width: 124px; height: 36px; }
.registration-quantity :deep(.el-input__wrapper) { height: 36px; border-radius: 6px; }
.registration-quantity :deep(.el-input__inner) { color: #334155; font-size: 14px; font-weight: 500; font-variant-numeric: tabular-nums; }
.registration-quantity :deep(.el-input-number__increase), .registration-quantity :deep(.el-input-number__decrease) { width: 24px; color: #7a8699; background: #f8fafc; }
.registration-footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.registration-save-note { color: #7a8699; font-size: 12px; text-align: left; }
.registration-footer__actions { display: flex; flex-shrink: 0; }
@media (max-width: 600px) {
  .registration-guide { align-items: flex-start; }
  .registration-product h3 { font-size: 14px; }
  .registration-product :deep(img) { width: 44px; height: 52px; }
  .registration-footer { flex-wrap: wrap; justify-content: flex-end; }
  .registration-save-note { margin-right: auto; }
}
.inventory-history {
  margin-top: 24px;
}
.history-role {
  display: block;
  color: var(--muted);
}
.history-size {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 4px 0;
}
.history-field {
  display: inline-block;
}
.inventory-expanded {
  padding: 18px 24px;
  background: #f8fafc;
}
.inventory-expanded .stock-grid {
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
}
.stock-cell {
  background: white;
  padding: 12px;
}
.stock-cell strong {
  font-size: 13px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}
.stock-line {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  margin-top: 8px;
}
.stock-line span {
  color: var(--muted);
}
.stock-line.inbound b {
  color: #b45309;
}
</style>

<style scoped>
@media(max-width:767px){
.m-stock-summary{display:grid;grid-template-columns:1fr 1fr;padding:0 3px 19px;gap:30px}.m-stock-summary span{display:block;color:#9aa7b9;font-size:11px;margin-bottom:8px}.m-stock-summary strong{font-size:28px;font-weight:700;color:#182b49;letter-spacing:-.7px}.m-stock-summary small{font-size:10px;font-weight:400;margin-left:5px;color:#a4afbe}.m-stock-summary .is-amber{color:#c29664}.m-stock-extra-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:13px;margin-bottom:15px;color:#9aa8bb;font-size:10px}.m-stock-extra-summary b{display:block;font-size:15px;color:#586f8e;margin-top:3px}.m-stock-stage{display:flex;align-items:center;justify-content:space-between;font-size:10px;color:#a3afbf;padding:1px 2px 12px}.m-stock-stage :deep(.el-select){width:126px}.m-stock-stage :deep(.el-select__wrapper){box-shadow:none;background:none;padding-left:0;font-size:12px;color:#546f94}
.m-stock-card{background:white;border:1px solid #e9eef6;border-radius:18px;padding:16px;box-sizing:border-box}.m-stock-card.is-selected{border-color:#9ebcf0;background:#f8fbff}.m-stock-head{border:0;background:none;width:100%;padding:0;display:flex;align-items:center;gap:11px;text-align:left;color:#182b49}.m-stock-head :deep(img){width:43px;height:52px;object-fit:contain;border-radius:9px}.m-stock-copy{flex:1;min-width:0}.m-stock-copy strong{font-size:12px;overflow-wrap:anywhere}.m-stock-copy small{display:block;font-size:10px;color:#9dabbe;margin-top:5px}.m-stock-total{font-size:21px;font-weight:650;white-space:nowrap}.m-stock-total small{display:block;font-size:9px;text-align:right;font-weight:400;color:#a4afbe}.m-stock-sizes{display:flex;gap:7px;margin-top:17px;overflow:auto}.m-stock-sizes button{flex:1;min-width:46px;min-height:57px;border:0;border-radius:10px;background:#f5f8fc;color:#5b7498;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:6px}.m-stock-sizes span{font-size:9px;color:#a4afc0;overflow-wrap:anywhere}.m-stock-sizes b{font-size:14px;font-weight:550}.m-stock-sizes .is-negative{background:#fff4eb;color:#c08e5f}.m-stock-foot{display:flex;align-items:center;justify-content:space-between;margin-top:10px;font-size:9px;color:#a4afbf;gap:7px}.m-stock-foot :deep(.el-button){font-size:11px;min-height:38px;padding:0 2px}.m-stock-foot .is-negative{color:#c29664}.m-stock-check{width:21px;height:21px;display:grid;place-items:center;border-radius:6px;border:1px solid #c6d5ed;color:#2f69eb;flex:none}.m-stock-batch{position:sticky;bottom:75px;z-index:12;display:flex;align-items:center;justify-content:space-between;background:white;border:1px solid #e3ebf7;border-radius:15px;padding:9px;gap:4px;margin-bottom:13px;box-shadow:0 5px 22px #243c6210}.m-stock-batch strong{font-size:11px}.m-stock-batch :deep(.el-button){font-size:11px;margin:0;min-height:38px}
.registration-product{padding-bottom:13px}.registration-product h3{font-size:13px}.registration-product__meta{font-size:10px}.registration-guide{font-size:10px;background:#f0f5fc;border:0}.registration-rule-trigger{font-size:10px}.m-registration-sizes{display:flex;gap:7px;overflow:auto;padding:4px 0 16px}.m-registration-sizes button{position:relative;border:1px solid #e0e8f4;border-radius:12px;min-width:47px;min-height:44px;padding:9px 12px;color:#9aabc1;background:white;font-size:12px;flex:none}.m-registration-sizes button.active{background:#2f69eb;color:white;border-color:#2f69eb}.m-registration-sizes button.changed:after{content:'';position:absolute;right:5px;top:5px;width:5px;height:5px;border-radius:50%;background:#e3b486}.m-registration-card{background:white;border:1px solid #e4ebf5;border-radius:18px;padding:17px}.m-registration-title{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:16px}.m-registration-title strong{font-size:12px;color:#465f82}.m-registration-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px 14px}.m-registration-grid>label{display:flex;flex-direction:column;min-width:0;gap:8px}.m-registration-grid>label>span{font-size:10px;color:#91a3bd}.m-registration-grid :deep(.el-input-number){width:100%}.m-registration-grid :deep(.el-input__wrapper){min-height:46px;border-radius:11px;background:#f8fbff;box-shadow:0 0 0 1px #e2eaf6 inset}.m-registration-grid :deep(input){font-size:16px;text-align:left}.m-registration-grid :deep(.quantity-change){font-size:10px}.m-registration-history{margin-top:18px}.m-registration-history>summary{font-size:12px;color:#6c84a5;min-height:44px;display:flex;align-items:center;justify-content:space-between}.m-registration-history small{font-size:10px;color:#a0aec2}.registration-footer{width:100%;flex-wrap:wrap}.registration-save-note{font-size:10px}.registration-footer__actions{width:100%;display:flex;gap:10px}.registration-footer__actions :deep(.el-button){flex:1;margin:0;min-height:44px;border-radius:12px}.registration-footer__actions :deep(.el-button--primary){flex:1.5}
}
</style>
