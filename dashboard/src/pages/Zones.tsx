import { useEffect, useState } from "react"
import { getZones } from "../services/api"

export default function Zones() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getZones().then(d => { setData(d); setLoading(false) })
  }, [])

  if (loading) return <div className="p-8 text-center text-slate-500">Loading zones...</div>
  if (!data || data.zones.length === 0) return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Zones</h1>
      <div className="bg-white rounded-xl border p-12 text-center">
        <div className="text-sm text-slate-500">No zones defined</div>
        <div className="text-xs text-slate-400 mt-1">Open the Zone Editor to create zones</div>
        <button onClick={() => window.open("/api/zones", "_blank")} className="mt-4 px-4 py-2 bg-slate-900 text-white rounded-lg text-sm">Manage Zones</button>
      </div>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Zones <span className="text-sm font-normal text-slate-500">• {data.map_name || data.map_id}</span></h1>
        <a href="#" onClick={(e) => { e.preventDefault(); alert("Zone Editor is a Python Tkinter app:\npython -m app.phase2.zones.editor\nIt edits zones/<map_id>.json — dashboard refreshes automatically") }} className="px-3 py-1.5 bg-slate-900 text-white rounded-lg text-sm">Manage Zones</a>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data.zones.map((z: any) => (
          <div key={z.zone_id} className="bg-white rounded-xl border p-5 card-hover">
            <div className="flex items-center justify-between">
              <div className="font-medium text-slate-900">{z.name}</div>
              <span className={`text-xs px-2 py-1 rounded-full border ${z.status === "Busy" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>{z.status || "Normal"}</span>
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-2xl font-semibold">{z.customers ?? z.occupancy ?? 0}</span>
              <span className="text-sm text-slate-500">customers</span>
            </div>
            <div className="mt-1 text-xs text-slate-500">Occupancy: {z.occupancy ?? z.customers ?? 0} • Updated just now</div>
            <div className="mt-3 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-slate-900" style={{ width: `${Math.min(100, (z.occupancy || 0) * 20)}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">Source: <code className="bg-white px-1 rounded border">zones/{data.map_id}.json</code> via <code className="bg-white px-1 rounded border">ZoneManager / ZoneEngine</code> — dashboard refreshes when file changes.</div>
    </div>
  )
}
