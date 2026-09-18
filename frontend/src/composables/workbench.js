import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import { request, API_BASE } from "../api";
import { useAdminAuthStore } from "../stores/auth";

export const statusNames = {
  pending_payment: "待付款",
  paid: "已付款",
  shipped: "已发货",
  completed: "已完成",
  cancelled: "已取消",
};
export const roleNames = {
  admin: "管理员",
  sales: "外贸部",
  warehouse: "仓库部",
  customer: "客户",
};
export const money = (value) =>
  `$${Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const dateTime = (value) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—";
export const productName = (item) =>
  item?.name?.zh || item?.name?.en || item?.productCode || "未命名商品";
export const shortName = (item) => {
  const value = Array.from(productName(item));
  return value.length > 32 ? value.slice(0, 32).join("") + "…" : value.join("");
};
export function api(path, options = {}) {
  const auth = useAdminAuthStore();
  return request("/api/admin/" + path, {
    ...options,
    headers: { Authorization: `Bearer ${auth.token}`, ...options.headers },
  });
}
export const save = (path, payload, method = "PUT") =>
  api(path, { method, body: JSON.stringify(payload) });
export function notifyError(error) {
  if (error?.name !== "AbortError")
    ElMessage.error(error?.message || "操作失败");
}
export async function confirm(message, title = "确认操作") {
  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: "确认",
      cancelButtonText: "取消",
      type: "warning",
      closeOnClickModal: false,
    });
    return true;
  } catch {
    return false;
  }
}
export async function copy(value) {
  try {
    await navigator.clipboard.writeText(String(value));
    ElMessage.success("已复制");
  } catch {
    ElMessage.info("请选中内容手动复制");
  }
}
export async function download(path, filename) {
  const response = await fetch(`${API_BASE}/api/admin/${path}`, {
    headers: { Authorization: `Bearer ${useAdminAuthStore().token}` },
  });
  if (!response.ok)
    throw new Error(
      (await response.json().catch(() => ({}))).message || "导出失败",
    );
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function useList(resource, defaults = {}) {
  const route = useRoute(),
    router = useRouter(),
    path = route.path;
  const cacheKey = `gingtto-query:${useAdminAuthStore().user?.id}:${resource}`;
  let cached = {};
  try {
    cached = JSON.parse(sessionStorage.getItem(cacheKey) || "{}");
  } catch {}
  const initial = Object.keys(route.query).length ? route.query : cached;
  const state = reactive({
    rows: [],
    total: 0,
    summary: {},
    statusCounts: {},
    loading: false,
    error: "",
    query: { page: 1, pageSize: 25, ...defaults, ...initial },
    filterKey: 0,
  });
  let controller,
    serial = 0;
  async function load() {
    controller?.abort();
    controller = new AbortController();
    const current = ++serial;
    state.loading = true;
    state.error = "";
    try {
      const params = new URLSearchParams(
        Object.entries(state.query).filter(([, v]) => v !== "" && v != null),
      );
      const result = await api(`${resource}?${params}`, {
        signal: controller.signal,
      });
      if (current === serial) {
        state.rows = result.items;
        state.total = result.total;
        state.summary = result.summary || {};
        state.statusCounts = result.statusCounts || {};
      }
    } catch (error) {
      if (current === serial && error.name !== "AbortError")
        state.error = error.message;
    } finally {
      if (current === serial) state.loading = false;
    }
  }
  const normalize = (q) =>
    JSON.stringify(
      Object.entries(q)
        .filter(([, v]) => v !== "" && v != null)
        .map(([k, v]) => [k, String(v)])
        .sort(),
    );
  watch(
    () => normalize(state.query),
    () => {
      const q = Object.fromEntries(
        Object.entries(state.query)
          .filter(([, v]) => v !== "" && v != null)
          .map(([k, v]) => [k, String(v)]),
      );
      try {
        sessionStorage.setItem(cacheKey, JSON.stringify(q));
      } catch {}
      if (route.path === path && normalize(q) !== normalize(route.query))
        router.replace({ query: q });
      load();
    },
    { immediate: true },
  );
  watch(
    () => route.query,
    (q) => {
      if (route.path !== path) return;
      const next = { page: 1, pageSize: 25, ...defaults, ...q };
      if (normalize(next) !== normalize(state.query)) state.query = next;
    },
  );
  watch(
    () =>
      normalize(
        Object.fromEntries(
          Object.entries(state.query).filter(
            ([key]) => !["page", "pageSize", "sort", "direction"].includes(key),
          ),
        ),
      ),
    () => {
      state.filterKey++;
    },
  );
  state.apply = (filters) => {
    state.query = { ...state.query, ...filters, page: 1 };
  };
  state.load = load;
  state.sort = ({ prop, order }) => {
    state.query = {
      ...state.query,
      sort: prop || "",
      direction: order === "ascending" ? "asc" : "desc",
      page: 1,
    };
  };
  onBeforeUnmount(() => controller?.abort());
  return state;
}
export function useDirty(value) {
  const baseline = ref("");
  const dirty = computed(
    () => baseline.value !== "" && JSON.stringify(value()) !== baseline.value,
  );
  const markClean = () => {
    baseline.value = JSON.stringify(value());
  };
  const canLeave = () =>
    !dirty.value || confirm("当前修改尚未保存，是否放弃修改？", "未保存修改");
  const beforeUnload = (event) => {
    if (dirty.value) {
      event.preventDefault();
      event.returnValue = "";
    }
  };
  window.addEventListener("beforeunload", beforeUnload);
  onBeforeUnmount(() =>
    window.removeEventListener("beforeunload", beforeUnload),
  );
  onBeforeRouteLeave(canLeave);
  return { dirty, markClean, canLeave };
}

export function uploadImage(file, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/admin/uploads`);
    xhr.setRequestHeader(
      "Authorization",
      `Bearer ${useAdminAuthStore().token}`,
    );
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () => reject(new Error("图片上传失败，请重试"));
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data.urls?.[0]);
      else reject(new Error(data.message || "图片上传失败"));
    };
    const body = new FormData();
    body.append("files", file);
    xhr.send(body);
  });
}
