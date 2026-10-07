<template>
  <section v-if="!managerOnly" class="customer-template-bar">
    <div class="panel-title">
      <strong>客户预设模板</strong>
      <div>
        <ElButton :disabled="applying" @click="edit(null, profile)">保存当前资料为模板</ElButton>
        <ElButton @click="managerOpen = true">管理模板</ElButton>
      </div>
    </div>
    <ElSelect v-model="selectedId" filterable remote clearable :remote-method="searchOptions"
      :loading="optionsLoading || applying" :disabled="applying" class="full-width"
      aria-label="客户预设模板" placeholder="搜索模板名称、客户或公司，选择后自动填入" @change="applySelected">
      <ElOption v-for="item in options" :key="item.id" :value="item.id"
        :label="`${item.name} · ${item.customer.companyName || item.customer.name || '客户已删除'}`"
        :disabled="!item.customerActive" />
    </ElSelect>
    <small>管理员可查看全部模板，其他人员仅可查看自己创建的模板。仅填入客户资料、备注和附件，商品明细及金额不变。</small>
    <ElAlert v-if="optionsError" :title="optionsError" type="error" :closable="false">
      <ElButton text @click="searchOptions()">重试</ElButton>
    </ElAlert>
  </section>

  <ElDrawer v-model="managerOpen" title="客户模板管理" size="850px" :close-on-click-modal="false"
    :before-close="closeManager">
    <ElAlert title="管理员可管理全部模板，其他人员仅可管理自己创建的模板；修改或删除模板不会改变已创建的订单。" type="info" :closable="false" />
    <form class="filters section-gap" @submit.prevent="page = 1; loadList()">
      <ElInput v-model="keyword" placeholder="模板名称、联系人、客户、公司或邮箱" clearable />
      <ElButton type="primary" native-type="submit">查询</ElButton>
      <ElButton @click="edit()">＋ 新建客户模板</ElButton>
    </form>
    <ElAlert v-if="listError" :title="listError" type="error" :closable="false">
      <ElButton text @click="loadList">重试</ElButton>
    </ElAlert>
    <ElTable :data="rows" v-loading="listLoading" empty-text="暂无客户模板，可先新建模板后再下单">
      <ElTableColumn prop="name" label="模板名称" min-width="160" />
      <ElTableColumn label="商城客户" min-width="140"><template #default="{ row }">
        {{ row.customer.companyName || row.customer.name || '客户已删除' }}
        <small v-if="!row.customerActive" class="negative">（账号停用或已删除）</small>
      </template></ElTableColumn>
      <ElTableColumn prop="contactName" label="联系人" width="100" />
      <ElTableColumn prop="country" label="国家" width="100" />
      <ElTableColumn prop="creatorName" label="创建人" width="100" />
      <ElTableColumn label="操作" :width="managerOnly ? 100 : 190"><template #default="{ row }">
        <ElButton v-if="!managerOnly" link type="primary" :disabled="!row.customerActive || applying"
          @click="applySelected(row.id)">填入订单</ElButton>
        <ElButton link type="primary" :disabled="applying" @click="edit(row.id)">编辑</ElButton>
        <ElButton link type="danger" :disabled="listLoading || applying" @click="remove(row)">删除</ElButton>
      </template></ElTableColumn>
    </ElTable>
    <ElPagination class="section-gap" :current-page="page" :page-size="25" :total="total"
      layout="total, prev, pager, next" @current-change="page = $event; loadList()" />
  </ElDrawer>

  <ElDialog v-model="editOpen" :title="draft.id ? '编辑客户模板' : '新建客户模板'" width="760px" top="4vh" class="customer-template-dialog"
    append-to-body :close-on-click-modal="false" :before-close="closeEdit">
    <ElAlert v-if="editError" :title="editError" type="error" :closable="false">
      <ElButton v-if="conflict" text :disabled="templateSaving || filesBusy" @click="readLatest">重新加载模板（替换草稿）</ElButton>
    </ElAlert>
    <ElForm ref="templateForm" :model="draft" label-position="top" :disabled="templateSaving || editLoading">
      <ElFormItem label="模板名称" prop="name" :rules="[{ required: true, whitespace: true, message: '请填写模板名称' }]">
        <ElInput v-model="draft.name" maxlength="120" placeholder="例如：德国客户 · 常用收货地址" />
      </ElFormItem>
      <ElFormItem label="商城客户" prop="profile.userId" :rules="[{ required: true, message: '请选择商城客户' }]">
        <ElSelect v-model="draft.profile.userId" filterable remote :remote-method="searchCustomers"
          :loading="customerLoading" class="full-width" placeholder="搜索客户姓名、公司或邮箱">
          <ElOption v-for="customer in customers" :key="customer.id" :value="customer.id"
            :label="`${customer.name} · ${customer.companyName || customer.email}`" />
        </ElSelect>
      </ElFormItem>
      <div class="detail-grid">
        <ElFormItem v-for="field in customerFields" :key="field.key" :label="field.label">
          <ElInput v-model="draft.profile[field.key]" maxlength="500" />
        </ElFormItem>
      </div>
      <small>资料可以提前分次保存；正式创建订单时仍需补齐必填收货信息。</small>
      <ElFormItem label="备注"><ElInput v-model="draft.profile.note" type="textarea" :rows="3" maxlength="5000" /></ElFormItem>
      <ElFormItem label="备注图片（最多 9 张）">
        <ImageUploader :key="editorKey" v-model="draft.profile.labelImageUrls" :max="9" @busy="imagesBusy = $event" />
      </ElFormItem>
      <ElFormItem label="PDF 附件">
        <PdfAttachment :key="editorKey" v-model="draft.profile.labelPdfUrl" @busy="pdfBusy = $event" />
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton :disabled="templateSaving || filesBusy || editLoading" @click="closeEdit()">取消</ElButton>
      <ElButton type="primary" :loading="templateSaving" :disabled="filesBusy || editLoading" @click="saveTemplate">保存客户模板</ElButton>
    </template>
  </ElDialog>
</template>
<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { api, save, confirm, notifyError, useDirty } from '../composables/workbench';
import { customerFields, customerProfile } from '../utils/customerTemplates';
import ImageUploader from './ImageUploader.vue';
import PdfAttachment from './PdfAttachment.vue';
const props = defineProps({ open: Boolean, managerOnly: Boolean, profile: Object, customer: Object });
const emit = defineEmits(['update:open', 'apply', 'busy']);
const managerOpen = ref(props.open), editOpen = ref(false), selectedId = ref();
const options = ref([]), optionsLoading = ref(false), optionsError = ref('');
const rows = ref([]), page = ref(1), total = ref(0), keyword = ref(''), listLoading = ref(false), listError = ref('');
const templateForm = ref(), templateSaving = ref(false), editLoading = ref(false), editError = ref(''), conflict = ref(false);
const imagesBusy = ref(false), pdfBusy = ref(false), applying = ref(false), editorKey = ref(0);
const customers = ref([]), customerLoading = ref(false);
const draft = reactive({ id: null, name: '', version: '', profile: customerProfile() });
const filesBusy = computed(() => imagesBusy.value || pdfBusy.value);
const { markClean, canLeave } = useDirty(() => draft);
let optionSerial = 0, listSerial = 0, customerSerial = 0;
watch(() => props.open, value => { managerOpen.value = value; });
watch(managerOpen, value => {
  emit('update:open', value);
  if (value) { page.value = 1; keyword.value = ''; loadList(); }
});
watch(() => editOpen.value || applying.value || editLoading.value, value => emit('busy', value));
onMounted(() => { if (!props.managerOnly) searchOptions(); });
async function searchOptions(search = '') {
  const current = ++optionSerial;
  optionsLoading.value = true; optionsError.value = '';
  try {
    const result = await api('orders/templates?' + new URLSearchParams({ page: 1, pageSize: 100, keyword: search }));
    if (current === optionSerial) options.value = result.items;
  } catch (error) { if (current === optionSerial) optionsError.value = error.message; }
  finally { if (current === optionSerial) optionsLoading.value = false; }
}
async function loadList() {
  const current = ++listSerial;
  listLoading.value = true; listError.value = '';
  try {
    const result = await api('orders/templates?' + new URLSearchParams({ page: page.value, pageSize: 25, keyword: keyword.value }));
    if (current === listSerial) { rows.value = result.items; total.value = result.total; }
  } catch (error) { if (current === listSerial) listError.value = error.message; }
  finally { if (current === listSerial) listLoading.value = false; }
}
async function searchCustomers(search = '') {
  const current = ++customerSerial;
  customerLoading.value = true;
  try {
    const result = await api('orders/customers?' + new URLSearchParams({ page: 1, pageSize: 100, keyword: search }));
    if (current === customerSerial) {
      const chosen = customers.value.find(customer => customer.id === draft.profile.userId);
      customers.value = result.items;
      if (chosen && !customers.value.some(customer => customer.id === chosen.id)) customers.value.unshift(chosen);
    }
  } catch (error) { if (current === customerSerial) editError.value = error.message; }
  finally { if (current === customerSerial) customerLoading.value = false; }
}
async function edit(id = null, source = {}) {
  if (templateSaving.value || editLoading.value || filesBusy.value) return;
  editLoading.value = true; editError.value = ''; conflict.value = false;
  try {
    const item = id ? (await api(`orders/templates/${id}`)).template : null;
    Object.assign(draft, { id, name: item?.name || '', version: item?.version || '', profile: customerProfile(item?.profile || source || {}) });
    const chosen = item?.customer || (props.customer?.id === draft.profile.userId ? props.customer : null);
    customers.value = chosen?.id ? [chosen] : [];
    editorKey.value++; imagesBusy.value = false; pdfBusy.value = false;
    markClean(); editOpen.value = true;
    await nextTick(); templateForm.value?.clearValidate();
    await searchCustomers();
  } catch (error) { notifyError(error); }
  finally { editLoading.value = false; }
}
async function closeEdit(done) {
  if (templateSaving.value || filesBusy.value || editLoading.value || !(await canLeave())) return;
  markClean(); editOpen.value = false;
  if (typeof done === 'function') done();
}
function closeManager(done) {
  if (editOpen.value || applying.value) return;
  managerOpen.value = false;
  if (typeof done === 'function') done();
}
async function saveTemplate() {
  if (templateSaving.value || filesBusy.value || editLoading.value || !(await templateForm.value.validate().catch(() => false))) return;
  templateSaving.value = true; editError.value = ''; conflict.value = false;
  try {
    await save(draft.id ? `orders/templates/${draft.id}` : 'orders/templates', {
      name: draft.name, profile: customerProfile(draft.profile), ...(draft.id ? { version: draft.version } : {}),
    }, draft.id ? 'PUT' : 'POST');
    markClean(); editOpen.value = false;
    ElMessage.success('客户模板已保存，仅创建者及管理员可使用');
    if (managerOpen.value) await loadList();
    if (!props.managerOnly) await searchOptions();
  } catch (error) { editError.value = error.message; conflict.value = error.status === 409; }
  finally { templateSaving.value = false; }
}
async function readLatest() {
  if (await confirm('重新加载会替换当前模板草稿，是否继续？')) {
    await edit(draft.id);
  }
}
async function remove(item) {
  if (!(await confirm(`删除客户模板“${item.name}”？已创建的订单及附件不会改变。`))) return;
  listLoading.value = true;
  try {
    await save(`orders/templates/${item.id}`, { version: item.version }, 'DELETE');
    if (rows.value.length === 1 && page.value > 1) page.value--;
    await loadList();
    if (!props.managerOnly) await searchOptions();
    if (selectedId.value === item.id) selectedId.value = undefined;
    ElMessage.success('客户模板已删除');
  } catch (error) { notifyError(error); await loadList(); }
  finally { listLoading.value = false; }
}
async function applySelected(id) {
  if (!id || props.managerOnly || applying.value) return;
  applying.value = true;
  try {
    const item = (await api(`orders/templates/${id}`)).template;
    if (!item.customerActive) { ElMessage.warning('该模板的商城账号已停用或删除，请先修改模板客户'); return; }
    emit('apply', item);
    managerOpen.value = false;
  } catch (error) { notifyError(error); }
  finally { applying.value = false; }
}
</script>
<style scoped>
.customer-template-bar { padding: 16px; margin-bottom: 22px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-color-primary-light-9); }
.customer-template-bar .panel-title { margin-bottom: 12px; flex-wrap: wrap; gap: 10px; }
.customer-template-bar small { display: block; margin-top: 8px; }
:global(.customer-template-dialog .el-dialog__body) { max-height: calc(90vh - 120px); overflow-y: auto; }
:global(.customer-template-dialog) .detail-grid { gap: 0 16px; }
</style>
