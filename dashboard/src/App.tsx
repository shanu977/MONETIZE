import { BrowserRouter, Routes, Route } from "react-router-dom"
import { useState } from "react"
import Sidebar from "./components/Sidebar"
import Dashboard from "./pages/Dashboard"
import LiveCCTV from "./pages/LiveCCTV"
import Customers from "./pages/Customers"
import Zones from "./pages/Zones"
import Alerts from "./pages/Alerts"
import Payments from "./pages/Payments"
import Inventory from "./pages/Inventory"
import Analytics from "./pages/Analytics"
import Settings from "./pages/Settings"

function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <div className="min-h-screen flex bg-[#f5f7fb]">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(v => !v)} />
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Mobile header */}
        <div className="lg:hidden h-12 bg-white border-b flex items-center px-4 justify-between">
          <span className="font-semibold">RETAIL AI</span>
          <button onClick={() => setCollapsed(!collapsed)} className="p-2 rounded-lg border">≡</button>
        </div>
        <main className="flex-1 p-4 lg:p-6 max-w-[1280px] w-full mx-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/live" element={<LiveCCTV />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/zones" element={<Zones />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/payments" element={<Payments />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
        <footer className="px-6 py-3 text-xs text-slate-400 border-t bg-white">
          <span className="px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 mr-2">DEMO MODE</span>
          CCTV: test 1.mp4 • Zones: zones/&lt;map_id&gt;.json via ZoneManager • POS: Not Connected
        </footer>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  )
}
