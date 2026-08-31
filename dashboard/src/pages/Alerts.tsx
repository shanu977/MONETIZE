import { useEffect, useState } from "react"
import { getAlerts } from "../services/api"

export default function Alerts() {
  const [data, setData] = useState<any>(null)
  useEffect(() => { getAlerts().then(setData) }, [])
  const alerts = data?.alerts || []
  const sevColor: any = { critical: "border-rose-200 bg-rose-50", warning: "border-amber-200 bg-amber-50", info: "border-emerald-200 bg-emerald-50" }
  const sevDot: any = { critical: "bg-rose-500", warning: "bg-amber-500", info: "bg-emerald-500" }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Alerts</h1>
        <span className="text-xs px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">DEMO — replace with /api/alerts</span>
      </div>
      <div className="space-y-3">
        {alerts.map((a: any) => (
          <div key={a.id} className={`bg-white rounded-xl border p-4 ${sevColor[a.severity] || "border-slate-200"}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <span className={`mt-1 w-2.5 h-2.5 rounded-full ${sevDot[a.severity]}`} />
                <div>
                  <div className="text-sm font-medium text-slate-900 flex items-center gap-2">{a.severity === "critical" ? "🔴" : a.severity === "warning" ? "🟡" : "🟢"} {a.message} <span className={`text-xs px-1.5 py-0.5 rounded border ${a.status === "Active" ? "bg-rose-50 border-rose-200 text-rose-700" : a.status === "Acknowledged" ? "bg-amber-50 border-amber-200 text-amber-700" : "bg-emerald-50 border-emerald-200 text-emerald-700"}`}>{a.status}</span></div>
                  <div className="text-xs text-slate-500 mt-1">{a.zone || a.customer || ""} {a.customers ? `• ${a.customers} customers` : ""} • {a.time}</div>
                </div>
              </div>
              <div className="flex gap-1.5 shrink-0">
                <button onClick={() => alert("Acknowledge → POST /api/alerts/"+a.id+"/acknowledge (Demo)")} className="text-xs px-2.5 py-1.5 rounded-lg border bg-white hover:bg-slate-50">Acknowledge</button>
                <button onClick={() => alert("Resolve → POST /api/alerts/"+a.id+"/resolve")} className="text-xs px-2.5 py-1.5 rounded-lg bg-slate-900 text-white">Resolve</button>
              </div>
            </div>
          </div>
        ))}
        {alerts.length === 0 && <div className="bg-white rounded-xl border p-12 text-center text-slate-500">No active alerts</div>}
      </div>
    </div>
  )
}
