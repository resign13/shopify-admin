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
      try {
        const data = await request("/api/auth/me", {
          headers: { Authorization: `Bearer ${this.token}` },
        });
        if (data.role !== "admin") throw new Error("Role mismatch");
        this.user = data.user;
      } catch {
        this.token = "";
        this.user = null;
        writeToken("");
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
      try {
        if (this.token) {
          await request("/api/auth/logout", {
            method: "POST",
            headers: { Authorization: `Bearer ${this.token}` },
          });
        }
      } catch {}
      this.token = "";
      this.user = null;
      writeToken("");
    },
  },
});
