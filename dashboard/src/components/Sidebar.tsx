import { NavLink } from "react-router-dom"
import { LayoutDashboard, Video, Users, Map, Bell, CreditCard, Package, BarChart3, Settings, Circle } from "lucide-react"

const items = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/live", label: "Live CCTV", icon: Video },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/zones", label: "Zones", icon: Map },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/payments", label: "Payments", icon: CreditCard },
  { to: "/inventory", label: "Inventory", icon: Package },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
]

export default function Sidebar({ collapsed, onToggle }: { collapsed?: boolean; onToggle?: () => void }) {
  return (
    <aside className={`${collapsed ? "w-[72px]" : "w-[260px]"} shrink-0 bg-[#0f172a] text-slate-200 flex flex-col transition-all duration-200`}>
      <div className="h-[64px] flex items-center gap-3 px-5 border-b border-white/10">
        <div className="w-8 h-8 rounded-lg bg-white text-[#0f172a] grid place-items-center font-bold text-[13px]">AI</div>
        {!collapsed && <div><div className="font-semibold tracking-wide text-sm">MONETIZE</div><div className="text-[11px] text-slate-400 -mt-1">Retail Intelligence</div></div>}
      </div>

      <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto">
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] transition-colors ${isActive ? "bg-white text-[#0f172a] font-medium" : "text-slate-400 hover:text-white hover:bg-white/10"}`
            }
          >
            <Icon size={18} />
            {!collapsed && label}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-white/10">
        <div className="flex items-center gap-3">
          <img src="https://i.pravatar.cc/100?img=12" alt="Admin" className="w-8 h-8 rounded-full object-cover" />
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-sm font-medium text-white leading-none">Admin</div>
              <div className="text-xs text-slate-400">Store Administrator</div>
              <div className="flex items-center gap-1.5 mt-1 text-[11px] text-emerald-400">
                <Circle size={8} className="fill-emerald-400 text-emerald-400" /> System Online
              </div>
            </div>
          )}
        </div>
        {onToggle && <button onClick={onToggle} className="mt-3 hidden lg:block text-xs text-slate-500 hover:text-slate-300 w-full text-left">{collapsed ? "Expand" : "Collapse"}</button>}
      </div>
    </aside>
  )
}
