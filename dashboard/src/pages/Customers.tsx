import { useEffect, useState } from "react"
import { getCustomers } from "../services/api"

export default function Customers() {
  const [customers, setCustomers] = useState<any[]>([])
  const [filter, setFilter] = useState("All")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getCustomers().then(d => { setCustomers(d.customers || []); setLoading(false) })
    const id = setInterval(() => getCustomers().then(d => setCustomers(d.customers || [])), 3000)
    return () => clearInterval(id)
  }, [])

  const filters = ["All", "Inside", "Waiting", "Moving", "Checkout"]
  const filtered = filter === "All" ? customers : customers.filter(c => c.status === filter || c.zone === filter)

  if (loading) return <div className="p-8 text-center text-slate-500">Loading customers...</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Customers <span className="text-sm font-normal text-slate-500">• Anonymous tracking only</span></h1>
        <span className="text-xs px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">DEMO</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {filters.map(f => (
          <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1.5 rounded-full text-sm border ${filter === f ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"}`}>{f}</button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
              <tr><th className="text-left px-4 py-3 font-medium">Customer</th><th className="text-left px-4 py-3 font-medium">Zone</th><th className="text-left px-4 py-3 font-medium">Status</th><th className="text-left px-4 py-3 font-medium">Time in Store</th></tr>
            </thead>
            <tbody className="divide-y">
              {filtered.map(c => (
                <tr key={c.customer_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{c.customer_id}</td>
                  <td className="px-4 py-3"><span className="px-2 py-1 rounded-full text-xs bg-slate-100 border">{c.zone}</span></td>
                  <td className="px-4 py-3"><span className={`px-2 py-1 rounded-full text-xs border ${c.status === "Waiting" ? "bg-amber-50 text-amber-700 border-amber-200" : c.status === "Moving" ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>{c.status}</span></td>
                  <td className="px-4 py-3 text-slate-600">{c.time_in_store}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && <div className="p-8 text-center text-slate-500">No customers in this filter</div>}
      </div>
      <p className="text-xs text-slate-400">Privacy: No names, faces, or personal data — anonymous IDs only.</p>
    </div>
  )
}
