export default function Settings() {
  return (
    <div className="space-y-4 max-w-2xl">
      <h1 className="text-xl font-semibold">Settings</h1>
      <div className="bg-white rounded-xl border p-5 space-y-4">
        <div>
          <label className="text-sm font-medium">Store Name</label>
          <input defaultValue="Main Store" className="mt-1 w-full px-3 py-2 rounded-lg border border-slate-200 text-sm" />
        </div>
        <div>
          <label className="text-sm font-medium">Video Source</label>
          <select className="mt-1 w-full px-3 py-2 rounded-lg border border-slate-200 text-sm bg-white">
            <option>test 1.mp4 (Demo)</option>
            <option>RTSP Camera (future)</option>
          </select>
          <p className="text-xs text-slate-500 mt-1">Abstraction: VideoSource → TestVideoSource / RTSPCameraSource — UI unchanged.</p>
        </div>
        <button className="px-4 py-2 bg-slate-900 text-white rounded-lg text-sm">Save</button>
      </div>
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">DEMO MODE — some settings use mock data until backend ready.</div>
    </div>
  )
}
