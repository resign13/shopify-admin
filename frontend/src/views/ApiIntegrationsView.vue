<template>
  <section class="api-integration" v-loading="initialLoading">
    <div v-if="isPhone" class="mobile-api" data-testid="mobile-api">
      <header class="mapi-heading"><div><h1>API 对接</h1><p>让商品与库存，轻松连接</p></div><MobileActionMenu label="更多"><ElButton :disabled="busy" @click="load">刷新状态</ElButton><ElButton v-if="meta?.keyId" :disabled="busy||meta.adminBlocked" @click="openGenerate(true)">重置 Key</ElButton></MobileActionMenu></header>
      <nav class="mapi-tabs" role="tablist" aria-label="API 对接"><button v-for="item in tabs" :key="item.key" role="tab" :aria-selected="tab===item.key" :class="{active:tab===item.key}" @click="changeTab(item.key)">{{ item.label }}</button></nav>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notice"/><el-button v-if="!meta&&!initialLoading" @click="load">重新加载</el-button>
      <template v-if="meta&&tab==='mine'"><section class="mapi-key"><div class="mapi-key-top"><span><el-icon><Key /></el-icon></span><el-tag :type="meta.status==='enabled'?'success':meta.adminBlocked||meta.status==='expired'?'warning':'info'" size="small">{{ apiStates[meta.status] }}</el-tag></div><p class="mapi-eyebrow">我的 API KEY</p><h2>{{ meta.keyLabel||'等待你的第一个连接' }}</h2><p class="mapi-key-description">{{ meta.keyId?'独立凭证，让业务数据有序流动。':'生成专属 Key，在你的系统中读取商品素材与可售库存。' }}</p><div class="mapi-tags"><span>商品素材 · 只读</span><span>可售库存 · 只读</span></div><div class="mapi-key-facts"><div><span>有效期 · 北京时间</span><strong>{{ meta.expiresAt?beijingTime(meta.expiresAt):'长期有效' }}</strong></div><div><span>近 24 小时调用</span><strong>{{ meta.calls24h }} <small>次</small></strong></div></div><el-button v-if="!meta.keyId" class="mapi-key-primary" type="primary" :disabled="busy||meta.adminBlocked" @click="openGenerate(false)">生成 API Key <el-icon><Plus /></el-icon></el-button><el-button v-else class="mapi-key-primary secondary" :disabled="busy||meta.adminBlocked||meta.status==='expired'" @click="toggleOwn">{{ meta.status==='owner_disabled'?'启用 Key':'停用 Key' }}</el-button><p class="mapi-key-note">{{ meta.adminBlocked?'请由账号管理人员恢复 API 授权':'完整 Key 只在生成或重置后展示一次' }}</p></section><h3 class="mapi-section">连接记录</h3><section class="mapi-group"><button @click="mobileCallsOpen=true"><el-icon><Clock /></el-icon><span><strong>最近调用</strong><small>{{ meta.lastUsedAt?'最近一次 · '+beijingTime(meta.lastUsedAt):'尚无调用，连接后将在这里显示' }}</small></span><b>{{ logs.total }}</b><el-icon><ArrowRight /></el-icon></button><button @click="changeTab('docs')"><el-icon><Document /></el-icon><span><strong>查看接口说明</strong><small>认证方式、请求参数与同步示例</small></span><el-icon><ArrowRight /></el-icon></button></section></template>
      <template v-if="meta&&tab==='docs'"><div class="mapi-doc-heading"><el-icon><Document /></el-icon><div><strong>只读开放接口</strong><p>HTTPS · GET · Bearer Key</p></div></div><section class="mapi-group"><button @click="openMobileDocs('auth')"><el-icon><Key /></el-icon><span><strong>连接与认证</strong><small>地址、请求头与权限范围</small></span><el-icon><ArrowRight /></el-icon></button><button v-for="endpoint in apiReadEndpoints" :key="endpoint.id" @click="openMobileDocs(endpoint.id)"><el-icon><component :is="endpoint.id==='inventory'?Box:Document"/></el-icon><span><strong>{{ {products:'商品列表',product:'商品详情',inventory:'批量库存'}[endpoint.id] }}</strong><small>GET {{ endpoint.path }}</small></span><el-icon><ArrowRight /></el-icon></button></section><h3 class="mapi-section">同步指南</h3><section class="mapi-group"><button @click="openMobileDocs('sync')"><el-icon><Collection /></el-icon><span><strong>字段与同步口径</strong><small>真实尺码、图片、库存与限流规则</small></span><el-icon><ArrowRight /></el-icon></button><button @click="openMobileDocs('python')"><el-icon><Document /></el-icon><span><strong>Python 完整同步</strong><small>游标分页、分批库存与限流重试</small></span><el-icon><ArrowRight /></el-icon></button></section></template>
      <template v-if="meta&&tab==='accounts'&&canManage"><form class="mapi-account-search mobile-query-bar" @submit.prevent="searchAccounts"><el-input v-model="accountKeyword" clearable maxlength="200" placeholder="搜索姓名或后台账号"><template #prefix><el-icon><Search /></el-icon></template></el-input><el-button native-type="submit" :disabled="busy" :loading="accountsLoading">查询</el-button></form><h3 class="mapi-section">{{ accounts.total }} 位后台成员</h3><div class="mapi-account-list" v-loading="accountsLoading"><button v-for="row in accounts.items" :key="row.id" class="mapi-account" @click="mobileAccount=row;mobileAccountOpen=true"><span class="mapi-avatar">{{ row.name?.slice(0,1) }}</span><span class="mapi-account-copy"><span><strong>{{ row.name }}</strong><el-tag size="small" :type="row.status==='enabled'?'success':row.adminBlocked?'warning':'info'">{{ apiStates[row.status] }}</el-tag></span><small>{{ roles[row.role] }} · {{ row.email }}</small><em>{{ !row.moduleAllowed?'账号停用 / 未授予模块':row.adminBlocked?'管理员禁用授权':row.keyLabel||'尚未生成 Key' }}</em></span><el-icon><ArrowRight /></el-icon></button><el-empty v-if="!accountsLoading&&!accounts.items.length" description="没有找到匹配账号" :image-size="64"/></div><el-pagination class="mapi-pagination" layout="prev, pager, next" :pager-count="5" :total="accounts.total" :page-size="20" :current-page="accountPage" @current-change="value=>{accountPage=value;loadAccounts()}"/></template>
      <el-drawer v-model="mobileCallsOpen" title="最近调用" size="85%" direction="btt"><CallRecords :items="logs.items" :total="logs.total" :page="logPage" :loading="logsLoading" @page="value=>{logPage=value;loadLogs()}"/><p class="mapi-sheet-note">仅保留最近 30 天 · 北京时间</p></el-drawer>
      <el-drawer v-model="mobileAccountOpen" :title="(mobileAccount?.name||'')+' · API 授权'" size="75%" direction="btt"><template v-if="mobileAccount"><div class="mapi-account-detail"><p><span>后台账号</span><b>{{ mobileAccount.email }}</b></p><p><span>部门</span><b>{{ roles[mobileAccount.role] }}</b></p><p><span>API 授权</span><b>{{ !mobileAccount.moduleAllowed?'账号停用 / 未授予模块':mobileAccount.adminBlocked?'管理员禁用':'允许' }}</b></p><p><span>Key 标识</span><b>{{ mobileAccount.keyLabel||'未生成' }}</b></p><p><span>状态</span><b>{{ apiStates[mobileAccount.status] }}</b></p><p><span>有效期</span><b>{{ mobileAccount.expiresAt?beijingTime(mobileAccount.expiresAt):'长期有效' }}</b></p><p><span>最近调用</span><b>{{ beijingTime(mobileAccount.lastUsedAt) }}</b></p></div><p class="mapi-sheet-note">管理授权和作废凭证，不展示他人的完整 Key。</p></template><template #footer><template v-if="mobileAccount"><el-button :disabled="busy" @click="manageMobileAccount('authorization')">{{ mobileAccount.adminBlocked?'恢复授权':'禁用授权' }}</el-button><el-button :disabled="busy||!mobileAccount.keyId" type="danger" plain @click="manageMobileAccount('revoke')">作废 Key</el-button><el-button @click="showAccountLogs(mobileAccount)">调用记录</el-button></template></template></el-drawer>
      <el-drawer v-model="mobileDocsOpen" :title="mobileDocsTitle" size="94%" direction="btt"><div class="mapi-doc-detail"><template v-if="mobileDocSection==='auth'"><h3>连接地址</h3><code>{{ baseUrl }}</code><p>完整地址＝连接地址＋接口路径。HTTPS、GET 请求，无请求体，无需设置 Content-Type；查询参数放在 URL 查询串。</p><pre>Authorization: Bearer TOKEN</pre><p>使用本人启用中的完整 Key。无需商城账号密码、登录 Cookie 或 CSRF Token；Key 仅在请求头提交，不具有订单、售价或后台操作权限。</p><article v-for="param in apiCommonHeaders" :key="param.name"><h4>{{ param.name }} <small>{{ param.required?'必填':'可选' }}</small></h4><p>{{ param.description }}</p><code>{{ param.example }}</code></article></template><template v-else-if="mobileEndpoint"><h3>GET {{ mobileEndpoint.path }}</h3><p>{{ mobileEndpoint.introduction }}</p><article v-for="param in mobileEndpoint.parameters" :key="param.name"><h4>{{ param.name }} <small>{{ param.required?'必填':'可选' }}</small></h4><p>{{ param.location }} · {{ param.type }} · 默认 {{ param.defaultValue }}</p><p>{{ param.description }}</p><code>{{ param.example }}</code></article><h4>请求示例</h4><pre>{{ examples[mobileEndpoint.exampleKey] }}</pre><details v-if="mobileEndpoint.id==='products'"><summary>带可选筛选参数</summary><pre>{{ examples.curlFiltered }}</pre></details><p>返回：{{ mobileEndpoint.returns }}</p><p>示例适用 Bash / Git Bash；含中文或特殊字符时使用客户端编码或 curl --data-urlencode。</p></template><template v-else-if="mobileDocSection==='sync'"><h3>字段与同步口径</h3><p>每条为一个颜色 SKU：productId、styleCode、sku、color、category（id/key/name）、title、summary、description、images、sizes。</p><p>images：main、gallery（有序数组）、sizeChart、detail，为原图 HTTPS 地址；缺失为 null。描述是原始文本，显示 HTML 时自行净化。</p><p>sizes 按真实配置顺序返回 { size, stock }；stock 是可售数量，内部负库存按 0 返回，不补造尺码。</p><p>库存接口只返回 productId、styleCode、sku、sizes；notFoundIds 表示不存在或下架，与库存为 0 不同。</p><p>同一响应为只读快照，readAt 为 UTC ISO 时间；跨页不是全库一致快照。完整拉取成功后再对账删除，失败保留已有目录。</p><p>款号及 SKU 筛选最多 100 项，关键词最多 200 字符；游标按商品 ID 递增，不是库存更新时间。</p><p>每 Key 60 次/分钟，同 IP 300 次/分钟，全局每秒 10 次；同时处理全局最多 4、单 Key 最多 2。429 按 Retry-After 等待；400 检查参数，401 检查 Key，404 下架/缺失，503 未启用或服务忙。</p><p>撤销 Key 不会撤回已下载素材。Key 只放服务端配置，不放 URL、客户网页或日志。</p></template><template v-else-if="mobileDocSection==='python'"><h3>完整分页与分批读取库存</h3><pre>{{ examples.python }}</pre></template></div></el-drawer>
    </div>
    <template v-else>
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
      <p>完整地址＝上方连接地址＋下方接口路径。使用 HTTPS、GET 请求，请求体留空，无需设置 Content-Type；查询参数放在 URL 查询串中。</p>
      <div class="docs-auth"><span class="parameter-required">所有接口必填</span><code>Authorization: Bearer TOKEN</code></div>
      <p>TOKEN 替换为“我的 Key”中生成的完整密钥。无需商城账号 ID、账号密码、登录 Cookie 或 CSRF Token；Key 仅在请求头提交，不具有订单、售价或后台操作权限。</p>
      <div class="table-scroll" role="region" aria-label="公共请求头" tabindex="0"><table class="parameters-table"><thead><tr><th>参数</th><th>位置</th><th>是否必填</th><th>类型</th><th>默认值</th><th>说明／示例</th></tr></thead><tbody>
        <tr v-for="param in apiCommonHeaders" :key="param.name"><td><code>{{ param.name }}</code></td><td>{{ param.location }}</td><td :class="param.required ? 'parameter-required' : 'parameter-optional'">{{ param.required ? '必填' : '可选' }}</td><td>{{ param.type }}</td><td>{{ param.defaultValue }}</td><td>{{ param.description }}<code class="parameter-example">{{ param.example }}</code></td></tr>
      </tbody></table></div>
      <h3>接口一览</h3>
      <div class="table-scroll" role="region" aria-label="接口一览" tabindex="0"><table><thead><tr><th>GET 接口</th><th>必填参数</th><th>可选参数</th><th>返回</th></tr></thead><tbody>
        <tr v-for="endpoint in apiReadEndpoints" :key="endpoint.id"><td><a :href="'#api-docs-' + endpoint.id"><code>{{ endpoint.path }}</code></a></td><td>{{ endpoint.requiredLabel }}</td><td>{{ endpoint.optionalLabel }}</td><td>{{ endpoint.returns }}</td></tr>
      </tbody></table></div>
      <section v-for="endpoint in apiReadEndpoints" :key="endpoint.id" class="endpoint-docs" :aria-labelledby="'api-docs-' + endpoint.id">
        <h3 :id="'api-docs-' + endpoint.id"><code>GET {{ endpoint.path }}</code></h3>
        <p>{{ endpoint.introduction }}</p>
        <div class="table-scroll" role="region" :aria-label="endpoint.path + ' 请求参数'" tabindex="0"><table class="parameters-table"><thead><tr><th>参数</th><th>位置</th><th>是否必填</th><th>类型</th><th>默认值</th><th>说明／示例</th></tr></thead><tbody>
          <tr v-for="param in endpoint.parameters" :key="param.name"><td><code>{{ param.name }}</code></td><td>{{ param.location }}</td><td :class="param.required ? 'parameter-required' : 'parameter-optional'">{{ param.required ? '必填' : '可选' }}</td><td>{{ param.type }}</td><td>{{ param.defaultValue }}</td><td>{{ param.description }}<code class="parameter-example">{{ param.example }}</code></td></tr>
        </tbody></table></div>
        <h4>{{ endpoint.id === 'products' ? '最简请求：不传查询参数' : '请求示例（替换为实际商品 ID）' }}</h4><pre>{{ examples[endpoint.exampleKey] }}</pre>
        <details v-if="endpoint.id === 'products'"><summary>带可选筛选参数的请求示例</summary><pre>{{ examples.curlFiltered }}</pre></details>
      </section>
      <p class="docs-note">curl 示例适用于 Bash／Git Bash。实际款号、SKU 和 ID 以商品列表返回值为准；含中文或特殊字符时交由 HTTP 客户端编码，curl 使用 --get 和 --data-urlencode，Python 使用 params。</p>
      <h3>字段与同步口径</h3>
      <ul>
        <li>每条为一个颜色 SKU：productId、styleCode、sku、color、category（id/key/name）、title、summary、description、images、sizes。</li>
        <li>images：main、gallery（有序数组）、sizeChart、detail，均为原图 HTTPS 地址；缺失为 null。描述是原始文本，对接方显示 HTML 时自行净化。</li>
        <li>sizes：按本商品真实配置顺序的 { size, stock }；商品 ID＋真实尺码关联。stock 是可售数量，内部负库存按 0 返回，不补造尺码。</li>
        <li>库存接口仅返回 productId、styleCode、sku、sizes；notFoundIds 表示商品不存在或已下架，与库存为 0 不同。</li>
        <li>每次响应使用同一只读快照；readAt 为 UTC ISO 时间。跨页不是全库一致快照。只有完整拉取成功后再对账删除，失败时保留已有目录。</li>
        <li>款号和 SKU 筛选均可传逗号分隔列表，最多 100 项；关键词最多 200 字符。游标按商品 ID 递增，不是库存更新时间。</li>
        <li>每把 Key 默认 60 次／分钟，同一 IP 300 次／分钟；全部 Key 共用每秒 10 次额度。全局最多同时处理 4 个请求，单 Key 最多 2 个。429 按 Retry-After 等待并错峰重试；400 检查参数，401 检查 Key 状态及授权，404 表示商品下架或缺失，503 表示尚未启用或服务暂忙。</li>
        <li>图片保持原公开访问规则，撤销 Key 不会撤回已下载的素材。Key 只放在服务端配置，不放入 URL、客户网页或日志。</li>
      </ul>
      <h3>Python：完整分页与分批读取库存</h3><pre>{{ examples.python }}</pre>
    </div>

    <template v-if="meta && tab === 'accounts' && canManage">
      <div class="account-search"><el-input v-model="accountKeyword" placeholder="搜索后台账号或姓名" clearable maxlength="200" @keyup.enter="searchAccounts" /><el-button :disabled="busy" @click="searchAccounts">查询</el-button></div>
      <AdaptiveTable :data="accounts.items" v-loading="accountsLoading" empty-text="暂无账号" class="accounts-table">
        <el-table-column label="后台账号" min-width="170"><template #default="{row}"><div>{{ row.name }}</div><small>{{ row.email }}</small></template></el-table-column>
        <el-table-column label="部门" width="90"><template #default="{row}">{{ roles[row.role] }}</template></el-table-column>
        <el-table-column label="API 授权" min-width="140"><template #default="{row}">{{ !row.moduleAllowed ? '账号停用／未授予模块' : row.adminBlocked ? '管理员禁用' : '允许' }}</template></el-table-column>
        <el-table-column prop="keyLabel" label="Key 标识" min-width="150" />
        <el-table-column label="状态" width="110"><template #default="{row}">{{ apiStates[row.status] }}</template></el-table-column>
        <el-table-column label="到期时间" min-width="165"><template #default="{row}">{{ row.expiresAt ? beijingTime(row.expiresAt) : '长期有效' }}</template></el-table-column>
        <el-table-column label="最近调用" min-width="165"><template #default="{row}">{{ beijingTime(row.lastUsedAt) }}</template></el-table-column>
        <el-table-column label="操作" width="210" fixed="right"><template #default="{row}"><el-button text size="small" :disabled="busy" @click="manage(row, 'authorization')">{{ row.adminBlocked ? '恢复授权' : '禁用授权' }}</el-button><el-button text size="small" :disabled="busy || !row.keyId" @click="manage(row,'revoke')">作废 Key</el-button><el-button text size="small" @click="showAccountLogs(row)">调用</el-button></template></el-table-column>
      </AdaptiveTable>
      <el-pagination class="pagination" layout="prev, pager, next, total" :total="accounts.total" :page-size="20" :current-page="accountPage" @current-change="value => { accountPage=value; loadAccounts(); }" />
    </template>

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
import { errorMessage } from '../utils/adminErrors.js';
import {useResponsive} from "../composables/responsive";
import MobileActionMenu from "../components/MobileActionMenu.vue";
import {Key,Plus,Clock,Document,ArrowRight,Box,Collection,Search} from "@element-plus/icons-vue";
const {isPhone}=useResponsive();
import AdaptiveTable from "../components/AdaptiveTable";
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, toRef, watch } from 'vue';
import { ElMessage, ElMessageBox, ElTableColumn, ElPagination } from 'element-plus';
import 'element-plus/es/components/table/style/css';
import 'element-plus/es/components/pagination/style/css';
import 'element-plus/es/components/message/style/css';
import 'element-plus/es/components/message-box/style/css';
import { request } from '../api';
import { createApiReadTask, createApiAccountQuery } from '../utils/apiIntegrationReads';
import { useAdminAuthStore } from '../stores/auth';
import { apiStates, beijingTime, expiryISO, apiExamples, apiCommonHeaders, apiReadEndpoints } from '../utils/apiIntegration';

// One shared table for own and explicitly authorized account logs. No request
// parameters/headers or raw tokens are stored in these objects.
const CallRecords = defineComponent({ props: ['items','total','page','loading'], emits: ['page'], setup(props,{emit}) {
  return () => isPhone.value ? h('div',{class:'mobile-api-call-records','aria-busy':props.loading},[...(props.items?.length?props.items.map(row=>h('article',[h('div',[h('strong',row.route),h('b',{class:row.status>=400?'is-error':''},String(row.status))]),h('p',beijingTime(row.time)+' · '+row.durationMs+' ms')])):[h('p',{class:'mobile-api-call-empty'},props.loading?'加载调用记录…':'尚无调用记录')]),h(ElPagination,{class:'mapi-pagination',layout:'prev, pager, next',pagerCount:5,total:props.total,pageSize:20,currentPage:props.page,'onUpdate:currentPage':value=>emit('page',value)})]) : h('div', [h(AdaptiveTable, { data:props.items, emptyText:props.loading?'加载中…':'暂无调用记录', 'aria-busy':props.loading }, () => [
    h(ElTableColumn, {label:'时间',minWidth:170}, {default:({row})=>beijingTime(row.time)}),
    h(ElTableColumn, {label:'接口',prop:'route',minWidth:260}),
    h(ElTableColumn, {label:'结果',prop:'status',width:80}),
    h(ElTableColumn, {label:'耗时',width:100}, {default:({row})=>row.durationMs+' ms'}),
  ]), h(ElPagination,{class:'pagination',layout:'prev, pager, next, total',total:props.total,pageSize:20,currentPage:props.page,'onUpdate:currentPage':value=>emit('page',value)})]);
}});
const mobileCallsOpen=ref(false),mobileAccountOpen=ref(false),mobileAccount=ref(null),mobileDocsOpen=ref(false),mobileDocSection=ref('auth');
const mobileEndpoint=computed(()=>apiReadEndpoints.find(endpoint=>endpoint.id===mobileDocSection.value));
const mobileDocsTitle=computed(()=>({auth:'连接与认证',products:'商品列表',product:'商品详情',inventory:'批量库存',sync:'字段与同步口径',python:'Python 完整同步'})[mobileDocSection.value]||'接口说明');
function openMobileDocs(section){mobileDocSection.value=section;mobileDocsOpen.value=true;}
async function manageMobileAccount(action){const id=mobileAccount.value.id;await manage(mobileAccount.value,action);mobileAccount.value=accounts.value.items.find(row=>row.id===id)||mobileAccount.value;}
const auth=useAdminAuthStore(), tab=ref('mine'), meta=ref(null), canManage=ref(false), error=ref('');
const initialLoading=ref(false),busy=ref(false),baseUrl=ref(''),secret=ref(''),secretOpen=ref(false),generateOpen=ref(false),resetting=ref(false),expiresInput=ref('');
const logs=ref({items:[],total:0}),logPage=ref(1),logsLoading=ref(false);
const accountQuery=reactive(createApiAccountQuery());
const accounts=ref({items:[],total:0}),accountPage=toRef(accountQuery,'page'),accountKeyword=toRef(accountQuery,'keyword'),accountsLoading=ref(false);
const managerLogsOpen=ref(false),logAccount=ref(null),managerLogPage=ref(1),managerLogs=ref({items:[],total:0}),managerLogsLoading=ref(false);
const roles={admin:'管理员',sales:'外贸部',warehouse:'仓库部',finance:'财务部'};
const tabs=computed(()=>[{key:'mine',label:'我的 Key'},{key:'docs',label:'接口说明'},...(canManage.value?[{key:'accounts',label:'账号管理'}]:[])]);
const examples=computed(()=>apiExamples(baseUrl.value));
const root='/api/admin/api-integrations';
let alive=true;
function readTask(target, pending) {
  return createApiReadTask(request, {
    active: () => alive,
    loading: value => { pending.value=value;if(value)error.value=''; },
    receive: data => { target.value=data; },
    fail: failure => { error.value=errorMessage(failure); },
  });
}
const accountsRead=readTask(accounts,accountsLoading),ownLogsRead=readTask(logs,logsLoading),managerLogsRead=readTask(managerLogs,managerLogsLoading);
function cancelReads(){accountsRead.cancel();ownLogsRead.cancel();managerLogsRead.cancel();}
watch(mobileCallsOpen, open=>{if(open)loadLogs();else ownLogsRead.cancel();},{flush:'sync'});
watch(managerLogsOpen, open=>{if(!open)managerLogsRead.cancel();},{flush:'sync'});
async function load() {
  initialLoading.value=!meta.value;error.value='';
  try { const data=await request(root+'/me');if(!alive)return;meta.value=data.item;canManage.value=data.canManage && auth.can('admin-users');baseUrl.value=data.baseUrl;await loadLogs(); }
  catch(e){if(alive)error.value=errorMessage(e);} finally{if(alive)initialLoading.value=false;}
}
async function loadLogs(){if(tab.value!=='mine')return;await ownLogsRead.run(root+'/logs?page='+logPage.value);}
async function changeTab(value){if(value!==tab.value){cancelReads();managerLogsOpen.value=false;mobileCallsOpen.value=false;mobileAccountOpen.value=false;error.value='';tab.value=value;}if(value==='accounts')await loadAccounts();else if(value==='mine')await loadLogs();}
async function searchAccounts(){accountQuery.submit();await loadAccounts();}
async function loadAccounts(){if(tab.value!=='accounts')return;await accountsRead.run(root+'/accounts?'+accountQuery.params());}
function openGenerate(reset){resetting.value=reset;expiresInput.value='';generateOpen.value=true;}
async function generate(){
  if(busy.value)return;
  let expiresAt;try{expiresAt=expiryISO(expiresInput.value);}catch(e){ElMessage.error(errorMessage(e));return;}
  busy.value=true;error.value='';
  try{
    const result=await request(root+'/me/'+(resetting.value?'reset':'generate'),{method:'POST',body:JSON.stringify({version:meta.value.version,expiresAt})});
    if(!alive)return;meta.value=result.item;generateOpen.value=false;secret.value=result.key;secretOpen.value=true;
  }catch(e){
    if(!alive)return;
    generateOpen.value=false;
    await load(); // Never automatically retry a potentially committed create.
    error.value=errorMessage(e)+'。已尝试刷新状态；若已生成但未取得完整 Key，请手动重置。';
  }finally{if(alive)busy.value=false;}
}
async function toggleOwn(){
  if(busy.value)return;
  const enabled=meta.value.status==='owner_disabled';
  try{await ElMessageBox.confirm(enabled?'恢复后，对接系统可继续读取商品素材和可售库存。':'停用后，对接系统的新请求将立即失效。',enabled?'启用 Key':'停用 Key',{type:'warning'});}catch{return;}
  busy.value=true;try{const result=await request(root+'/me/status',{method:'PUT',body:JSON.stringify({version:meta.value.version,enabled})});if(alive)meta.value=result.item;}catch(e){await load();if(alive)error.value=errorMessage(e);}finally{if(alive)busy.value=false;}
}
async function manage(row,action){
  if(busy.value)return;
  const message=action==='revoke'?'现有 Key 将立即失效，之后须由账号本人重新生成。':row.adminBlocked?'恢复该账号的 API 授权？':'禁用后，本人不能通过生成、重置或启用绕过，直到管理人员恢复授权。';
  try{await ElMessageBox.confirm(message,row.name+' · API 授权',{type:'warning'});}catch{return;}
  busy.value=true;try{
    await request(root+'/accounts/'+row.id+'/'+action,{method:action==='revoke'?'POST':'PUT',body:JSON.stringify({version:row.version,...(action==='authorization'?{blocked:!row.adminBlocked}:{})})});
    if(alive){await loadAccounts();await load();ElMessage.success('已更新');}
  }catch(e){await loadAccounts();if(alive)error.value=errorMessage(e);}finally{if(alive)busy.value=false;}
}
async function showAccountLogs(row){logAccount.value=row;managerLogPage.value=1;managerLogs.value={items:[],total:0};managerLogsOpen.value=true;await loadManagerLogs();}
async function loadManagerLogs(){if(tab.value!=='accounts'||!managerLogsOpen.value||!logAccount.value)return;await managerLogsRead.run(root+'/logs?'+new URLSearchParams({userId:logAccount.value.id,page:managerLogPage.value}));}
async function copySecret(){try{await navigator.clipboard.writeText(secret.value);ElMessage.success('已复制');}catch{ElMessage.info('请选中密钥后手动复制');}}
function clearSecret(){secret.value='';}
function identityCleared(){alive=false;cancelReads();secretOpen.value=false;managerLogsOpen.value=false;mobileCallsOpen.value=false;clearSecret();meta.value=null;accounts.value={items:[],total:0};logs.value={items:[],total:0};managerLogs.value={items:[],total:0};logAccount.value=null;}
onMounted(()=>{window.addEventListener('auth-identity-cleared',identityCleared);load();});
onBeforeUnmount(()=>{alive=false;cancelReads();clearSecret();window.removeEventListener('auth-identity-cleared',identityCleared);});
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
.docs-auth{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 12px;background:#f8fafc;border-radius:6px}.parameter-required{color:#b45309;font-weight:500}.parameter-optional{color:#64748b}.parameter-example{display:block;margin-top:4px}.parameters-table{min-width:820px}.parameters-table td{vertical-align:top}.parameters-table td:first-child{width:130px}.parameters-table td:nth-child(2),.parameters-table td:nth-child(3){white-space:nowrap}.parameters-table td:last-child{min-width:260px}.api-docs h4{font-size:12px;font-weight:500;margin:16px 0 8px}.api-docs summary{cursor:pointer;color:#2563eb}.api-docs .docs-note{color:#64748b;font-size:11px}.endpoint-docs{scroll-margin-top:20px}.table-scroll:focus-visible{outline:2px solid #93c5fd;outline-offset:2px}
@media(max-width:700px){.api-integration{padding:14px}.scope-label{width:100%;margin:0;padding-bottom:10px}.api-tabs{gap:18px}.key-facts{grid-template-columns:1fr}.section-heading{align-items:flex-start;gap:8px;flex-wrap:wrap}.key-actions{align-items:flex-start}.key-actions span{width:100%}.api-docs pre{padding:10px}}
</style>

<style scoped>
@media(max-width:767px){.api-integration{padding:0;background:transparent;border:0;border-radius:0;box-shadow:none}.mobile-api{color:#182b49}.mapi-heading{display:flex;justify-content:space-between;align-items:center;gap:14px;margin:4px 0 20px}.mapi-heading h1{font-size:25px;letter-spacing:-.04em;margin:0}.mapi-heading p{font-size:11px;color:#8c9ab0;margin:7px 0 0}.mapi-tabs{display:flex;gap:24px;border-bottom:1px solid #e7ecf5;margin-bottom:18px}.mapi-tabs button{font-size:13px;color:#9aa7bc;background:none;border:0;border-bottom:2px solid transparent;padding:7px 0 13px;min-height:43px}.mapi-tabs button.active{color:#2f69eb;border-bottom-color:#2f69eb;font-weight:600}.mapi-key{padding:21px;background:#fff;border:1px solid #e6edf8;border-radius:20px}.mapi-key-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.mapi-key-top>span{display:grid;place-items:center;width:48px;height:48px;border-radius:16px;background:#edf3fe;color:#7295d3;font-size:24px}.mapi-key-top :deep(.el-tag){border:0;font-size:10px}.mapi-eyebrow{font-size:10px;letter-spacing:.1em;color:#96a5bb;margin:0 0 9px}.mapi-key h2{font-size:20px;letter-spacing:-.035em;line-height:1.5;overflow-wrap:anywhere;margin:0;color:#213b63}.mapi-key-description{font-size:11px;color:#9aa7bb;line-height:1.8;margin:9px 0 14px}.mapi-tags{display:flex;gap:6px;flex-wrap:wrap}.mapi-tags>span{background:#eef4ff;color:#7998c8;border-radius:6px;padding:4px 6px;font-size:10px}.mapi-key-facts{display:grid;grid-template-columns:minmax(0,1fr) auto;border-top:1px solid #eef2f8;margin:22px 0 20px;padding-top:18px;gap:14px}.mapi-key-facts>div{display:flex;flex-direction:column;gap:7px;min-width:0}.mapi-key-facts>div:last-child{text-align:right}.mapi-key-facts span{font-size:11px;color:#a4afc0}.mapi-key-facts strong{font-size:13px;font-weight:550;line-height:1.6;overflow-wrap:anywhere}.mapi-key-facts small{font-size:10px;color:#a4afc0;font-weight:400}.mapi-key-primary{width:100%;height:45px!important;border-radius:12px;font-size:13px!important;gap:9px;box-shadow:0 5px 11px #2f69eb12}.mapi-key-primary.secondary{background:#f2f6fe;color:#6385c2;border:1px solid #e8effd;box-shadow:none}.mapi-key-note{font-size:10px;color:#aab5c7;line-height:1.8;text-align:center;margin:13px 0 0}.mapi-section{font-size:12px;font-weight:600;color:#365175;margin:24px 0 14px}.mapi-group{border:1px solid #e9edf5;border-radius:18px;background:#fff;overflow:hidden}.mapi-group>button{display:flex;align-items:center;gap:12px;width:100%;background:none;border:0;padding:17px 15px;min-height:69px;text-align:left;color:#7d99bf;position:relative}.mapi-group>button+button:before{content:'';position:absolute;top:0;left:56px;right:15px;height:1px;background:#f0f3f8}.mapi-group>button>.el-icon:first-child{font-size:20px;flex:0 0 28px}.mapi-group>button>span{display:flex;flex-direction:column;gap:6px;flex:1;min-width:0}.mapi-group strong{font-size:13px;font-weight:550;color:#405b7e}.mapi-group small{font-size:11px;line-height:1.6;color:#a0adc0;overflow-wrap:anywhere}.mapi-group b{font-size:11px;font-weight:450}.mapi-group>button>.el-icon:last-child{font-size:12px;color:#bac7da}.mapi-doc-heading{display:flex;align-items:center;gap:13px;background:#edf3fd;border:1px solid #e7eefb;border-radius:17px;padding:17px;margin-bottom:17px;color:#6688be}.mapi-doc-heading>.el-icon{font-size:24px}.mapi-doc-heading strong{font-size:14px;font-weight:600;color:#3a587e}.mapi-doc-heading p{font-size:10px;color:#96a5bf;margin:5px 0 0}.mapi-account-search{display:flex;gap:9px;margin-bottom:15px}.mapi-account-search>.el-input{flex:1;min-width:0}.mapi-account-search :deep(.el-input__wrapper){border-radius:12px;background:#edf1f8;box-shadow:none;min-height:43px}.mapi-account-search>.el-button{min-height:43px;border-radius:12px}.mapi-account-list{display:flex;flex-direction:column;gap:11px}.mapi-account{display:flex;align-items:center;width:100%;gap:12px;border:1px solid #e8edf6;background:#fff;border-radius:18px;padding:17px 15px;text-align:left;color:inherit}.mapi-avatar{width:43px;height:43px;flex:0 0 43px;display:grid;place-items:center;font-size:17px;font-weight:600;border-radius:15px;background:#edf3ff;color:#7a99c9}.mapi-account-copy{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px}.mapi-account-copy>span{display:flex;justify-content:space-between;align-items:center;gap:8px}.mapi-account-copy strong{font-size:15px;font-weight:650;overflow-wrap:anywhere}.mapi-account-copy :deep(.el-tag){font-size:10px;border:0;flex-shrink:0}.mapi-account-copy small{font-size:11px;color:#91a4c0;overflow-wrap:anywhere}.mapi-account-copy em{font-size:10px;color:#acb9cc;font-style:normal;overflow-wrap:anywhere}.mapi-account>.el-icon{font-size:12px;color:#c0ccdd}.mapi-pagination{justify-content:center;max-width:100%;overflow:auto;margin-top:20px}.mapi-account-detail p{display:flex;justify-content:space-between;gap:14px;padding:12px 0;border-bottom:1px solid #edf2f8;font-size:12px;margin:0}.mapi-account-detail span{color:#9eb0c9;flex-shrink:0}.mapi-account-detail b{font-size:11px;font-weight:500;color:#6f8bb0;text-align:right;overflow-wrap:anywhere}.mapi-sheet-note{font-size:11px;color:#a5b3c9;line-height:1.8;margin:17px 0}.mapi-doc-detail{font-size:12px;color:#8ba0bd;line-height:1.9}.mapi-doc-detail h3{font-size:14px;color:#3b5a83;margin:0 0 15px}.mapi-doc-detail h4{font-size:12px;color:#587ba7;margin:0 0 9px}.mapi-doc-detail article{padding:14px;border:1px solid #e7eef8;background:#fff;border-radius:13px;margin:12px 0}.mapi-doc-detail h4 small{font-size:9px;color:#a2b3cb;font-weight:400;margin-left:8px}.mapi-doc-detail article p{margin:6px 0;font-size:11px}.mapi-doc-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5fc;border-radius:13px;padding:14px;font-size:11px;color:#758faf}.mapi-doc-detail code{font-size:11px;overflow-wrap:anywhere;color:#6484b0}.mapi-doc-detail summary{font-size:11px;color:#7f9dc3;padding:10px 0}.mobile-api-call-records :deep(article){padding:15px 0;border-bottom:1px solid #edf2f8}.mobile-api-call-records :deep(article>div){display:flex;justify-content:space-between;align-items:center;gap:10px}.mobile-api-call-records :deep(strong){font-size:12px;font-weight:550;color:#6684ac;overflow-wrap:anywhere}.mobile-api-call-records :deep(b){font-size:10px;color:#65a391;background:#eef7f3;border-radius:6px;padding:3px 6px;font-weight:500}.mobile-api-call-records :deep(b.is-error){color:#ba9290;background:#fff4f2}.mobile-api-call-records :deep(p){font-size:11px;color:#a4b3c8;margin:9px 0 0}.mobile-api-call-records :deep(.mobile-api-call-empty){padding:38px 8px;text-align:center}.mobile-api-call-records :deep(.el-pagination){justify-content:center;max-width:100%;overflow:auto;margin-top:20px}}
</style>
