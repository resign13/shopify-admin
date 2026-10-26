<template>
  <ElDrawer :model-value="open" title="订单草稿" size="min(860px, 100vw)" :close-on-click-modal="false" @update:model-value="$emit('update:open', $event)">
    <ElAlert title="草稿保存在服务器，不生成订单、不占库存。业务员只看自己的；管理员可查看全部，其他人的草稿只读。" type="info" :closable="false" />
    <form class="filters section-gap" @submit.prevent="page = 1; load()">
      <ElSelect v-if="auth.isSuperAdmin" v-model="scope" aria-label="草稿查看范围" @change="page = 1; load()">
        <ElOption label="我的草稿" value="mine"/><ElOption label="全部草稿" value="all"/>
      </ElSelect>
      <ElInput v-model="keyword" aria-label="搜索草稿" placeholder="联系人、客户、公司、来源订单号" clearable />
      <ElButton type="primary" native-type="submit">查询</ElButton>
    </form>
    <ElAlert v-if="error" :title="error" type="error" :closable="false"><ElButton text @click="load">重试</ElButton></ElAlert>
    <AdaptiveTable :data="rows" v-loading="loading" empty-text="暂无保存的草稿">
      <ElTableColumn label="客户 / 联系人" min-width="160"><template #default="{row}"><strong>{{ row.contactName }}</strong><div class="small-note">{{ row.customerName }}</div></template></ElTableColumn>
      <ElTableColumn label="来源" min-width="125"><template #default="{row}"><OrderNumber v-if="row.sourceOrderNo" :value="row.sourceOrderNo" /><span v-else>新增订单</span></template></ElTableColumn>
      <ElTableColumn prop="itemCount" label="件数" width="65"/>
      <ElTableColumn prop="creatorName" label="创建人" width="100"/>
      <ElTableColumn label="保存时间" min-width="150"><template #default="{row}"><small>{{ dateTime(row.updatedAt) }}</small></template></ElTableColumn>
      <ElTableColumn label="操作" width="145"><template #default="{row}">
        <ElButton link type="primary" :disabled="loading" @click="$emit('select', row)">{{ row.canEdit ? '继续编辑' : '查看' }}</ElButton>
        <ElButton v-if="row.canEdit" link type="danger" :disabled="loading" @click="remove(row)">删除</ElButton>
      </template></ElTableColumn>
    </AdaptiveTable>
    <ElPagination class="section-gap" :current-page="page" :page-size="10" :total="total" layout="total, prev, pager, next" @current-change="page = $event; load()" />
  </ElDrawer>
</template>
<script setup>
import AdaptiveTable from "./AdaptiveTable";
import { ref, watch } from 'vue';
import OrderNumber from './OrderNumber.vue';
import { api, save, confirm, dateTime } from '../composables/workbench';
import { useAdminAuthStore } from '../stores/auth';
const props = defineProps({open:Boolean});
defineEmits(['update:open','select']);
const auth=useAdminAuthStore(), rows=ref([]), page=ref(1), total=ref(0), scope=ref('mine'), keyword=ref(''), loading=ref(false), error=ref('');
let serial=0;
async function load() {
  const current=++serial; loading.value=true; error.value='';
  try {
    const result=await api('orders/drafts?'+new URLSearchParams({page:page.value,scope:scope.value,keyword:keyword.value}));
    if (current!==serial) return;
    rows.value=result.items; total.value=result.total;
    if (!rows.value.length && page.value>1) { page.value--; return load(); }
  } catch(e) { if(current===serial) error.value=e.message; }
  finally { if(current===serial) loading.value=false; }
}
async function remove(row) {
  if (!(await confirm('删除这份草稿？不会删除附件文件或影响任何正式订单。'))) return;
  loading.value=true;
  try { await save(`orders/drafts/${row.id}`,{version:row.version},'DELETE'); await load(); }
  catch(e) { error.value=e.message; loading.value=false; }
}
watch(()=>props.open, value=>{ if(value) {page.value=1;load();} else ++serial; });
</script>
