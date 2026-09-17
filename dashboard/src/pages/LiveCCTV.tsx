import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { 
  getCustomers, 
  getZones, 
  listCameras, 
  createCamera, 
  updateCamera, 
  deleteCamera, 
  testCameraConnection, 
  connectCamera, 
  disconnectCamera, 
  setActiveCamera, 
  getActiveCameraStatus, 
  startDemo, 
  stopDemo, 
  listMaps, 
  uploadMap, 
  selectMap, 
  deleteMap,
  getRuntimeStatus 
} from "../services/api"

type Mode = "cctv" | "map" | "split"

type Camera = {
  id: string
  name: string
  source_type: string
  rtsp_url: string
  status: string
  enabled: boolean
  fps: number
  resolution?: number[]
  last_connected?: string
}

export default function LiveCCTV() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>("split")
  const [status, setStatus] = useState<any>(null)
  const [customers, setCustomers] = useState<any[]>([])
  const [zones, setZones] = useState<any[]>([])
  const [mapMeta, setMapMeta] = useState<any>(null)
  const [runtimeStatus, setRuntimeStatus] = useState<any>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [maps, setMaps] = useState<any[]>([])
  const [showCameraModal, setShowCameraModal] = useState(false)
  const [showMapModal, setShowMapModal] = useState(false)
  const [editingCamera, setEditingCamera] = useState<Camera | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [operationInProgress, setOperationInProgress] = useState(false)

  const statusColors = {
    "NOT_CONFIGURED": "bg-slate-100 text-slate-800 border-slate-300",
    "CONNECTING": "bg-blue-100 text-blue-800 border-blue-300",
    "CONNECTED": "bg-emerald-100 text-emerald-800 border-emerald-300",
    "DISCONNECTED": "bg-amber-100 text-amber-800 border-amber-300",
    "ERROR": "bg-rose-100 text-rose-800 border-rose-300",
    "DEMO": "bg-purple-100 text-purple-800 border-purple-300",
  }

  useEffect(() => {
    loadInitialData()
  }, [])

  const loadInitialData = async () => {
    try {
      setLoading(true)
      const [
        camerasData,
        mapsData,
        runtimeData,
        statusData,
        customersData,
        zonesData,
      ] = await Promise.all([
        listCameras(),
        listMaps(),
        getRuntimeStatus(),
        getActiveCameraStatus(),
        getCustomers(),
        getZones(),
      ])
      
      setCameras(camerasData.cameras || [])
      setMaps(mapsData.maps || [])
      setRuntimeStatus(runtimeData)
      setStatus(statusData)
      setCustomers(customersData.customers || [])
      setZones(zonesData.zones || [])
      
      if (mapsData.selected && !mapMeta) {
        fetch("/api/zones/map").then(r => r.ok ? r.json() : null).then(m => m && !m.error && setMapMeta(m))
      }
    } catch (error) {
      console.error("Failed to load initial data:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const interval = setInterval(() => {
      refreshStatus()
    }, 2000)
    return () => clearInterval(interval)
  }, [])

  const refreshStatus = async () => {
    try {
      const [
        statusData,
        customersData,
        zonesData,
        runtimeData,
      ] = await Promise.all([
        getActiveCameraStatus(),
        getCustomers(),
        getZones(),
        getRuntimeStatus(),
      ])
      
      setStatus(statusData)
      setCustomers(customersData.customers || [])
      setZones(zonesData.zones || [])
      setRuntimeStatus(runtimeData)
    } catch (error) {
      console.error("Failed to refresh status:", error)
    }
  }

  const getVideoSourceUrl = () => {
    if (!status?.source) return null
    
    if (status.status === "DEMO" || status.mode === "DEMO") {
      return "/test 1.mp4"
    }
    
    return `/api/cctv/stream`
  }

  const getVideoOverlayClass = () => {
    if (!status?.status) return "hidden"
    
    if (status.status === "DEMO" || status.mode === "DEMO") {
      return "bg-purple-900/20"
    }
    
    if (status.status === "CONNECTED" || status.status === "CONNECTING") {
      return "bg-emerald-900/20"
    }
    
    if (status.status === "ERROR") {
      return "bg-rose-900/20"
    }
    
    return "bg-slate-900/20"
  }

  const getStatusText = () => {
    if (!status?.status) return "No CCTV camera connected"
    
    switch (status.status) {
      case "DEMO":
        return "Demo Mode - Using test 1.mp4"
      case "CONNECTED":
        return "Connected"
      case "CONNECTING":
        return "Connecting..."
      case "DISCONNECTED":
        return "Disconnected"
      case "ERROR":
        return "Connection Error"
      case "NOT_CONFIGURED":
        return "Not Configured"
      default:
        return status.status || "Unknown"
    }
  }

  const getStatusColor = () => {
    if (!status?.status) return "bg-slate-100 text-slate-800"
    
    return (statusColors as Record<string, string>)[status.status] || statusColors.NOT_CONFIGURED
  }

  const getConnectionButtonText = () => {
    if (!status?.status) return "Connect CCTV"
    
    switch (status.status) {
      case "DEMO":
        return "Stop Demo"
      case "CONNECTED":
        return "Disconnect"
      case "CONNECTING":
        return "Connecting..."
      case "DISCONNECTED":
        return "Connect"
      case "ERROR":
        return "Retry Connection"
      case "NOT_CONFIGURED":
        return "Connect CCTV"
      default:
        return "Connect CCTV"
    }
  }

  const getCameraButtonText = () => {
    if (status?.status === "DEMO") {
      return "Use Demo Mode"
    }
    return "Connect CCTV"
  }

  const handleConnection = async () => {
    if (operationInProgress) return
    
    setOperationInProgress(true)
    try {
      if (!status?.status || status.status === "NOT_CONFIGURED") {
        setShowCameraModal(true)
        return
      }
      
      if (status.status === "DEMO") {
        await stopDemo()
        await refreshStatus()
      } else if (status.status === "CONNECTED") {
        await disconnectCamera(status.id)
        await refreshStatus()
      } else if (status.status === "ERROR") {
        await connectCamera(status.id)
        await refreshStatus()
      }
    } catch (error) {
      console.error("Connection operation failed:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const handleCameraSelect = async (camera: Camera) => {
    if (operationInProgress) return
    
    setOperationInProgress(true)
    try {
      await setActiveCamera(camera.id)
      await refreshStatus()
    } catch (error) {
      console.error("Failed to select camera:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const handleDemoMode = async () => {
    if (operationInProgress) return
    
    setOperationInProgress(true)
    try {
      if (status?.status === "DEMO") {
        await stopDemo()
      } else {
        await startDemo()
      }
      await refreshStatus()
    } catch (error) {
      console.error("Demo mode operation failed:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const handleSaveCamera = async (cameraData: any) => {
    if (operationInProgress) return
    
    setOperationInProgress(true)
    try {
      if (editingCamera) {
        await updateCamera(editingCamera.id, cameraData)
      } else {
        await createCamera(cameraData)
      }
      
      await loadInitialData()
      setShowCameraModal(false)
      setEditingCamera(null)
    } catch (error) {
      console.error("Failed to save camera:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const handleDeleteCamera = async (cameraId: string) => {
    if (operationInProgress) return
    if (!confirm("Delete this camera?")) return
    
    setOperationInProgress(true)
    try {
      await deleteCamera(cameraId)
      await loadInitialData()
    } catch (error) {
      console.error("Failed to delete camera:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const handleTestConnection = async (cameraId: string) => {
    if (operationInProgress) return
    
    setOperationInProgress(true)
    try {
      await testCameraConnection(cameraId)
      await refreshStatus()
    } catch (error) {
      console.error("Failed to test connection:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const handleUploadMap = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files || event.target.files.length === 0) return
    
    const file = event.target.files[0]
    setIsUploading(true)
    
    try {
      await uploadMap(file, "")
      await loadInitialData()
      setShowMapModal(false)
    } catch (error) {
      console.error("Failed to upload map:", error)
    } finally {
      setIsUploading(false)
      event.target.value = ""
    }
  }

  const handleDeleteMap = async (mapId: string) => {
    if (!confirm("Delete this map?")) return
    
    setOperationInProgress(true)
    try {
      await deleteMap(mapId)
      await loadInitialData()
    } catch (error) {
      console.error("Failed to delete map:", error)
    } finally {
      setOperationInProgress(false)
    }
  }

  const renderCCTVVideo = () => {
    const videoSrc = getVideoSourceUrl()
    const overlayClass = getVideoOverlayClass()
    
    return (
      <div className="h-[420px] bg-slate-900 relative flex items-center justify-center overflow-hidden">
        {videoSrc === "/api/cctv/stream" ? (
          <img 
            src={videoSrc} 
            alt="CCTV" 
            className="w-full h-full object-cover" 
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none"
              ;(e.target as HTMLImageElement).nextElementSibling?.classList.remove("hidden")
            }} 
          />
        ) : (
          <video 
            src={videoSrc ?? undefined} 
            controls 
            autoPlay 
            muted 
            loop 
            className="w-full h-full object-cover"
          />
        )}
        
        <div className={`hidden absolute inset-0 grid place-items-center ${overlayClass} text-slate-400 p-6 text-center`}>
          <div>
            {status?.status === "NOT_CONFIGURED" || !status?.status ? (
              <>
                <div className="text-sm font-medium text-white mb-2">CCTV NOT CONNECTED</div>
                <div className="text-xs mb-4">No physical CCTV camera is currently connected.</div>
                <div className="text-xs mb-3 flex flex-wrap gap-2 justify-center">
                  <button 
                    onClick={() => setShowCameraModal(true)}
                    className="px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs transition-colors"
                    disabled={operationInProgress}
                  >
                    Connect CCTV
                  </button>
                  <button 
                    onClick={handleDemoMode}
                    className="px-3 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs transition-colors"
                    disabled={operationInProgress}
                  >
                    Use Demo Mode
                  </button>
                </div>
              </>
            ) : status?.status === "DEMO" ? (
              <>
                <div className="text-sm font-medium text-purple-300 mb-2">DEMO MODE</div>
                <div className="text-xs mb-2">Using test 1.mp4 for presentation</div>
                <div className="text-xs mb-3 text-slate-400">Click "Stop Demo" to return to disconnected state</div>
              </>
            ) : status?.status === "ERROR" ? (
              <>
                <div className="text-sm font-medium text-rose-300 mb-2">CONNECTION ERROR</div>
                <div className="text-xs mb-3">Camera connection failed.</div>
                <div className="text-xs mb-3 px-3 py-1 bg-rose-900/50 rounded border border-rose-700">
                  Check RTSP URL, credentials, network, or camera availability.
                </div>
              </>
            ) : status?.status === "CONNECTING" ? (
              <>
                <div className="text-sm font-medium text-blue-300 mb-2">CONNECTING...</div>
                <div className="text-xs">Attempting to connect to camera...</div>
              </>
            ) : status?.status === "DISCONNECTED" ? (
              <>
                <div className="text-sm font-medium text-amber-300 mb-2">DISCONNECTED</div>
                <div className="text-xs mb-3">Camera is disconnected.</div>
              </>
            ) : (
              <>
                <div className="text-sm font-medium text-slate-300 mb-2">Loading...</div>
                <div className="text-xs">Preparing video stream...</div>
              </>
            )}
          </div>
        </div>
        
        <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between text-xs">
          <span className="px-2 py-1 rounded bg-black/60 text-white">
            Camera: {status?.name || (status?.status === "DEMO" ? "Demo Camera" : "Not Configured")} • 
            {status?.fps || (status?.status === "DEMO" ? 6 : 0)} FPS • 
            {customers.length} customers
          </span>
          <span className={`px-2 py-1 rounded font-medium ${getStatusColor()}`}>● {getStatusText()}</span>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">LIVE CCTV</h1>
            <p className="text-sm text-slate-500">Loading...</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <div className="text-sm text-slate-500">Loading Live CCTV interface...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            LIVE CCTV
            <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${getStatusColor()}`}>● {status?.status || "NOT_CONFIGURED"}</span>
          </h1>
          <p className="text-sm text-slate-500">
            {status?.status === "DEMO" 
              ? `Demo Camera • ${status?.fps || 6} FPS • ${customers.length} customers`
              : status?.status === "CONNECTED" || status?.status === "CONNECTING"
              ? `Real CCTV • ${status?.name || "Connected Camera"}`
              : "No CCTV camera connected • Use Demo Mode for testing"
            }
          </p>
        </div>
        <div className="inline-flex p-1 bg-slate-100 rounded-lg">
          {(["cctv", "map", "split"] as Mode[]).map(m => (
            <button 
              key={m} 
              onClick={() => setMode(m)} 
              className={`px-3 py-1.5 text-sm rounded-md capitalize transition-colors ${mode === m ? "bg-white shadow text-slate-900" : "text-slate-600 hover:text-slate-900"}`}
            >
              {m === "cctv" ? "CCTV" : m === "map" ? "Bird's-Eye" : "Split View"}
            </button>
          ))}
        </div>
      </div>

      {status?.status === "NOT_CONFIGURED" && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-800">
          <span className="font-medium">Getting Started:</span> No real CCTV camera is connected. 
          Click <span className="font-medium">"Connect CCTV"</span> to add a real camera, 
          or <span className="font-medium">"Use Demo Mode"</span> to test with sample video.
        </div>
      )}

      <div className={`grid gap-4 ${mode === "split" ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1"}`}>
        {(mode === "cctv" || mode === "split") && (
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            {renderCCTVVideo()}
            <div className="p-3 flex items-center gap-2 text-xs text-slate-600 border-t">
              <span>Source: {status?.source || (status?.status === "DEMO" ? "test 1.mp4" : "Not Configured")}</span>
              <span className="h-3 w-px bg-slate-200" />
              <span>Resolution: {status?.resolution?.join("x") || (status?.status === "DEMO" ? "848x478" : "N/A")}</span>
            </div>
            {mode === "cctv" && (
              <div className="px-3 py-2 bg-slate-50 border-t text-xs flex flex-wrap gap-2">
                <button
                  onClick={handleConnection}
                  className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg transition-colors disabled:opacity-50"
                  disabled={operationInProgress}
                >
                  {getConnectionButtonText()}
                </button>
                <button
                  onClick={handleDemoMode}
                  className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors disabled:opacity-50"
                  disabled={operationInProgress}
                >
                  {getCameraButtonText()}
                </button>
                <button
                  onClick={() => navigate("/settings")}
                  className="px-3 py-1.5 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg transition-colors"
                >
                  Camera Settings
                </button>
              </div>
            )}
          </div>
        )}

        {(mode === "map" || mode === "split") && (
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="h-[420px] bg-[#f8fafc] relative p-3 flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-slate-900">Zone Map</span>
                <span className="text-xs px-2 py-1 rounded-full bg-slate-100 border">
                  {zones.length} zones • {mapMeta ? mapMeta.name : "Store Floor"}
                </span>
              </div>
              <div className="flex-1 border border-slate-200 rounded-lg bg-white overflow-hidden relative">
                {mapMeta ? (
                  <div className="absolute inset-0 flex items-center justify-center bg-slate-50">
                    <div className="text-center p-6 max-w-[80%]">
                      <div className="grid grid-cols-2 gap-2">
                        {zones.map((z: any, i: number) => (
                          <div key={z.zone_id || i} className="border-2 border-dashed rounded-lg p-3 bg-blue-50/50 border-blue-300">
                            <div className="text-xs font-medium text-blue-700">{z.name}</div>
                            <div className="text-[11px] text-slate-500">{z.customers ?? 0} customers • {z.status || "Normal"}</div>
                          </div>
                        ))}
                        {zones.length === 0 && (
                          <div className="col-span-2 text-sm text-slate-400 py-10">
                            No zones — open Zone Editor to create zones
                          </div>
                        )}
                      </div>
                      {/* Customer dots */}
                      <div className="absolute inset-0 pointer-events-none">
                        {customers.slice(0, 5).map((c, i) => (
                          <div 
                            key={c.customer_id} 
                            className="absolute w-2.5 h-2.5 rounded-full bg-rose-500 border-2 border-white shadow"
                            style={{ left: `${20 + i * 15}%`, top: `${30 + (i % 3) * 12}%` }} 
                            title={c.customer_id} 
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="h-full grid place-items-center text-sm text-slate-500">
                    No map selected — use Zone Editor to select a map
                  </div>
                )}
              </div>
            </div>
            <div className="p-3 border-t bg-slate-50">
              <div className="text-xs text-slate-600 flex items-center justify-between">
                <span>Selected Map: {mapMeta ? mapMeta.name : "None"}</span>
                {mapMeta && (
                  <button
                    onClick={() => setShowMapModal(true)}
                    className="text-purple-600 hover:text-purple-700 font-medium"
                  >
                    Manage Maps
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
        <span className="font-medium">SYSTEM STATUS:</span> 
        Camera: {status?.status === "DEMO" ? "Demo Mode (test 1.mp4)" : (status?.status === "CONNECTED" ? "Connected" : "Not Connected")} • 
        Map: {mapMeta ? mapMeta.name : "Not Selected"} • 
        Detection: {runtimeStatus?.processing?.detection || "running"} • 
        Tracking: {runtimeStatus?.processing?.tracking || "running"}
      </div>
    </div>
  )
}
