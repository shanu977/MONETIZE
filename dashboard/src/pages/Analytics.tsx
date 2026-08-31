import { useEffect, useState } from "react"
import { getAnalytics } from "../services/api"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell } from "recharts"

export default function Analytics() {
  const [data, setData] = useState<any>(null)
  useEffect(() => { getAnalytics().then(setData) }, [])
  if (!data) return <div className="p-8 text-center text-slate-500">Loading analytics...</div>
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Sales / Bill Analytics</h1>
        <span className="text-xs px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">DEMO — future bill parser</span>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border p-5"><div className="text-sm text-slate-500">Today's Sales</div><div className="text-2xl font-semibold mt-1">₹{data.today_sales.toLocaleString()}</div></div>
        <div className="bg-white rounded-xl border p-5"><div className="text-sm text-slate-500">Bills</div><div className="text-2xl font-semibold mt-1">{data.bills}</div></div>
        <div className="bg-white rounded-xl border p-5"><div className="text-sm text-slate-500">Items Sold</div><div className="text-2xl font-semibold mt-1">{data.items_sold}</div></div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white rounded-xl border p-5">
          <div className="font-medium mb-2">Sales over time</div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.sales_over_time}>
                <XAxis dataKey="time" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip />
                <Line type="monotone" dataKey="sales" stroke="#0f172a" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="bg-white rounded-xl border p-5">
          <div className="font-medium mb-2">Top products</div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.top_products}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-15} dy={10} height={50} /><YAxis /><Tooltip /><Bar dataKey="sales" fill="#0f172a" radius={[6,6,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border p-5">
        <div className="font-medium mb-2">Category sales</div>
        <div className="h-[200px] flex items-center justify-center">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data.category_sales} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                {data.category_sales.map((_:any, i:number) => <Cell key={i} fill={["#0f172a","#334155","#94a3b8","#e2e8f0"][i%4]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="text-xs text-slate-400">Flow: POS bill → bill parser → products → sales → inventory → dashboard (future)</div>
    </div>
  )
}
