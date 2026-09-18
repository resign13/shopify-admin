<template>
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
    <form class="filters" @submit.prevent="list.apply(filters)">
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
    </form>
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
  <ElDrawer
    v-model="open"
    :title="form.id ? '编辑账号' : '新建账号'"
    size="520px"
    :before-close="close"
    ><ElForm ref="formRef" :model="form" label-position="top"
      ><ElFormItem
        label="姓名"
        prop="name"
        :rules="[{ required: true, message: '请填写姓名' }]"
        ><ElInput v-model.trim="form.name" /></ElFormItem
      ><ElFormItem v-if="!admin" label="公司名称"
        ><ElInput v-model.trim="form.companyName" /></ElFormItem
      ><ElFormItem
        label="登录账号 / 邮箱"
        prop="email"
        :rules="[{ required: true, message: '请填写登录账号' }]"
        ><ElInput v-model.trim="form.email" autocomplete="off" /></ElFormItem
      ><ElFormItem v-if="admin" label="岗位角色"
        ><ElSelect v-model="form.role"
          ><ElOption
            v-for="(label, value) in roleNames"
            :key="value"
            :value="value"
            :label="label"
        /></ElSelect>
        <p class="small-note section-gap">
          {{ roleHelp[form.role] }}
        </p></ElFormItem
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
import { reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import PageHeader from "./PageHeader.vue";
import DataTable from "./DataTable.vue";
import { useAdminAuthStore } from "../stores/auth";
import {
  save,
  useList,
  useDirty,
  notifyError,
  confirm,
  dateTime,
  roleNames,
} from "../composables/workbench";
const props = defineProps({ admin: Boolean }),
  auth = useAdminAuthStore(),
  resource = props.admin ? "admin-users" : "store-users",
  list = useList(resource);
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
  admin: "全部后台功能，包括账号管理和操作日志。",
  sales: "经营分析、商品、库存、订单及商城运营；不含账号与日志管理。",
  warehouse: "订单与库存管理，可编辑库存、合同未送并导入导出。",
  customer: "仅查看库存；不显示合同未送，不允许编辑或导入导出。",
};
const columns = [
  { prop: "name", label: "姓名", width: 140, sortable: true },
  { prop: "email", label: "登录账号", width: 200 },
  ...(props.admin
    ? [{ prop: "role", label: "角色" }]
    : [{ prop: "companyName", label: "公司" }]),
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
    ...row,
    password: "",
  });
  error.value = "";
  open.value = true;
  markClean();
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
      form,
      form.id ? "PUT" : "POST",
    );
    markClean();
    open.value = false;
    ElMessage.success("账号已保存");
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
