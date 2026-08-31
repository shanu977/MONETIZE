import { useEffect, useState } from "react"
import { getDashboardSummary, getSystemStatus } from "../services/api"
import { Users, UserCheck, Clock3, AlertTriangle, Activity, Video, ScanEye, Map, Bell, Store } from "lucide-react"

export default function Dashboard() {
  const [summary, setSummary] = useState<any>(null)
  const [status, setStatus] = useState<any>(null)

  useEffect(() => {
    getDashboardSummary().then(setSummary)
    getSystemStatus().then(setStatus)
  }, [])

  const date = new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })
  const hour = new Date().getHours()
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold text-slate-900">{greet}, Admin</h1>
          <p className="text-sm text-slate-500">Store Overview • {date}</p>
        </div>
        <span className="inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" /> System Online
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Customers", value: summary?.total_customers ?? 12, sub: "Today", icon: Users, color: "bg-blue-50 text-blue-600" },
          { label: "Currently Inside", value: summary?.currently_inside ?? 7, sub: "Live", icon: UserCheck, color: "bg-emerald-50 text-emerald-600" },
          { label: "Payment Queue", value: summary?.payment_queue ?? 5, sub: "Waiting", icon: Clock3, color: "bg-amber-50 text-amber-600" },
          { label: "Active Alerts", value: summary?.active_alerts ?? 2, sub: "Needs attention", icon: AlertTriangle, color: "bg-rose-50 text-rose-600" },
        ].map((c) => (
          <div key={c.label} className="bg-white rounded-xl border border-slate-200 p-5 card-hover">
            <div className="flex items-center justify-between">
              <div className={`w-9 h-9 rounded-lg grid place-items-center ${c.color}`}><c.icon size={18} /></div>
              <span className="text-xs px-2 py-1 rounded-full bg-slate-50 border text-slate-600">{c.sub}</span>
            </div>
            <div className="mt-4 text-2xl font-semibold text-slate-900">{c.value}</div>
            <div className="text-sm text-slate-500">{c.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-medium text-slate-900 mb-1">Store Activity</h3>
          <p className="text-sm text-slate-500 mb-4">Customers per hour (demo data)</p>
          <div className="h-[180px] flex items-end gap-1.5">
            {[5, 8, 6, 9, 12, 7, 10, 14, 11, 9, 6, 4].map((h, i) => (
              <div key={i} className="flex-1 bg-slate-900 rounded-t" style={{ height: `${(h / 14) * 100}%` }} />
            ))}
          </div>
          <div className="flex justify-between text-xs text-slate-400 mt-2">{["09:00", "12:00", "15:00", "18:00"].map(t => <span key={t}>{t}</span>)}</div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-medium text-slate-900">System Status</h3>
          <p className="text-xs text-slate-500 mb-4">Real backend vs Demo</p>
          <div className="space-y-3">
            {[
              { k: "CCTV", v: status?.cctv, icon: Video },
              { k: "Customer Detection", v: status?.detection, icon: ScanEye },
              { k: "Tracking", v: status?.tracking, icon: Activity },
              { k: "Zone Engine", v: status?.zone_engine, icon: Map },
              { k: "Alert Engine", v: status?.alert_engine, icon: Bell },
              { k: "POS Integration", v: status?.pos_integration, icon: Store },
            ].map(({ k, v, icon: Icon }) => (
              <div key={k} className="flex items-center justify-between py-2.5 border-b last:border-0 border-slate-100">
                <div className="flex items-center gap-2.5">
                  <Icon size={16} className="text-slate-400" />
                  <span className="text-sm text-slate-700">{k}</span>
                </div>
                <span className={`text-xs px-2 py-1 rounded-full border ${v?.mode === "Demo" ? "bg-amber-50 text-amber-700 border-amber-200" : v?.status === "Online" || v?.status === "Running" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-slate-50 text-slate-600"}`}>
                  {v?.mode === "Demo" ? "Demo" : v?.status || "Offline"}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
