import { defineStore } from 'pinia'

import { API_BASE, request } from '../api'
import { useAdminAuthStore } from './auth'

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` }
}

function normalizeOrderItem(item = {}) {
  return {
    productId: Number(item.productId || 0),
    productName: item.productName || '',
    sku: item.sku || '',
    categoryKey: item.categoryKey || '',
    categoryLabel: item.categoryLabel || '',
    sizeCode: item.sizeCode || '',
    quantity: Number(item.quantity || 0),
    unitPrice: Number(item.unitPrice || 0),
    totalPrice: Number(item.totalPrice || 0),
    image: item.image || '',
  }
}

function normalizeGroupedOrder(order = {}) {
  const items = Array.isArray(order.items) ? order.items.map(normalizeOrderItem) : []
  const itemCount =
    Number(order.itemCount || 0) ||
    items.reduce((total, item) => total + Number(item.quantity || 0), 0)
  const totalAmount =
    Number(order.totalAmount || 0) ||
    items.reduce((total, item) => total + Number(item.totalPrice || 0), 0)

  return {
    id: Number(order.id || 0),
    orderNo: order.orderNo || '',
    createdAt: order.createdAt || '',
    updatedAt: order.updatedAt || '',
    status: order.status || 'pending_payment',
    userId: Number(order.userId || 0),
    userName: order.userName || '',
    companyName: order.companyName || '',
    userEmail: order.userEmail || '',
    contactName: order.contactName || '',
    contactValue: order.contactValue || '',
    phone: order.phone || '',
    country: order.country || '',
    address: order.address || '',
    apartment: order.apartment || '',
    city: order.city || '',
    state: order.state || '',
    zip: order.zip || '',
    shippingAddress: order.shippingAddress || '',
    note: order.note || '',
    labelPdfUrl: order.labelPdfUrl || '',
    labelImageUrls: Array.isArray(order.labelImageUrls) ? order.labelImageUrls : (order.labelPdfUrl ? [order.labelPdfUrl] : []),
    totalAmount,
    trackingNo: order.trackingNo || '',
    paymentLink: order.paymentLink || '',
    shippingFee: Number(order.shippingFee || 0),
    shippedAt: order.shippedAt || '',
    completedAt: order.completedAt || '',
    marketingOptIn: Boolean(order.marketingOptIn),
    itemCount,
    items,
  }
}

function groupLegacyOrders(rows = []) {
  const grouped = new Map()

  rows.forEach((row) => {
    const orderId = Number(row.id || 0)
    if (!grouped.has(orderId)) {
      grouped.set(orderId, {
        id: orderId,
        orderNo: row.orderNo || '',
        createdAt: row.createdAt || '',
        updatedAt: row.updatedAt || row.createdAt || '',
        status: row.status || 'pending_payment',
        userId: Number(row.userId || 0),
        userName: row.userName || '',
        companyName: row.companyName || '',
        userEmail: row.userEmail || '',
        contactName: row.contactName || '',
        contactValue: row.contactValue || row.userEmail || '',
        phone: row.phone || '',
        country: row.country || '',
        address: row.address || '',
        apartment: row.apartment || '',
        city: row.city || '',
        state: row.state || '',
        zip: row.zip || '',
        shippingAddress: row.shippingAddress || '',
        note: row.note || '',
        labelPdfUrl: row.labelPdfUrl || '',
        labelImageUrls: Array.isArray(row.labelImageUrls) ? row.labelImageUrls : (row.labelPdfUrl ? [row.labelPdfUrl] : []),
        totalAmount: 0,
        trackingNo: row.trackingNo || '',
        paymentLink: row.paymentLink || '',
        shippingFee: Number(row.shippingFee || 0),
        shippedAt: row.shippedAt || '',
        completedAt: row.completedAt || '',
        marketingOptIn: Boolean(row.marketingOptIn),
        itemCount: 0,
        items: [],
      })
    }

    const order = grouped.get(orderId)
    const item = normalizeOrderItem({
      productId: row.productId,
      productName: row.productName,
      sku: row.sku,
      categoryKey: row.categoryKey,
      categoryLabel: row.categoryLabel,
      sizeCode: row.sizeCode,
      quantity: row.quantity,
      unitPrice: row.unitPrice,
      totalPrice: row.totalPrice,
      image: row.image,
    })

    if (item.productId || item.productName || item.sku) {
      order.items.push(item)
      order.itemCount += item.quantity
      order.totalAmount += item.totalPrice
    }
  })

  return Array.from(grouped.values()).map(normalizeGroupedOrder)
}

function normalizeOrders(rows = []) {
  if (!Array.isArray(rows) || !rows.length) return []
  if (Array.isArray(rows[0]?.items)) {
    return rows.map(normalizeGroupedOrder)
  }
  return groupLegacyOrders(rows)
}

export const useAdminStore = defineStore('admin-data', {
  state: () => ({
    dashboard: null,
    products: [],
    inventoryItems: [],
    banners: [],
    homeConfig: null,
    categories: [],
    storeUsers: [],
    adminUsers: [],
    orders: [],
    loading: false,
    error: '',
  }),
  actions: {
    async loadDashboard(filters = {}) {
      const auth = useAdminAuthStore()
      const params = new URLSearchParams()
      Object.entries(filters || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '' && value !== 'all') {
          params.set(key, String(value))
        }
      })
      const query = params.toString() ? `?${params.toString()}` : ''
      const data = await request(`/api/admin/dashboard${query}`, { headers: authHeaders(auth.token) })
      this.dashboard = data
    },
    async loadProducts() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/products', { headers: authHeaders(auth.token) })
      this.products = data.items
    },
    async loadInventory() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/inventory', { headers: authHeaders(auth.token) })
      this.inventoryItems = data.items
    },
    async saveInventory(productId, sizeStocks) {
      const auth = useAdminAuthStore()
      const data = await request(`/api/admin/inventory/${productId}`, {
        method: 'PUT',
        headers: authHeaders(auth.token),
        body: JSON.stringify({ sizeStocks }),
      })
      const updated = data.product
      const syncList = (items) => {
        const index = items.findIndex((item) => Number(item.id || 0) === Number(updated.id || 0))
        if (index >= 0) {
          items.splice(index, 1, updated)
        }
      }
      syncList(this.inventoryItems)
      syncList(this.products)
      await this.loadDashboard()
      return updated
    },
    async loadCategories() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/categories', { headers: authHeaders(auth.token) })
      this.categories = data.items
    },
    async saveCategory(payload) {
      const auth = useAdminAuthStore()
      const isEdit = Boolean(payload.id)
      await request(`/api/admin/categories${isEdit ? `/${payload.id}` : ''}`, {
        method: isEdit ? 'PUT' : 'POST',
        headers: authHeaders(auth.token),
        body: JSON.stringify(payload),
      })
      await this.loadCategories()
    },
    async deleteCategory(id) {
      const auth = useAdminAuthStore()
      await request(`/api/admin/categories/${id}`, {
        method: 'DELETE',
        headers: authHeaders(auth.token),
      })
      await this.loadCategories()
    },
    async uploadFiles(files) {
      const auth = useAdminAuthStore()
      const formData = new FormData()
      for (const file of files || []) {
        if (file) formData.append('files', file)
      }
      const data = await request('/api/admin/uploads', {
        method: 'POST',
        headers: authHeaders(auth.token),
        body: formData,
        skipGlobalLoading: true,
      })
      return data.urls || []
    },
    async saveProduct(payload) {
      const auth = useAdminAuthStore()
      const isEdit = Boolean(payload.id)
      const data = await request(`/api/admin/products${isEdit ? `/${payload.id}` : ''}`, {
        method: isEdit ? 'PUT' : 'POST',
        headers: authHeaders(auth.token),
        body: JSON.stringify(payload),
      })
      const savedProducts = Array.isArray(data.product) ? data.product : [data.product].filter(Boolean)
      for (const product of savedProducts) {
        const index = this.products.findIndex((item) => Number(item.id || 0) === Number(product.id || 0))
        if (index >= 0) {
          this.products.splice(index, 1, product)
        } else {
          this.products.push(product)
        }
      }
      this.products.sort((left, right) => Number(left.id || 0) - Number(right.id || 0))
      this.loadDashboard().catch(() => {})
      return savedProducts
    },
    async deleteProduct(id) {
      const auth = useAdminAuthStore()
      await request(`/api/admin/products/${id}`, {
        method: 'DELETE',
        headers: authHeaders(auth.token),
      })
      await this.loadProducts()
      await this.loadHomeConfig()
      await this.loadDashboard()
    },
    async loadBanners() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/banners', { headers: authHeaders(auth.token) })
      this.banners = data.items
    },
    async saveBanner(payload) {
      const auth = useAdminAuthStore()
      const isEdit = Boolean(payload.id)
      await request(`/api/admin/banners${isEdit ? `/${payload.id}` : ''}`, {
        method: isEdit ? 'PUT' : 'POST',
        headers: authHeaders(auth.token),
        body: JSON.stringify(payload),
      })
      await this.loadBanners()
      await this.loadDashboard()
    },
    async loadHomeConfig() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/home-config', { headers: authHeaders(auth.token) })
      this.homeConfig = data.config
    },
    async saveHomeConfig(payload) {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/home-config', {
        method: 'PUT',
        headers: authHeaders(auth.token),
        body: JSON.stringify(payload),
      })
      this.homeConfig = data.config
    },
    async deleteBanner(id) {
      const auth = useAdminAuthStore()
      await request(`/api/admin/banners/${id}`, {
        method: 'DELETE',
        headers: authHeaders(auth.token),
      })
      await this.loadBanners()
      await this.loadDashboard()
    },
    async loadStoreUsers() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/store-users', { headers: authHeaders(auth.token) })
      this.storeUsers = data.items
    },
    async saveStoreUser(payload) {
      const auth = useAdminAuthStore()
      const isEdit = Boolean(payload.id)
      await request(`/api/admin/store-users${isEdit ? `/${payload.id}` : ''}`, {
        method: isEdit ? 'PUT' : 'POST',
        headers: authHeaders(auth.token),
        body: JSON.stringify(payload),
      })
      await this.loadStoreUsers()
      await this.loadDashboard()
    },
    async deleteStoreUser(id) {
      const auth = useAdminAuthStore()
      await request(`/api/admin/store-users/${id}`, {
        method: 'DELETE',
        headers: authHeaders(auth.token),
      })
      await this.loadStoreUsers()
      await this.loadDashboard()
    },
    async loadAdminUsers() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/admin-users', { headers: authHeaders(auth.token) })
      this.adminUsers = data.items
    },
    async saveAdminUser(payload) {
      const auth = useAdminAuthStore()
      const isEdit = Boolean(payload.id)
      await request(`/api/admin/admin-users${isEdit ? `/${payload.id}` : ''}`, {
        method: isEdit ? 'PUT' : 'POST',
        headers: authHeaders(auth.token),
        body: JSON.stringify(payload),
      })
      await this.loadAdminUsers()
      await this.loadDashboard()
    },
    async deleteAdminUser(id) {
      const auth = useAdminAuthStore()
      await request(`/api/admin/admin-users/${id}`, {
        method: 'DELETE',
        headers: authHeaders(auth.token),
      })
      await this.loadAdminUsers()
      await this.loadDashboard()
    },
    async loadOrders() {
      const auth = useAdminAuthStore()
      const data = await request('/api/admin/orders', { headers: authHeaders(auth.token) })
      this.orders = normalizeOrders(data.items)
    },
    async deleteOrders(orderIds = []) {
      const auth = useAdminAuthStore()
      const normalizedIds = Array.from(
        new Set(
          (Array.isArray(orderIds) ? orderIds : [orderIds])
            .map((id) => Number(id))
            .filter((id) => Number.isInteger(id) && id > 0)
        )
      )
      if (!normalizedIds.length) {
        throw new Error('No orders selected')
      }
      await request('/api/admin/orders', {
        method: 'DELETE',
        headers: authHeaders(auth.token),
        body: JSON.stringify({ orderIds: normalizedIds }),
      })
      await this.loadOrders()
      await this.loadDashboard()
    },
    async exportOrders(filters = {}) {
      const auth = useAdminAuthStore()
      const params = new URLSearchParams()
      Object.entries(filters || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.set(key, String(value))
        }
      })
      const response = await fetch(
        `/api/admin/orders/export${params.toString() ? `?${params.toString()}` : ''}`.replace(
          /^\/api/,
          `${API_BASE}/api`
        ),
        {
          headers: authHeaders(auth.token),
        }
      )
      if (!response.ok) {
        let message = 'Export failed'
        try {
          const data = await response.json()
          message = data.message || message
        } catch {
          // ignore json parse failure for file responses
        }
        throw new Error(message)
      }
      return response.blob()
    },
    async exportOrdersBySheet(filters = {}) {
      const auth = useAdminAuthStore()
      const params = new URLSearchParams()
      Object.entries(filters || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.set(key, String(value))
        }
      })
      const response = await fetch(
        `/api/admin/orders/export-by-sheet${params.toString() ? `?${params.toString()}` : ''}`.replace(
          /^\/api/,
          `${API_BASE}/api`
        ),
        {
          headers: authHeaders(auth.token),
        }
      )
      if (!response.ok) {
        let message = 'Export failed'
        try {
          const data = await response.json()
          message = data.message || message
        } catch {
          // ignore json parse failure for file responses
        }
        throw new Error(message)
      }
      return response.blob()
    },
    async exportOrderInvoice(orderId) {
      const auth = useAdminAuthStore()
      const response = await fetch(
        `/api/admin/orders/${orderId}/invoice`.replace(/^\/api/, `${API_BASE}/api`),
        {
          headers: authHeaders(auth.token),
        }
      )
      if (!response.ok) {
        let message = 'Export failed'
        try {
          const data = await response.json()
          message = data.message || message
        } catch {
          // ignore json parse failure for file responses
        }
        throw new Error(message)
      }
      return response.blob()
    },
    async updateOrderStatus(id, status, trackingNo = '', paymentLink = '', shippingFee = 0) {
      const auth = useAdminAuthStore()
      await request(`/api/admin/orders/${id}`, {
        method: 'PUT',
        headers: authHeaders(auth.token),
        body: JSON.stringify({ status, trackingNo, paymentLink, shippingFee }),
      })
      await this.loadOrders()
    },
  },
})
