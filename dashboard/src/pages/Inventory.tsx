import { useEffect, useState } from "react"
import { getInventory } from "../services/api"

export default function Inventory() {
  const [q, setQ] = useState("")
  const [data, setData] = useState<any>(null)
  useEffect(() => { getInventory(q).then(setData) }, [q])
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Inventory</h1>
        <span className="text-xs px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">DEMO — future POS/bill parser</span>
      </div>
      <div className="relative max-w-sm">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search products..." className="w-full pl-9 pr-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10" />
        <span className="absolute left-3 top-2.5 text-slate-400">⌕</span>
      </div>
      <div className="bg-white rounded-xl border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="text-left px-4 py-3 font-medium">Product</th><th className="text-left px-4 py-3 font-medium">Stock</th><th className="text-left px-4 py-3 font-medium">Status</th></tr></thead>
          <tbody className="divide-y">
            {(data?.items || []).map((r: any) => (
              <tr key={r.product} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-medium text-slate-900">{r.product}</td>
                <td className="px-4 py-3">{r.stock}</td>
                <td className="px-4 py-3"><span className={`px-2 py-1 rounded-full text-xs border ${r.status === "Normal" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : r.status === "Low Stock" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-rose-50 text-rose-700 border-rose-200"}`}>{r.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
