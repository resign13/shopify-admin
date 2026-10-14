import { roleModules, defaultRoleModules } from '../permissions';
import { defineStore } from 'pinia';
import { request } from '../api';
import { setAuthSession, withAuthTransition } from '../authTransport';
const HINT_KEY = 'gingtto-admin-session-hint', OLD_TOKEN_KEY = 'lumiere-admin-token', CHANNEL = 'gingtto-admin-auth';
const PENDING_LOGOUT = 'gingtto-admin-logout-pending';
const EXPECTED_ROLE = 'admin', LOGIN_PATH = '/api/auth/admin/login';
const NETWORK_MESSAGE = '连接暂时中断，当前输入和提醒进度已保留，请重试连接。';
function hint() { try { return localStorage.getItem(HINT_KEY) || ''; } catch { return ''; } }
function remember(value) { try { localStorage.removeItem(OLD_TOKEN_KEY); localStorage.setItem(HINT_KEY,value || ''); if (value) localStorage.removeItem(PENDING_LOGOUT); } catch {} }
let bound = false, channel;
function bind(store) {
  if (bound || typeof window === 'undefined') return;
  bound = true;
  if (typeof BroadcastChannel !== 'undefined') channel = new BroadcastChannel(CHANNEL);
  const change = async (message) => {
    if (message?.type === 'logout') {
      if (store.sessionId === message.sessionId) store.clearLocalAuth(false);
    } else if (message?.sessionId !== store.sessionId) {
      setAuthSession();
      store.user = null;
      window.dispatchEvent(new Event('auth-identity-cleared'));
      await store.initialize();
    }
  };
  if (channel) channel.onmessage = event => change(event.data);
  window.addEventListener('storage', event => { if (event.key === HINT_KEY) change({type:event.newValue?'changed':'logout',sessionId:event.newValue || store.sessionId}); });
  window.addEventListener('auth-session-expired', () => store.clearLocalAuth(true));
}
function announce(type, id) { channel?.postMessage({type,sessionId:id}); }
export const useAdminAuthStore = defineStore('admin-auth',{
  state: () => ({sessionId:hint(),user:null,expiresAt:null,initialized:false,loading:false,error:'',revision:0}),
  getters: {
    isAuthenticated: (state) => Boolean(state.sessionId && state.user),
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
    canEditOrders() {
      return this.can("orders") && ["admin", "sales", "finance"].includes(this.userRole);
    },
    canAssignOrderOwner() {
      return this.canEditOrders && this.userRole !== "sales";
    },
    permissions: (state) =>
      (state.user?.permissions ?? defaultRoleModules(state.user?.role)).filter((key) =>
        roleModules(state.user?.role).includes(key),
      ),
    can() {
      return (module) => this.permissions.includes(module);
    },
    defaultRoute() {
      const preferred =
        this.userRole === "finance" ? "finance" : this.userRole === "warehouse"
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
    clearLocalAuth(broadcast = true) {
      const old = this.sessionId;
      this.revision++; this.sessionId = ''; this.user = null;
      setAuthSession(); remember('');
      if (broadcast) announce('logout',old);
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('auth-identity-cleared'));
    },
    async initialize() {
      bind(this);
      const pendingLogout = localStorage.getItem(PENDING_LOGOUT);
      if (pendingLogout) {
        try {
          await withAuthTransition(CHANNEL, () => request('/api/auth/logout', {method:'POST',headers:{'X-Auth-Session':pendingLogout}}));
          localStorage.removeItem(PENDING_LOGOUT);
        } catch (error) {
          if ([401,409].includes(error.status)) localStorage.removeItem(PENDING_LOGOUT);
          else { this.error = NETWORK_MESSAGE; this.initialized = true; return; }
        }
      }
      const revision = ++this.revision, previousUser = this.user;
      try {
        const data = await request('/api/auth/me');
        if (revision !== this.revision) return;
        if (data.role !== EXPECTED_ROLE) throw Object.assign(new Error('Role mismatch'),{status:401});
        const old = this.sessionId;
        this.sessionId = data.sessionId; this.user = data.user; this.expiresAt = data.expiresAt;
        setAuthSession(data.sessionId,data.csrfToken); remember(data.sessionId); this.error = '';
        if (old !== data.sessionId) announce('changed',data.sessionId);
      } catch (error) {
        if (revision !== this.revision) return;
        if ([401,403].includes(error.status)) this.clearLocalAuth();
        else { this.user = previousUser; this.error = NETWORK_MESSAGE; }
      } finally { this.initialized = true; }
    },
    async login(payload) {
      bind(this);
      if (this.loading) return false;
      const revision = ++this.revision;
      this.loading = true; this.error = '';
      try {
        return await withAuthTransition(CHANNEL, async () => {
          const data = await request(LOGIN_PATH,{method:'POST',body:JSON.stringify(payload)});
          if (revision !== this.revision) return false;
          this.sessionId = data.sessionId; this.user = data.user; this.expiresAt = data.expiresAt;
          setAuthSession(data.sessionId,data.csrfToken); remember(data.sessionId); announce('changed',data.sessionId);
          return true;
        });
      } catch (error) { if (revision === this.revision) this.error = error.code === 'login_failed' ? '账号或密码错误' : error.message; return false; }
      finally { this.loading = false; }
    },
    async logout() {
      const id = this.sessionId, revision = ++this.revision;
      if (id) localStorage.setItem(PENDING_LOGOUT,id);
      this.sessionId = ''; this.user = null; remember(''); announce('logout',id);
      setAuthSession();
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('auth-identity-cleared'));
      try { await withAuthTransition(CHANNEL, () => request('/api/auth/logout',{method:'POST',headers:id?{'X-Auth-Session':id}:{}})); localStorage.removeItem(PENDING_LOGOUT); } catch (error) { if ([401,409].includes(error.status)) localStorage.removeItem(PENDING_LOGOUT); }
      finally { if (revision === this.revision) setAuthSession(); }
    },
  },
});
