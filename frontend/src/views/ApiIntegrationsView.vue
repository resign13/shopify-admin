<template>
  <section class="api-integration" v-loading="initialLoading">
    <div class="api-tabs" role="tablist" aria-label="API 对接">
      <button v-for="item in tabs" :key="item.key" role="tab" :aria-selected="tab === item.key" :class="{active: tab === item.key}" @click="changeTab(item.key)">{{ item.label }}</button>
      <span class="scope-label">商品素材 · 可售库存 · 只读</span>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notice" />
    <el-button v-if="!meta && !initialLoading" @click="load">重新加载</el-button>

    <template v-if="meta && tab === 'mine'">
      <div class="key-overview">
        <div class="key-heading"><h3>我的 Key</h3><el-tag :type="meta.status === 'enabled' ? 'success' : meta.adminBlocked ? 'danger' : 'info'">{{ apiStates[meta.status] }}</el-tag><el-button text size="small" :disabled="busy" @click="load">刷新</el-button></div>
        <div class="key-facts">
          <div><span>Key 标识</span><strong class="monospace">{{ meta.keyLabel || '尚未生成' }}</strong></div>
          <div><span>固定权限</span><strong>商品素材读取、可售库存读取</strong></div>
          <div><span>有效期（北京时间）</span><strong>{{ meta.expiresAt ? beijingTime(meta.expiresAt) : '长期有效' }}</strong></div>
          <div><span>最近调用（北京时间）</span><strong>{{ beijingTime(meta.lastUsedAt) }}</strong></div>
          <div><span>近 24 小时调用</span><strong>{{ meta.calls24h }} 次</strong></div>
        </div>
        <div class="key-actions">
          <el-button v-if="!meta.keyId" type="primary" :disabled="busy || meta.adminBlocked" @click="openGenerate(false)">生成 Key</el-button>
          <template v-else>
            <el-button :disabled="busy || meta.adminBlocked || meta.status === 'expired'" @click="toggleOwn">{{ meta.status === 'owner_disabled' ? '启用' : '停用' }}</el-button>
            <el-button :disabled="busy || meta.adminBlocked" @click="openGenerate(true)">重置 Key</el-button>
          </template>
          <span>{{ meta.adminBlocked ? '请由具有后台账号管理权限的人员恢复 API 授权。' : '完整密钥仅在生成或重置成功时展示一次。' }}</span>
        </div>
      </div>
      <div class="section-heading"><h3>最近调用</h3><span>仅保留 30 天 · 北京时间</span></div>
      <CallRecords :items="logs.items" :total="logs.total" :page="logPage" :loading="logsLoading" @page="value => { logPage=value; loadLogs(); }" />
    </template>

    <div v-if="meta && tab === 'docs'" class="api-docs">
      <h3>连接地址</h3><code>{{ baseUrl }}</code>
      <p>请求头：<code>Authorization: Bearer TOKEN</code>。仅支持 HTTPS 和读取；浏览器登录 Cookie 不作为凭证，Key 不具有订单、售价或后台操作权限。</p>
      <div class="table-scroll"><table><thead><tr><th>GET 接口</th><th>参数</th><th>返回</th></tr></thead><tbody>
        <tr><td>/products</td><td>limit（默认 50，最多 100）、cursor、keyword、categoryId、styleCodes、skus</td><td>items、nextCursor、limit、readAt、requestId</td></tr>
        <tr><td>/products/{productId}</td><td>颜色商品 ID</td><td>item、readAt、requestId；下架或缺失返回 404</td></tr>
        <tr><td>/inventory</td><td>productIds，逗号分隔，最多 100 个</td><td>items、notFoundIds、readAt、requestId</td></tr>
      </tbody></table></div>
      <h3>字段与同步口径</h3>
      <ul>
        <li>每条为一个颜色 SKU：productId、styleCode、sku、color、category（id/key/name）、title、summary、description、images、sizes。</li>
        <li>images：main、gallery（有序数组）、sizeChart、detail，均为原图 HTTPS 地址；缺失为 null。描述是原始文本，对接方显示 HTML 时自行净化。</li>
        <li>sizes：按本商品真实配置顺序的 { size, stock }；商品 ID＋真实尺码关联。stock 是可售数量，内部负库存按 0 返回，不补造尺码。</li>
        <li>库存接口仅返回 productId、styleCode、sku、sizes；notFoundIds 表示商品不存在或已下架，与库存为 0 不同。</li>
        <li>每次响应使用同一只读快照；readAt 为 UTC ISO 时间。跨页不是全库一致快照。只有完整拉取成功后再对账删除，失败时保留已有目录。</li>
        <li>款号和 SKU 筛选均可传逗号分隔列表，最多 100 项；关键词最多 200 字符。游标按商品 ID 递增，不是库存更新时间。</li>
          <li>每把 Key 默认 60 次／分钟，同一 IP 300 次／分钟；全部 Key 共用每秒 10 次额度。全局最多同时处理 4 个请求，单 Key 最多 2 个。429 按 Retry-After 等待并错峰重试；401 检查授权，409 刷新管理状态，503 表示尚未启用或服务暂忙。</li>
        <li>图片保持原公开访问规则，撤销 Key 不会撤回已下载的素材。Key 只放在服务端配置，不放入 URL、客户网页或日志。</li>
      </ul>
      <h3>curl</h3><pre>{{ examples.curl }}</pre><h3>Python</h3><pre>{{ examples.python }}</pre>
    </div>

    <template v-if="meta && tab === 'accounts' && canManage">
      <div class="account-search"><el-input v-model="accountKeyword" placeholder="搜索后台账号或姓名" clearable maxlength="200" @keyup.enter="searchAccounts" /><el-button :disabled="busy" @click="searchAccounts">查询</el-button></div>
      <el-table :data="accounts.items" v-loading="accountsLoading" empty-text="暂无账号" class="accounts-table">
        <el-table-column label="后台账号" min-width="170"><template #default="{row}"><div>{{ row.name }}</div><small>{{ row.email }}</small></template></el-table-column>
        <el-table-column label="部门" width="90"><template #default="{row}">{{ roles[row.role] }}</template></el-table-column>
        <el-table-column label="API 授权" min-width="140"><template #default="{row}">{{ !row.moduleAllowed ? '账号停用／未授予模块' : row.adminBlocked ? '管理员禁用' : '允许' }}</template></el-table-column>
        <el-table-column prop="keyLabel" label="Key 标识" min-width="150" />
        <el-table-column label="状态" width="110"><template #default="{row}">{{ apiStates[row.status] }}</template></el-table-column>
        <el-table-column label="到期时间" min-width="165"><template #default="{row}">{{ row.expiresAt ? beijingTime(row.expiresAt) : '长期有效' }}</template></el-table-column>
        <el-table-column label="最近调用" min-width="165"><template #default="{row}">{{ beijingTime(row.lastUsedAt) }}</template></el-table-column>
        <el-table-column label="操作" width="210" fixed="right"><template #default="{row}"><el-button text size="small" :disabled="busy" @click="manage(row, 'authorization')">{{ row.adminBlocked ? '恢复授权' : '禁用授权' }}</el-button><el-button text size="small" :disabled="busy || !row.keyId" @click="manage(row,'revoke')">作废 Key</el-button><el-button text size="small" @click="showAccountLogs(row)">调用</el-button></template></el-table-column>
      </el-table>
      <el-pagination class="pagination" layout="prev, pager, next, total" :total="accounts.total" :page-size="20" :current-page="accountPage" @current-change="value => { accountPage=value; loadAccounts(); }" />
    </template>

    <el-dialog v-model="generateOpen" :title="resetting ? '重置 Key' : '生成 Key'" width="min(480px, calc(100vw - 32px))" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p v-if="resetting">旧 Key 将立即失效，需要更新对接系统配置。</p>
      <p>到期时间（北京时间，留空表示长期有效）</p>
      <el-date-picker v-model="expiresInput" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" placeholder="长期有效" clearable style="width:100%" />
      <template #footer><el-button :disabled="busy" @click="generateOpen=false">取消</el-button><el-button type="primary" :loading="busy" @click="generate">{{ resetting ? '确认重置' : '确认生成' }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="secretOpen" title="请立即保存完整 Key" width="min(560px, calc(100vw - 32px))" append-to-body :close-on-click-modal="false" @close="clearSecret">
      <p>此密钥只展示一次。关闭后仅保留脱敏标识；若未保存，请重新重置。</p>
      <el-input :model-value="secret" readonly type="textarea" :rows="3" aria-label="完整 API Key" autocomplete="off" />
      <template #footer><el-button @click="copySecret">复制</el-button><el-button type="primary" @click="secretOpen=false; clearSecret()">已保存，关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="managerLogsOpen" :title="'调用记录 · ' + (logAccount?.name || '')" width="min(780px, calc(100vw - 32px))" append-to-body>
      <CallRecords :items="managerLogs.items" :total="managerLogs.total" :page="managerLogPage" :loading="managerLogsLoading" @page="value => { managerLogPage=value; loadManagerLogs(); }" />
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox, ElTable, ElTableColumn, ElPagination } from 'element-plus';
import 'element-plus/es/components/table/style/css';
import 'element-plus/es/components/pagination/style/css';
import 'element-plus/es/components/message/style/css';
import 'element-plus/es/components/message-box/style/css';
import { request } from '../api';
import { useAdminAuthStore } from '../stores/auth';
import { apiStates, beijingTime, expiryISO, apiExamples } from '../utils/apiIntegration';

// One shared table for own and explicitly authorized account logs. No request
// parameters/headers or raw tokens are stored in these objects.
const CallRecords = defineComponent({ props: ['items','total','page','loading'], emits: ['page'], setup(props,{emit}) {
  return () => h('div', [h(ElTable, { data:props.items, emptyText:props.loading?'加载中…':'暂无调用记录', 'aria-busy':props.loading }, () => [
    h(ElTableColumn, {label:'时间',minWidth:170}, {default:({row})=>beijingTime(row.time)}),
    h(ElTableColumn, {label:'接口',prop:'route',minWidth:260}),
    h(ElTableColumn, {label:'结果',prop:'status',width:80}),
    h(ElTableColumn, {label:'耗时',width:100}, {default:({row})=>row.durationMs+' ms'}),
  ]), h(ElPagination,{class:'pagination',layout:'prev, pager, next, total',total:props.total,pageSize:20,currentPage:props.page,'onUpdate:currentPage':value=>emit('page',value)})]);
}});
const auth=useAdminAuthStore(), tab=ref('mine'), meta=ref(null), canManage=ref(false), error=ref('');
const initialLoading=ref(false),busy=ref(false),baseUrl=ref(''),secret=ref(''),secretOpen=ref(false),generateOpen=ref(false),resetting=ref(false),expiresInput=ref('');
const logs=ref({items:[],total:0}),logPage=ref(1),logsLoading=ref(false);
const accounts=ref({items:[],total:0}),accountPage=ref(1),accountKeyword=ref(''),accountsLoading=ref(false);
const managerLogsOpen=ref(false),logAccount=ref(null),managerLogPage=ref(1),managerLogs=ref({items:[],total:0}),managerLogsLoading=ref(false);
const roles={admin:'管理员',sales:'外贸部',warehouse:'仓库部',finance:'财务部'};
const tabs=computed(()=>[{key:'mine',label:'我的 Key'},{key:'docs',label:'接口说明'},...(canManage.value?[{key:'accounts',label:'账号管理'}]:[])]);
const examples=computed(()=>apiExamples(baseUrl.value));
const root='/api/admin/api-integrations';
let alive=true;
async function load() {
  initialLoading.value=!meta.value;error.value='';
  try { const data=await request(root+'/me');if(!alive)return;meta.value=data.item;canManage.value=data.canManage && auth.can('admin-users');baseUrl.value=data.baseUrl;await loadLogs(); }
  catch(e){if(alive)error.value=e.message;} finally{if(alive)initialLoading.value=false;}
}
async function loadLogs(){logsLoading.value=true;try{const data=await request(root+'/logs?page='+logPage.value);if(alive)logs.value=data;}catch(e){if(alive)error.value=e.message;}finally{if(alive)logsLoading.value=false;}}
async function changeTab(value){tab.value=value;if(value==='accounts')await loadAccounts();}
async function searchAccounts(){accountPage.value=1;await loadAccounts();}
async function loadAccounts(){accountsLoading.value=true;try{const data=await request(root+'/accounts?'+new URLSearchParams({keyword:accountKeyword.value,page:accountPage.value}));if(alive)accounts.value=data;}catch(e){if(alive)error.value=e.message;}finally{if(alive)accountsLoading.value=false;}}
function openGenerate(reset){resetting.value=reset;expiresInput.value='';generateOpen.value=true;}
async function generate(){
  if(busy.value)return;
  let expiresAt;try{expiresAt=expiryISO(expiresInput.value);}catch(e){ElMessage.error(e.message);return;}
  busy.value=true;error.value='';
  try{
    const result=await request(root+'/me/'+(resetting.value?'reset':'generate'),{method:'POST',body:JSON.stringify({version:meta.value.version,expiresAt})});
    if(!alive)return;meta.value=result.item;generateOpen.value=false;secret.value=result.key;secretOpen.value=true;
  }catch(e){
    if(!alive)return;
    generateOpen.value=false;
    await load(); // Never automatically retry a potentially committed create.
    error.value=e.message+'。已尝试刷新状态；若已生成但未取得完整 Key，请手动重置。';
  }finally{if(alive)busy.value=false;}
}
async function toggleOwn(){
  if(busy.value)return;
  const enabled=meta.value.status==='owner_disabled';
  try{await ElMessageBox.confirm(enabled?'恢复后，对接系统可继续读取商品素材和可售库存。':'停用后，对接系统的新请求将立即失效。',enabled?'启用 Key':'停用 Key',{type:'warning'});}catch{return;}
  busy.value=true;try{const result=await request(root+'/me/status',{method:'PUT',body:JSON.stringify({version:meta.value.version,enabled})});if(alive)meta.value=result.item;}catch(e){await load();if(alive)error.value=e.message;}finally{if(alive)busy.value=false;}
}
async function manage(row,action){
  if(busy.value)return;
  const message=action==='revoke'?'现有 Key 将立即失效，之后须由账号本人重新生成。':row.adminBlocked?'恢复该账号的 API 授权？':'禁用后，本人不能通过生成、重置或启用绕过，直到管理人员恢复授权。';
  try{await ElMessageBox.confirm(message,row.name+' · API 授权',{type:'warning'});}catch{return;}
  busy.value=true;try{
    await request(root+'/accounts/'+row.id+'/'+action,{method:action==='revoke'?'POST':'PUT',body:JSON.stringify({version:row.version,...(action==='authorization'?{blocked:!row.adminBlocked}:{})})});
    if(alive){await loadAccounts();await load();ElMessage.success('已更新');}
  }catch(e){await loadAccounts();if(alive)error.value=e.message;}finally{if(alive)busy.value=false;}
}
async function showAccountLogs(row){logAccount.value=row;managerLogPage.value=1;managerLogs.value={items:[],total:0};managerLogsOpen.value=true;await loadManagerLogs();}
async function loadManagerLogs(){managerLogsLoading.value=true;try{const data=await request(root+'/logs?userId='+logAccount.value.id+'&page='+managerLogPage.value);if(alive)managerLogs.value=data;}catch(e){if(alive)error.value=e.message;}finally{if(alive)managerLogsLoading.value=false;}}
async function copySecret(){try{await navigator.clipboard.writeText(secret.value);ElMessage.success('已复制');}catch{ElMessage.info('请选中密钥后手动复制');}}
function clearSecret(){secret.value='';}
function identityCleared(){alive=false;secretOpen.value=false;clearSecret();meta.value=null;accounts.value={items:[],total:0};logs.value={items:[],total:0};}
onMounted(()=>{window.addEventListener('auth-identity-cleared',identityCleared);load();});
onBeforeUnmount(()=>{alive=false;clearSecret();window.removeEventListener('auth-identity-cleared',identityCleared);});
</script>

<style scoped>
.api-integration{background:#fff;border:1px solid #e3e9f2;border-radius:10px;padding:22px;font-size:12px;min-width:0;color:#475569}
.api-tabs{display:flex;align-items:center;gap:24px;border-bottom:1px solid #edf1f6;margin-bottom:22px;flex-wrap:wrap}
.api-tabs button{border:0;background:none;color:#64748b;padding:0 0 15px;font-size:12px;cursor:pointer;border-bottom:2px solid transparent}
.api-tabs button.active{color:#2563eb;border-color:#2563eb}.scope-label{margin-left:auto;color:#94a3b8;padding-bottom:15px}
h3{font-size:13px;color:#1e293b;margin:0}.key-heading,.section-heading{display:flex;align-items:center;gap:12px}.key-heading{margin-bottom:24px}.section-heading{margin:28px 0 12px;justify-content:space-between}.section-heading span,small{color:#94a3b8;font-size:11px}
.key-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(195px,1fr));gap:24px}.key-facts div{display:flex;flex-direction:column;gap:10px}.key-facts span{color:#94a3b8;font-size:11px}.key-facts strong{font-weight:500;color:#334155}.monospace{font-family:monospace;font-size:13px}
.key-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:24px;padding-top:20px;border-top:1px solid #f1f5f9}.key-actions span{color:#94a3b8;font-size:11px}.notice{margin-bottom:20px}
.pagination{justify-content:flex-end;margin-top:16px}.account-search{display:flex;gap:10px;max-width:440px;margin-bottom:16px}.account-search .el-input{flex:1}.api-docs{line-height:1.9}.api-docs h3{margin:22px 0 10px}.api-docs li{margin:8px 0}.api-docs ul{padding-left:18px}.api-docs code{color:#2563eb;overflow-wrap:anywhere}.api-docs pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;background:#f8fafc;border-radius:6px;padding:16px;font-size:12px}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:650px}td,th{text-align:left;padding:12px;border-bottom:1px solid #edf1f6;font-weight:400}th{color:#94a3b8}.api-integration :deep(.el-table){font-size:12px}.api-integration :deep(.el-table th){background:#fff;font-size:11px}.api-integration :deep(.el-input__wrapper){min-height:32px;box-sizing:border-box}.api-integration :deep(.el-button){height:32px;font-size:12px}
@media(max-width:700px){.api-integration{padding:14px}.scope-label{width:100%;margin:0;padding-bottom:10px}.api-tabs{gap:18px}.key-facts{grid-template-columns:1fr}.section-heading{align-items:flex-start;gap:8px;flex-wrap:wrap}.key-actions{align-items:flex-start}.key-actions span{width:100%}.api-docs pre{padding:10px}}
</style>
