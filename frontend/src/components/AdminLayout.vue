<template>
  <div class="workspace" :class="{ 'is-collapsed': collapsed }">
    <aside class="workspace-sidebar">
      <RouterLink to="/" class="brand"
        ><span class="brand-symbol">G</span
        ><span v-if="!collapsed"
          >GINGTTO<small>BUSINESS CONSOLE</small></span
        ></RouterLink
      >
      <nav>
        <section v-for="group in groups" :key="group.label">
          <p v-if="!collapsed">{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            :title="item.label"
            ><ElIcon><component :is="item.icon" /></ElIcon
            ><span v-if="!collapsed">{{ item.label }}</span></RouterLink
          >
        </section>
      </nav>
      <div class="sidebar-bottom">
        <span class="status-dot"></span
        ><span v-if="!collapsed">GINGTTO · 管理工作台</span>
      </div>
    </aside>
    <div class="workspace-main">
      <header class="workspace-topbar">
        <div class="topbar-left">
          <ElButton
            text
            :aria-label="collapsed ? '展开导航' : '收起导航'"
            @click="toggle"
            ><ElIcon
              ><Expand v-if="collapsed" /><Fold v-else /></ElIcon></ElButton
          ><span class="topbar-breadcrumb"
            >管理工作台 <span>/</span>
            <strong>{{ route.meta.title }}</strong></span
          >
        </div>
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
      <main class="workspace-content"><RouterView /></main>
    </div>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
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
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useAdminAuthStore } from "../stores/auth";
import { roleNames } from "../composables/workbench";
const auth = useAdminAuthStore(),
  route = useRoute(),
  router = useRouter();
const collapsed = ref(
  window.innerWidth < 1280 ||
    localStorage.getItem("gingtto-sidebar") === "collapsed",
);
const toggle = () => {
  collapsed.value = !collapsed.value;
  localStorage.setItem(
    "gingtto-sidebar",
    collapsed.value ? "collapsed" : "expanded",
  );
};
const definitions = [
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
    items: [["/orders", "订单管理", Document, "admin,sales,warehouse"]],
  },
  {
    label: "商城运营",
    items: [
      ["/home-config", "首页配置", Picture, "admin,sales"],
      ["/activity-zone/apply", "活动报名", Promotion, "admin,sales"],
      ["/activity-zone/manage", "活动管理", Collection, "admin,sales"],
    ],
  },
  {
    label: "账号与系统",
    items: [
      ["/store-accounts", "商城账号", User, "admin"],
      ["/admin-users", "后台账号", UserFilled, "admin"],
      ["/audit-logs", "操作日志", Notebook, "admin"],
    ],
  },
];
const groups = computed(() =>
  definitions
    .map((group) => ({
      ...group,
      items: group.items
        .filter((i) => i[3].split(",").includes(auth.userRole))
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
  await logout();
}
window.addEventListener("admin-session-expired", expired);
onBeforeUnmount(() =>
  window.removeEventListener("admin-session-expired", expired),
);
</script>
