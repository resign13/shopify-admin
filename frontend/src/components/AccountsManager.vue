<template>
  <section v-if="isPhone" class="mobile-accounts" :data-testid="admin ? 'mobile-admin-accounts' : 'mobile-store-accounts'">
    <header class="mobile-system-heading"><div><h1>{{ admin ? '后台账号' : '商城账号' }}</h1><p>{{ admin ? '每位同事，恰当的访问权限' : '让客户关系，保持清晰' }}</p></div><ElButton type="primary" circle aria-label="新建账号" @click="edit()"><ElIcon><Plus /></ElIcon></ElButton></header>
    <div class="mobile-system-search"><ElInput v-model="filters.keyword" clearable :placeholder="admin ? '搜索姓名或工作账号' : '搜索姓名、账号或公司'" @change="list.apply(filters)" @keyup.enter="list.apply(filters)"><template #prefix><ElIcon><Search /></ElIcon></template></ElInput><ElButton aria-label="筛选账号" @click="mobileFiltersOpen=true"><ElIcon><Filter /></ElIcon></ElButton></div>
    <div class="mobile-system-section"><span>{{ list.total }} 位{{ admin ? '团队成员' : '商城客户' }}</span><MobileActionMenu label="更多"><ElButton @click="mobileFiltersOpen=true">筛选与排序</ElButton><ElButton @click="reset">重置筛选</ElButton><ElButton @click="list.load">刷新列表</ElButton></MobileActionMenu></div>
    <ElAlert v-if="list.error" :title="list.error" type="error" :closable="false"><ElButton text @click="list.load">重试</ElButton></ElAlert>
    <div v-loading="list.loading" class="mobile-account-list"><article v-for="row in list.rows" :key="row.id" class="mobile-account-card"><button class="mobile-account-main" @click="edit(row)"><span class="mobile-account-avatar">{{ row.name?.slice(0,1) }}</span><span class="mobile-account-copy"><span class="mobile-account-name"><strong>{{ row.name }}</strong><ElTag size="small" :type="row.status==='active'?'success':'info'">{{ row.status==='active'?'启用':'停用' }}</ElTag></span><span>{{ admin ? roleNames[row.role] : row.companyName || '未填写公司' }}</span><small>{{ row.email }}</small></span></button><footer><small>{{ admin ? editableRolePermissions(row.role,row.permissions).length+' 项模块权限' : row.linkedAdminName ? '关联业务员 · '+row.linkedAdminName : '尚未关联业务员' }}</small><MobileActionMenu icon-only :label="row.name+' · 更多'"><ElButton @click="edit(row)">编辑账号</ElButton><ElButton type="danger" :disabled="admin && row.id===auth.user.id" @click="remove(row)">删除账号</ElButton></MobileActionMenu></footer></article><ElEmpty v-if="!list.loading&&!list.rows.length" description="没有找到匹配账号" :image-size="64" /></div>
    <ElPagination v-if="list.total" class="mobile-system-pagination" :current-page="Number(list.query.page)" :page-size="Number(list.query.pageSize)" :total="list.total" layout="prev, pager, next" :pager-count="5" @current-change="list.query.page=$event" />
    <ElDrawer v-model="mobileFiltersOpen" title="账号筛选" size="88%" direction="btt"><ElForm label-position="top"><ElFormItem label="账号状态"><ElSelect v-model="filters.status" clearable placeholder="全部状态"><ElOption label="启用" value="active"/><ElOption label="停用" value="disabled"/></ElSelect></ElFormItem><ElFormItem v-if="admin" label="岗位角色"><ElSelect v-model="filters.role" clearable placeholder="全部角色"><ElOption v-for="(label,value) in roleNames" :key="value" :label="label" :value="value"/></ElSelect></ElFormItem><ElFormItem label="排序"><ElSelect v-model="mobileSort"><ElOption label="创建时间 · 最新优先" value="createdAt:descending"/><ElOption label="创建时间 · 最早优先" value="createdAt:ascending"/><ElOption label="姓名 · 升序" value="name:ascending"/><ElOption label="姓名 · 降序" value="name:descending"/></ElSelect></ElFormItem><ElFormItem label="每页条数"><ElSelect :model-value="Number(list.query.pageSize)" @change="list.query={...list.query,page:1,pageSize:$event}"><ElOption v-for="n in [25,50,100]" :key="n" :label="n+' 条'" :value="n"/></ElSelect></ElFormItem></ElForm><template #footer><ElButton @click="reset">重置</ElButton><ElButton type="primary" @click="applyMobileFilters">查看结果</ElButton></template></ElDrawer>
  </section>
  <template v-else>
  <PageHeader
    :title="admin ? '后台账号' : '商城账号'"
    :description="
      admin
        ? '按岗位分配访问权限，管理团队工作账号。'
        : '管理客户登录账号、公司资料和启用状态。'
    "
    eyebrow="ACCOUNTS / 账号与系统"
    ><ElButton type="primary" @click="edit()">＋ 新建账号</ElButton></PageHeader
  >
  <section class="panel">
    <ResponsiveFilters :active="list.query" @remove="key => { filters[key] = ''; list.apply(filters); }" @submit.prevent="list.apply(filters)">
      <ElInput
        v-model="filters.keyword"
        clearable
        placeholder="搜索姓名、邮箱或公司"
      /><ElSelect v-model="filters.status" clearable placeholder="全部状态"
        ><ElOption label="启用" value="active" /><ElOption
          label="停用"
          value="disabled" /></ElSelect
      ><ElSelect
        v-if="admin"
        v-model="filters.role"
        clearable
        placeholder="全部角色"
        ><ElOption
          v-for="(label, value) in roleNames"
          :key="value"
          :value="value"
          :label="label" /></ElSelect
      ><ElButton type="primary" native-type="submit">查询</ElButton
      ><ElButton @click="reset">重置</ElButton>
    </ResponsiveFilters>
    <DataTable
      :storage-key="resource"
      :rows="list.rows"
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
      ><template #role="{ row }"
        ><ElTag type="info">{{ roleNames[row.role] }}</ElTag></template
      ><template #status="{ row }"
        ><ElTag :type="row.status === 'active' ? 'success' : 'info'">{{
          row.status === "active" ? "启用" : "停用"
        }}</ElTag></template
      ><template #createdAt="{ row }">{{ dateTime(row.createdAt) }}</template
      ><template #actions="{ row }"
        ><ElButton link type="primary" @click="edit(row)">编辑</ElButton
        ><ElButton
          link
          type="danger"
          :disabled="admin && row.id === auth.user.id"
          @click="remove(row)"
          >删除</ElButton
        ></template
      ></DataTable
    >
  </section>
  </template>
  <ElDrawer
    v-model="open"
    :title="form.id ? '编辑账号' : '新建账号'"
    :size="isPhone ? '100%' : '520px'"
    :before-close="close"
    :class="{'mobile-account-editor':isPhone}"
    ><ElForm ref="formRef" :model="form" label-position="top"
      ><ElFormItem
        label="姓名"
        prop="name"
        :rules="[{ required: true, message: '请填写姓名' }]"
        ><ElInput v-model.trim="form.name" /></ElFormItem
      ><ElFormItem v-if="!admin" label="公司名称"
        ><ElInput v-model.trim="form.companyName" /></ElFormItem
      ><ElFormItem v-if="!admin" label="关联后台业务员">
        <ElSelect v-model="form.linkedAdminId" clearable filterable placeholder="未关联" class="full-width">
          <ElOption v-for="person in salespeople" :key="person.id" :value="person.id" :label="`${person.name} · ${person.email}`" :disabled="person.status !== 'active' && person.id !== form.linkedAdminId" />
        </ElSelect>
        <p class="small-note">保存关联后，尚未归属的历史商城订单也计入该业务员。已归属订单不随关联关系修改而转移；两端登录和密码保持独立。</p>
      </ElFormItem>
      <ElFormItem
        label="登录账号 / 邮箱"
        prop="email"
        :rules="[{ required: true, message: '请填写登录账号' }]"
        ><ElInput v-model.trim="form.email" autocomplete="off" /></ElFormItem
      ><ElFormItem v-if="admin" label="岗位角色"
        ><ElSelect v-model="form.role" @change="changeRole"
          ><ElOption
            v-for="(label, value) in roleNames"
            :key="value"
            :value="value"
            :label="label"
        /></ElSelect>
        <p class="small-note section-gap">
          {{ roleHelp[form.role] }}
        </p></ElFormItem
      ><ElFormItem v-if="admin" label="模块权限">
        <details v-if="isPhone" class="mobile-account-permissions"><summary>模块权限 <span>已选 {{ form.permissions?.length||0 }} 项</span></summary>
        <div class="module-permissions">
          <p class="small-note">
              部门只决定默认勾选项，可按账号启用其他模块；未勾选的模块不显示，也不允许调用接口。业务归属等规则保持不变。
          </p>
          <div>
            <ElButton text @click="form.permissions = roleModules(form.role)"
              >全选可用模块</ElButton
            ><ElButton text @click="form.permissions = defaultRoleModules(form.role)">恢复部门默认</ElButton
            ><ElButton text @click="form.permissions = []">清空</ElButton>
          </div>
          <ElCheckboxGroup v-model="form.permissions">
            <section v-for="group in moduleGroups" :key="group.label">
              <strong>{{ group.label }}</strong>
              <div>
                <ElCheckbox
                  v-for="[key, label] in group.items"
                  :key="key"
                  :value="key"
                  :disabled="!roleModules(form.role).includes(key)"
                  >{{ label }}</ElCheckbox
                >
              </div>
            </section>
          </ElCheckboxGroup>
          <p class="small-note">
            已选
            {{
              form.permissions?.length || 0
            }}
              个模块。客户角色仍仅开放库存查看。
          </p>
        </div>
        </details>
        <template v-else>
        <div class="module-permissions">
          <p class="small-note">
              部门只决定默认勾选项，可按账号启用其他模块；未勾选的模块不显示，也不允许调用接口。业务归属等规则保持不变。
          </p>
          <div>
            <ElButton text @click="form.permissions = roleModules(form.role)"
              >全选可用模块</ElButton
            ><ElButton text @click="form.permissions = defaultRoleModules(form.role)">恢复部门默认</ElButton
            ><ElButton text @click="form.permissions = []">清空</ElButton>
          </div>
          <ElCheckboxGroup v-model="form.permissions">
            <section v-for="group in moduleGroups" :key="group.label">
              <strong>{{ group.label }}</strong>
              <div>
                <ElCheckbox
                  v-for="[key, label] in group.items"
                  :key="key"
                  :value="key"
                  :disabled="!roleModules(form.role).includes(key)"
                  >{{ label }}</ElCheckbox
                >
              </div>
            </section>
          </ElCheckboxGroup>
          <p class="small-note">
            已选
            {{
              form.permissions?.length || 0
            }}
              个模块。客户角色仍仅开放库存查看。
          </p>
        </div>
        </template> </ElFormItem
      ><ElFormItem label="账号状态"
        ><ElRadioGroup
          v-model="form.status"
          :disabled="admin && form.id === auth.user.id"
          ><ElRadio value="active">启用</ElRadio
          ><ElRadio value="disabled">停用</ElRadio></ElRadioGroup
        ></ElFormItem
      ><ElDivider content-position="left">{{
        form.id ? "修改密码" : "设置密码"
      }}</ElDivider
      ><ElFormItem
        :label="form.id ? '新密码（留空不修改）' : '登录密码'"
        prop="password"
        :rules="[{ validator: validatePassword }]"
        ><ElInput
          v-model="form.password"
          type="password"
          show-password
          autocomplete="new-password" /></ElFormItem
      ><ElAlert
        v-if="error"
        :title="error"
        type="error"
        :closable="false" /></ElForm
    ><template #footer
      ><ElButton :disabled="saving" @click="close()">取消</ElButton
      ><ElButton type="primary" :loading="saving" @click="submit"
        >保存账号</ElButton
      ></template
    ></ElDrawer
  >
</template>
<script setup>
import { useResponsive } from "../composables/responsive";
import MobileActionMenu from "./MobileActionMenu.vue";
import { Plus, Search, Filter } from "@element-plus/icons-vue";
import ResponsiveFilters from "./ResponsiveFilters.vue";
import { moduleGroups, roleModules, defaultRoleModules, editableRolePermissions } from "../permissions";
import { useRouter } from "vue-router";
import { reactive, ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import PageHeader from "./PageHeader.vue";
import DataTable from "./DataTable.vue";
import { useAdminAuthStore } from "../stores/auth";
import {
  save,
  api,
  useList,
  useDirty,
  notifyError,
  confirm,
  dateTime,
  roleNames,
} from "../composables/workbench";
const { isPhone } = useResponsive();
const mobileFiltersOpen=ref(false), mobileSort=ref("createdAt:descending");
function applyMobileFilters(){const [prop,order]=mobileSort.value.split(":");list.apply({...filters,sort:prop,direction:order==='ascending'?'asc':'desc'});mobileFiltersOpen.value=false;}
const props = defineProps({ admin: Boolean }),
  auth = useAdminAuthStore(),
  router = useRouter(),
  resource = props.admin ? "admin-users" : "store-users",
  list = useList(resource);
const salespeople = ref([]);
onMounted(async () => { if (!props.admin) { try { salespeople.value = (await api('salespeople')).items; } catch (e) { notifyError(e); } } });
const filters = reactive({
    keyword: list.query.keyword || "",
    status: list.query.status || "",
    role: list.query.role || "",
  }),
  open = ref(false),
  form = reactive({}),
  formRef = ref(),
  saving = ref(false),
  error = ref("");
const { markClean, canLeave } = useDirty(() => form);
const roleHelp = {
  finance: "默认财务管理和合同管理；可额外勾选其他后台模块。",
  admin: "可分配全部后台模块，实际访问范围以下方勾选为准。",
  sales: "默认经营分析、商品、库存、订单、分类和合同；其他模块可勾选，订单归属仍按本人隔离。",
  warehouse: "默认订单与库存；其他模块可勾选，订单金额隐藏和现有仓库操作范围保持不变。",
  customer: "仅查看库存；不显示合同未送，不允许编辑或导入导出。",
};
const columns = [
  { prop: "name", label: "姓名", width: 140, sortable: true },
  { prop: "email", label: "登录账号", width: 200 },
  ...(props.admin
    ? [{ prop: "role", label: "角色" }]
    : [{ prop: "companyName", label: "公司" }, { prop: "linkedAdminName", label: "关联业务员", width: 150 }]),
  { prop: "status", label: "状态", width: 90 },
  { prop: "createdAt", label: "创建时间", width: 180, sortable: true },
  { prop: "actions", label: "操作", width: 110 },
];
function reset() {
  Object.assign(filters, { keyword: "", status: "", role: "" });
  list.apply(filters);
}
function edit(row) {
  Object.keys(form).forEach((k) => delete form[k]);
  Object.assign(form, {
    name: "",
    email: "",
    password: "",
    status: "active",
    role: "sales",
    companyName: "",
    linkedAdminId: null,
    ...row,
    password: "",
  });
  if (props.admin)
    form.permissions = editableRolePermissions(form.role, row?.permissions);
  error.value = "";
  open.value = true;
  markClean();
}
function changeRole() {
    form.permissions = defaultRoleModules(form.role);
}
function validatePassword(_r, value, cb) {
  cb(!form.id && !value ? new Error("请设置登录密码") : undefined);
}
async function close(done) {
  if (saving.value) return;
  if (await canLeave()) {
    markClean();
    open.value = false;
    if (typeof done === "function") done();
  }
}
async function submit() {
  if (saving.value || !(await formRef.value.validate().catch(() => false)))
    return;
  saving.value = true;
  error.value = "";
  try {
    await save(
      `${resource}${form.id ? "/" + form.id : ""}`,
      props.admin ? form : { ...form, linkedAdminId: form.linkedAdminId || null },
      form.id ? "PUT" : "POST",
    );
    markClean();
    open.value = false;
    ElMessage.success("账号已保存");
    if (props.admin && form.id === auth.user.id) {
      await auth.initialize();
      if (!auth.can("admin-users")) {
        await router.replace(auth.defaultRoute);
        return;
      }
    }
    list.load();
  } catch (e) {
    error.value = e.message;
  } finally {
    saving.value = false;
  }
}
async function remove(row) {
  if (
    !(await confirm(
      `删除账号“${row.name}”？如果只需暂停访问，建议先停用账号。`,
      "删除账号",
    ))
  )
    return;
  try {
    await save(`${resource}/${row.id}`, {}, "DELETE");
    ElMessage.success("账号已删除");
    list.load();
  } catch (e) {
    notifyError(e);
  }
}
</script>

<style scoped>
.module-permissions {
  width: 100%;
}
.module-permissions section {
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
}
.module-permissions strong {
  display: block;
  line-height: 20px;
  font-size: 12px;
  color: var(--muted);
}
.module-permissions .el-checkbox {
  margin-right: 18px;
}
</style>

<style scoped>
@media(max-width:767px){.mobile-accounts{color:#182b49}.mobile-system-heading{display:flex;justify-content:space-between;align-items:center;margin:4px 0 22px;gap:14px}.mobile-system-heading h1{font-size:25px;letter-spacing:-.04em;margin:0}.mobile-system-heading p{font-size:11px;color:#8c9ab0;margin:7px 0 0}.mobile-system-heading>.el-button{width:42px;height:42px;border-radius:14px}.mobile-system-search{display:flex;gap:10px;margin-bottom:18px}.mobile-system-search>.el-input{flex:1;min-width:0}.mobile-system-search :deep(.el-input__wrapper){background:#edf1f8;box-shadow:none;border-radius:13px;min-height:44px}.mobile-system-search>.el-button{height:44px;width:44px;border-radius:13px;color:#8b9ebc}.mobile-system-section{display:flex;align-items:center;justify-content:space-between;min-height:42px;margin-bottom:12px;font-size:12px;font-weight:600}.mobile-account-list{display:flex;flex-direction:column;gap:12px;min-height:80px}.mobile-account-card{border:1px solid #e8edf5;border-radius:18px;background:#fff;overflow:hidden}.mobile-account-main{display:flex;align-items:center;gap:13px;padding:17px 16px;width:100%;background:none;border:0;text-align:left;color:inherit}.mobile-account-avatar{width:44px;height:44px;flex:0 0 44px;display:grid;place-items:center;border-radius:15px;background:#edf3ff;color:#6688c4;font-size:17px;font-weight:600}.mobile-account-copy{display:flex;flex-direction:column;gap:5px;flex:1;min-width:0}.mobile-account-name{display:flex;align-items:center;justify-content:space-between;gap:8px}.mobile-account-name strong{font-size:16px;font-weight:650;overflow-wrap:anywhere}.mobile-account-name :deep(.el-tag){font-size:10px;border:0;background:#edf6f2;color:#629e8a;flex-shrink:0}.mobile-account-copy>span:not(.mobile-account-name){font-size:12px;color:#7f92b1;overflow-wrap:anywhere}.mobile-account-copy>small{font-size:11px;color:#a4b0c3;overflow-wrap:anywhere}.mobile-account-card footer{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #f0f3f8;margin:0 16px;padding:4px 0 4px 57px;gap:8px}.mobile-account-card footer>small{font-size:11px;color:#a5b1c4}.mobile-account-card footer :deep(.el-button){font-size:10px;max-width:100px;overflow:hidden;text-overflow:ellipsis}.mobile-system-pagination{justify-content:center;margin-top:22px;max-width:100%;overflow:auto}}
</style>

<style scoped>
@media(max-width:767px){.mobile-account-permissions{width:100%;border:1px solid #e7edf6;border-radius:13px;background:#fafcff;padding:0 12px}.mobile-account-permissions>summary{display:flex;justify-content:space-between;align-items:center;gap:10px;cursor:pointer;min-height:46px;font-size:12px;color:#6d89b0}.mobile-account-permissions>summary span{font-size:10px;color:#a7b5c9}.mobile-account-permissions .module-permissions{padding-bottom:12px}.mobile-account-editor :deep(.el-form-item__label){font-size:12px;color:#7890b2}.mobile-account-editor :deep(.el-input__wrapper),.mobile-account-editor :deep(.el-select__wrapper){min-height:43px;border-radius:11px}.mobile-account-editor :deep(.el-select){width:100%}.mobile-account-editor :deep(.small-note){font-size:11px;line-height:1.8;color:#a1b0c5}.mobile-account-editor :deep(.el-checkbox){font-size:12px;margin-right:12px}.mobile-account-editor :deep(.el-divider__text){font-size:11px;color:#9dafc6}}
</style>
