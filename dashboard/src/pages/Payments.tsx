import { useEffect, useState } from "react"
import { getPayments } from "../services/api"

export default function Payments() {
  const [data, setData] = useState<any>(null)
  useEffect(() => { getPayments().then(setData) }, [])
  if (!data) return <div className="p-8 text-center text-slate-500">Loading payments...</div>
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Payment Queue</h1>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border p-5">
          <div className="text-sm text-slate-500">Current Queue</div><div className="text-3xl font-semibold mt-1">{data.current}</div>
        </div>
        <div className="bg-white rounded-xl border p-5">
          <div className="text-sm text-slate-500">Threshold</div><div className="text-3xl font-semibold mt-1">{data.threshold}</div>
        </div>
        <div className={`rounded-xl border p-5 ${data.status === "Busy" ? "bg-amber-50 border-amber-200" : "bg-emerald-50 border-emerald-200"}`}>
          <div className="text-sm opacity-80">Status</div><div className="text-lg font-medium mt-1">{data.status === "Busy" ? "⚠ Queue Busy" : "✓ Normal"}</div>
          <div className="text-xs mt-1 opacity-70">DEMO — will use CCTV payment-zone detection</div>
        </div>
      </div>
      <div className="bg-white rounded-xl border divide-y">
        {data.queue.map((c: any) => (
          <div key={c.customer_id} className="flex items-center justify-between p-4">
            <div className="font-medium text-slate-900">{c.customer_id}</div>
            <div className="text-sm text-slate-500">Waiting {c.waiting}</div>
            <span className="text-xs px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">{c.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
