// Service layer with real API fallback to mock
// Each function tries real backend first, falls back to mock demo data
// TODO: Replace mock imports with real endpoints when backend ready:
//   GET /api/cctv/live, /api/customers, /api/zones, etc.

export const API_BASE = "" // proxied via vite

async function fetchJSON(path: string, fallback: any) {
  try {
    const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" })
    if (!r.ok) throw new Error(String(r.status))
    const data = await r.json()
    return { ...data, _mode: data.mode || "Running" }
  } catch {
    return fallback
  }
}

async function postJSON(path: string, body: any, fallback: any) {
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(String(r.status))
    return await r.json()
  } catch {
    return fallback
  }
}

async function putJSON(path: string, body: any, fallback: any) {
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(String(r.status))
    return await r.json()
  } catch {
    return fallback
  }
}

async function deleteJSON(path: string, fallback: any) {
  try {
    const r = await fetch(`${API_BASE}${path}`, { method: "DELETE" })
    if (!r.ok) throw new Error(String(r.status))
    return await r.json()
  } catch {
    return fallback
  }
}

async function uploadFile(path: string, file: File, name: string, fallback: any) {
  try {
    const form = new FormData()
    form.append("file", file)
    form.append("name", name)
    const r = await fetch(`${API_BASE}${path}`, { method: "POST", body: form })
    if (!r.ok) throw new Error(String(r.status))
    return await r.json()
  } catch {
    return fallback
  }
}

export async function getDashboardSummary() {
  return fetchJSON("/api/dashboard/summary", {
    total_customers: 12,
    currently_inside: 7,
    payment_queue: 5,
    active_alerts: 2,
    mode: "Demo"
  })
}

export async function getSystemStatus() {
  return fetchJSON("/api/system/status", {
    cctv: { status: "Online", mode: "DEMO", source: "test 1.mp4" },
    detection: { status: "Running", mode: "Running" },
    tracking: { status: "Running", mode: "Running" },
    zone_engine: { status: "Running", mode: "Demo", zones: 2 },
    alert_engine: { status: "Demo Mode", mode: "Demo" },
    pos_integration: { status: "Not Connected", mode: "Offline" },
    system_online: true
  })
}

export async function getCctvStatus() {
  return fetchJSON("/api/cctv/status", {
    camera: "Test Camera", source: "test 1.mp4", status: "Live", mode: "DEMO", fps: 6, resolution: [848, 478], customers: 3
  })
}

export async function getCustomers() {
  return fetchJSON("/api/customers", { customers: [], count: 0, mode: "Demo" })
}

export async function getZones() {
  return fetchJSON("/api/zones", {
    map_id: "d6f8bd3b",
    map_name: "Store Floor",
    zones: [],
    mode: "Demo"
  })
}

export async function getAlerts() {
  return fetchJSON("/api/alerts", {
    alerts: [
      { id: "a1", severity: "critical", type: "Queue", message: "Payment queue exceeded threshold", zone: "Checkout Zone", customers: 5, time: "2 minutes ago", status: "Active" },
      { id: "a2", severity: "warning", type: "Wait", message: "Customer waiting too long", customer: "Customer_007", zone: "Products Zone", time: "4 minutes ago", status: "Active" },
      { id: "a3", severity: "info", type: "Info", message: "Checkout queue cleared", time: "10 minutes ago", status: "Resolved" },
    ],
    mode: "Demo"
  })
}

export async function getPayments() {
  return fetchJSON("/api/payments", {
    queue: [
      { customer_id: "Customer_001", waiting: "02:14", status: "Waiting" },
      { customer_id: "Customer_002", waiting: "01:47", status: "Waiting" },
      { customer_id: "Customer_003", waiting: "01:20", status: "Waiting" },
      { customer_id: "Customer_004", waiting: "00:58", status: "Waiting" },
      { customer_id: "Customer_005", waiting: "00:32", status: "Waiting" },
    ],
    current: 5, threshold: 5, status: "Busy", mode: "Demo"
  })
}

export async function getInventory(q = "") {
  const d = await fetchJSON(`/api/inventory?q=${encodeURIComponent(q)}`, null)
  if (d && d.items) return d
  const items = [
    { product: "Product A", stock: 24, status: "Normal" },
    { product: "Product B", stock: 3, status: "Low Stock" },
    { product: "Product C", stock: 0, status: "Out of Stock" },
    { product: "Product D", stock: 12, status: "Normal" },
    { product: "Instant Noodles", stock: 45, status: "Normal" },
    { product: "Cold Drinks", stock: 2, status: "Low Stock" },
  ]
  return { items: q ? items.filter(i => i.product.toLowerCase().includes(q.toLowerCase())) : items, mode: "Demo" }
}

export async function getAnalytics() {
  return fetchJSON("/api/analytics", {
    today_sales: 48250, bills: 42, items_sold: 183,
    sales_over_time: [
      { time: "09:00", sales: 3200 }, { time: "10:00", sales: 5400 }, { time: "11:00", sales: 4100 },
      { time: "12:00", sales: 6800 }, { time: "13:00", sales: 7200 }, { time: "14:00", sales: 5900 },
      { time: "15:00", sales: 8300 }, { time: "16:00", sales: 7300 },
    ],
    top_products: [
      { name: "Cold Drinks", sales: 45 }, { name: "Snacks", sales: 38 }, { name: "Instant Noodles", sales: 32 },
    ],
    category_sales: [
      { name: "Beverages", value: 40 }, { name: "Snacks", value: 30 }, { name: "Groceries", value: 20 }, { name: "Others", value: 10 },
    ],
    mode: "Demo"
  })
}

// ── Cameras ─────────────────────────────────────────────────────────
export async function listCameras() {
  return fetchJSON("/api/cameras", { cameras: [], mode: "Demo" })
}

export async function createCamera(data: any) {
  return postJSON("/api/cameras", data, { error: "Failed to create camera" })
}

export async function updateCamera(cameraId: string, data: any) {
  return putJSON(`/api/cameras/${cameraId}`, data, { error: "Failed to update camera" })
}

export async function deleteCamera(cameraId: string) {
  return deleteJSON(`/api/cameras/${cameraId}`, { error: "Failed to delete camera" })
}

export async function testCameraConnection(cameraId: string) {
  return postJSON(`/api/cameras/${cameraId}/test`, {}, { success: false, error: "Test failed" })
}

export async function connectCamera(cameraId: string) {
  return postJSON(`/api/cameras/${cameraId}/connect`, {}, { success: false, error: "Connect failed" })
}

export async function disconnectCamera(cameraId: string) {
  return postJSON(`/api/cameras/${cameraId}/disconnect`, {}, { success: false, error: "Disconnect failed" })
}

export async function setActiveCamera(cameraId: string) {
  return postJSON(`/api/cameras/active/${cameraId}`, {}, { success: false, error: "Failed to set active" })
}

export async function getActiveCameraStatus() {
  return fetchJSON("/api/cameras/active/status", { status: "NOT_CONFIGURED", mode: "Offline", message: "No CCTV camera connected" })
}

export async function getRuntimeStatus() {
  return fetchJSON("/api/runtime/status", { camera: {}, map: { map_id: null }, analytics: { active_customers: 0 }, processing: { detection: "running", tracking: "running" } })
}

// ── Demo ────────────────────────────────────────────────────────────
export async function getDemoStatus() {
  return fetchJSON("/api/demo/status", { active: false, camera_id: null })
}

export async function startDemo() {
  return postJSON("/api/demo/start", {}, { success: false, error: "Failed to start demo" })
}

export async function stopDemo() {
  return postJSON("/api/demo/stop", {}, { success: false, error: "Failed to stop demo" })
}

// ── Maps ────────────────────────────────────────────────────────────
export async function listMaps() {
  return fetchJSON("/api/maps", { maps: [], selected: null, mode: "Demo" })
}

export async function uploadMap(file: File, name: string) {
  return uploadFile("/api/maps/upload", file, name, { error: "Upload failed" })
}

export async function selectMap(mapId: string) {
  return postJSON(`/api/maps/${mapId}/select`, {}, { success: false, error: "Failed to select map" })
}

export async function deleteMap(mapId: string) {
  return deleteJSON(`/api/maps/${mapId}`, { success: false, error: "Failed to delete map" })
}
