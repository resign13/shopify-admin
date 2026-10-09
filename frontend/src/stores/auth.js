import { roleModules } from "../permissions";
import { defineStore } from "pinia";

import { request } from "../api";

const TOKEN_KEY = "lumiere-admin-token";

function readToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function writeToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {}
}

export const useAdminAuthStore = defineStore("admin-auth", {
  state: () => ({
    token: readToken(),
    user: null,
    initialized: false,
    loading: false,
    error: "",
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token && state.user),
    userRole: (state) => state.user?.role || "",
    isSuperAdmin() {
      return this.userRole === "admin";
    },
    isWarehouse() {
      return this.userRole === "warehouse";
    },
    isCustomer() {
      return this.userRole === "customer";
    },
    canManageAccounts() {
      return this.can("admin-users");
    },
    permissions: (state) =>
      (state.user?.permissions ?? roleModules(state.user?.role)).filter((key) =>
        roleModules(state.user?.role).includes(key),
      ),
    can() {
      return (module) => this.permissions.includes(module);
    },
    defaultRoute() {
      const preferred =
        this.userRole === "warehouse"
          ? "orders"
          : this.userRole === "customer"
            ? "inventory"
            : "dashboard";
      return this.can(preferred)
        ? "/" + preferred
        : this.permissions.length
          ? "/" + this.permissions[0]
          : "/no-access";
    },
  },
  actions: {
    async initialize() {
      if (!this.token) {
        this.initialized = true;
        return;
      }
      const token = this.token;
      try {
        const data = await request("/api/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (this.token !== token) return;
        if (data.role !== "admin") throw new Error("Role mismatch");
        this.user = data.user;
        this.error = "";
      } catch (error) {
        if (this.token !== token) return;
        this.user = null;
        if ([401, 403].includes(error.status) || error.message === "Role mismatch") {
          this.token = "";
          writeToken("");
        } else {
          // Transport errors are not a new login: retain the session and its voice queue.
          // Protected views remain unavailable until /auth/me succeeds again.
          this.error = "连接暂时中断，恢复网络后请点击重试连接；原登录进度已保留。";
        }
      } finally {
        this.initialized = true;
      }
    },
    async login(payload) {
      this.loading = true;
      this.error = "";
      try {
        const data = await request("/api/auth/admin/login", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        this.token = data.token;
        this.user = data.user;
        writeToken(data.token);
        return true;
      } catch (error) {
        this.error = error.message || "Login failed";
        return false;
      } finally {
        this.loading = false;
      }
    },
    async logout() {
      const token = this.token;
      // Stop local listeners and notify other tabs before waiting for the network.
      this.token = "";
      this.user = null;
      writeToken("");
      try {
        if (token) {
          await request("/api/auth/logout", {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
          });
        }
      } catch {}
    },
  },
});
