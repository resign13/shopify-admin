<template>
  <div class="workspace" :class="{ 'is-collapsed': collapsed, 'mobile-menu-open': menuOpen }">
    <button v-if="isCompact && menuOpen" class="navigation-mask" aria-label="关闭导航" @click="menuOpen = false" />
    <aside class="workspace-sidebar" :inert="isCompact && !menuOpen" :aria-hidden="isCompact && !menuOpen" aria-label="模块导航" @keydown.esc="menuOpen = false">
      <RouterLink to="/" class="brand"
        ><span class="brand-symbol">G</span
        ><span v-if="!collapsed || isCompact"
          >GINGTTO<small>BUSINESS CONSOLE</small></span
        ></RouterLink
      >
      <nav>
        <section v-for="group in groups" :key="group.label">
          <p v-if="!collapsed || isCompact">{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            :title="item.label"
            @click="menuOpen = false"
            ><ElIcon><component :is="item.icon" /></ElIcon
            ><span v-if="!collapsed || isCompact">{{ item.label }}</span></RouterLink
          >
        </section>
      </nav>
      <div class="sidebar-bottom">
        <span class="status-dot"></span
        ><span v-if="!collapsed || isCompact">GINGTTO · 管理工作台</span>
      </div>
    </aside>
    <div class="workspace-main">
      <header class="workspace-topbar">
        <div class="topbar-left">
          <ElButton
            text
            :aria-label="isCompact ? (menuOpen ? '关闭导航' : '展开导航') : collapsed ? '展开导航' : '收起导航'"
            :aria-expanded="isCompact ? menuOpen : !collapsed"
            @click="toggle"
            ><ElIcon
              ><Expand v-if="collapsed" /><Fold v-else /></ElIcon></ElButton
          ><span class="mobile-brand">GINGTTO<span>工作台</span></span><span class="topbar-breadcrumb"
            ><span class="desktop-breadcrumb">管理工作台 /</span>
            <strong>{{ route.meta.title }}</strong></span
          >
        </div>
        <ElButton v-if="isCompact && auth.can('orders') && ['admin','sales','warehouse'].includes(auth.userRole)" text class="mobile-voice-trigger" aria-label="提醒" :aria-expanded="voiceOpen" @click="voiceOpen = !voiceOpen"><ElIcon><Bell /></ElIcon></ElButton>
        <div class="voice-panel" :class="{ 'is-open': voiceOpen }"><OrderVoiceReminder /></div>
        <ElDropdown @command="logout"
          ><button class="profile-button">
            <span class="avatar">{{ auth.user?.name?.slice(0, 1) }}</span
            ><span
              >{{ auth.user?.name
              }}<small>{{ roleNames[auth.userRole] }}</small></span
            ><ElIcon><ArrowDown /></ElIcon></button
          ><template #dropdown
            ><ElDropdownMenu
              ><ElDropdownItem command="logout"
                >退出登录</ElDropdownItem
              ></ElDropdownMenu
            ></template
          ></ElDropdown
        >
      </header>
      <main class="workspace-content"><RouterView :key="auth.user?.id" /></main>
    </div>
  </div>
</template>
<script setup>
import OrderVoiceReminder from "./OrderVoiceReminder.vue";
import { routeModule } from "../permissions";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useResponsive } from '../composables/responsive';
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import {
  DataAnalysis,
  Goods,
  Box,
  Collection,
  Document,
  Picture,
  Promotion,
  User,
  UserFilled,
  Notebook,
  Expand,
  Fold,
  ArrowDown,
  Bell,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useAdminAuthStore } from "../stores/auth";
import { roleNames } from "../composables/workbench";
const auth = useAdminAuthStore(),
  route = useRoute(),
  router = useRouter();
const { isCompact } = useResponsive();
const menuOpen = ref(false), voiceOpen = ref(false);
watch(() => route.path, () => { menuOpen.value = false; voiceOpen.value = false; });
watch(isCompact, () => { menuOpen.value = false; });
const collapsed = ref(
  window.innerWidth < 1280 ||
    localStorage.getItem("gingtto-sidebar") === "collapsed",
);
const collapseNarrow = () => { if (window.innerWidth < 1024) collapsed.value = true; };
window.addEventListener('resize', collapseNarrow);
onBeforeUnmount(() => window.removeEventListener('resize', collapseNarrow));
const toggle = () => {
  if (isCompact.value) { menuOpen.value = !menuOpen.value; voiceOpen.value = false; return; }
  collapsed.value = !collapsed.value;
  localStorage.setItem(
    "gingtto-sidebar",
    collapsed.value ? "collapsed" : "expanded",
  );
};
const definitions = [
  { label: "财务核算", items: [["/finance", "财务管理", DataAnalysis, "admin,finance"]] },
  {
    label: "经营概览",
    items: [["/dashboard", "经营工作台", DataAnalysis, "admin,sales"]],
  },
  {
    label: "商品与库存",
    items: [
      ["/products", "商品管理", Goods, "admin,sales"],
      ["/inventory", "库存管理", Box, "admin,sales,warehouse,customer"],
      ["/categories", "商品分类", Collection, "admin,sales"],
    ],
  },
  {
    label: "订单业务",
    items: [
      ["/orders", "订单管理", Document, "admin,sales,warehouse"],
      ["/contracts", "合同管理", Document, "admin,sales"],
    ],
  },
  {
    label: "商城运营",
    items: [
      ["/presale", "预售管理", Promotion, "admin,sales"],
    ],
  },
  {
    label: "账号与系统",
    items: [
      ["/store-accounts", "商城账号", User, "admin"],
      ["/admin-users", "后台账号", UserFilled, "admin"],
      ["/audit-logs", "操作日志", Notebook, "admin"],
      ["/api-integrations", "API 对接", Notebook, "admin,sales,warehouse,finance"],
    ],
  },
];
const groups = computed(() =>
  definitions
    .map((group) => ({
      ...group,
      items: group.items
        .filter((i) => auth.can(routeModule(i[0])))
        .map(([to, label, icon]) => ({ to, label, icon })),
    }))
    .filter((g) => g.items.length),
);
async function logout() {
  await auth.logout();
  router.push("/login");
}
async function expired() {
  ElMessage.warning("登录已过期，请重新登录");
  auth.clearLocalAuth(false);
  router.push("/login");
}
window.addEventListener("auth-session-expired", expired);
onBeforeUnmount(() =>
  window.removeEventListener("auth-session-expired", expired),
);
</script>
