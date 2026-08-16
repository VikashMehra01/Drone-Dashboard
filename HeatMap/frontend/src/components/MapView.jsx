import { useEffect, useRef, useState, useMemo } from 'react'
import { MapContainer, TileLayer, Circle, Popup, useMap, Marker, FeatureGroup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { X, Video, BarChart3, SlidersHorizontal, Radio, RotateCcw } from 'lucide-react'
import { useNotification } from '../context/NotificationContext'
import { useSettings } from '../context/SettingsContext'
import HlsPlayer from './HlsPlayer'

/**
 * Returns true for protocols browsers cannot play natively (RTSP, RTMP …).
 * HTTP/HTTPS streams (MJPEG, HLS) are left for the <video> tag.
 */
function isNonPlayableUrl(url) {
    if (!url) return false
    try {
        const scheme = new URL(url).protocol.replace(':', '').toLowerCase()
        return ['rtsp', 'rtsps', 'rtmp', 'rtmps'].includes(scheme)
    } catch {
        return false
    }
}

/**
 * Returns true when an HTTP/HTTPS URL points to an HLS playlist (.m3u8).
 * Chrome cannot play these natively — they need hls.js.
 */
function isHlsUrl(url) {
    if (!url) return false
    try {
        return new URL(url).pathname.toLowerCase().endsWith('.m3u8')
    } catch {
        return url.toLowerCase().includes('.m3u8')
    }
}

// Fix default marker icon
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
    iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
})

// ─── Color interpolation based on intensity ───────────
function getHeatColor(value, maxIntensity) {
    const ratio = Math.min(value / maxIntensity, 1.0)
    // 5 stops: blue → green → yellow → orange → red
    const stops = [
        { pos: 0.0, r: 21, g: 101, b: 192 },   // #1565c0 - blue
        { pos: 0.25, r: 76, g: 175, b: 80 },    // #4caf50 - green
        { pos: 0.5, r: 255, g: 235, b: 59 },    // #ffeb3b - yellow
        { pos: 0.75, r: 255, g: 152, b: 0 },     // #ff9800 - orange
        { pos: 1.0, r: 244, g: 67, b: 54 },      // #f44336 - red
    ]
    let lower = stops[0], upper = stops[stops.length - 1]
    for (let i = 0; i < stops.length - 1; i++) {
        if (ratio >= stops[i].pos && ratio <= stops[i + 1].pos) {
            lower = stops[i]
            upper = stops[i + 1]
            break
        }
    }
    const range = upper.pos - lower.pos || 1
    const t = (ratio - lower.pos) / range
    const r = Math.round(lower.r + (upper.r - lower.r) * t)
    const g = Math.round(lower.g + (upper.g - lower.g) * t)
    const b = Math.round(lower.b + (upper.b - lower.b) * t)
    return `rgb(${r},${g},${b})`
}

function getDensityLabel(value, maxIntensity) {
    const ratio = value / maxIntensity
    if (ratio >= 0.8) return 'Critical'
    if (ratio >= 0.6) return 'Very High'
    if (ratio >= 0.4) return 'High'
    if (ratio >= 0.2) return 'Moderate'
    return 'Low'
}

function getDroneViewAngle(drone) {
    return Math.max(10, Math.min(170, Number(drone.viewAngle ?? 60)))
}

function getDroneFootprintRadiusMeters(drone) {
    const altitudeMeters = Math.max(1, Number(drone.altitude ?? 100))
    const viewAngleDeg = getDroneViewAngle(drone)
    return altitudeMeters * Math.tan((viewAngleDeg * Math.PI) / 360)
}

function getVideoNameFromUrl(url) {
    if (!url) return ''
    try {
        const parsed = new URL(url)
        return (parsed.pathname || '').split(/[\/\\]/).pop() || ''
    } catch {
        return String(url).split(/[\/\\]/).pop() || ''
    }
}

// ─── Heatmap Layer ────────────────────────────────────
function HeatmapLayer({ data }) {
    const map = useMap()
    const heatLayerRef = useRef(null)
    const isMountedRef = useRef(true)

    useEffect(() => {
        isMountedRef.current = true
        return () => {
            isMountedRef.current = false
        }
    }, [])

    useEffect(() => {
        import('leaflet.heat').then(() => {
            if (!isMountedRef.current || heatLayerRef.current) return

            heatLayerRef.current = L.heatLayer([], {
                radius: 35,
                blur: 25,
                maxZoom: 17,
                max: 1.0,
                gradient: {
                    0.1: '#1a237e',
                    0.2: '#283593',
                    0.3: '#1565c0',
                    0.4: '#0288d1',
                    0.5: '#00acc1',
                    0.6: '#4caf50',
                    0.7: '#8bc34a',
                    0.8: '#ffeb3b',
                    0.9: '#ff9800',
                    1.0: '#f44336',
                },
            }).addTo(map)

            const heatContainer = heatLayerRef.current.getContainer?.()
            if (heatContainer) {
                // Let map interactions pass through heat layer canvas.
                heatContainer.style.pointerEvents = 'none'
            }

            if (heatLayerRef.current._map) {
                heatLayerRef.current.setLatLngs(data)
                heatLayerRef.current.redraw()
            }
        })
    }, [map])

    useEffect(() => {
        if (!heatLayerRef.current) return
        if (heatLayerRef.current._map) {
            heatLayerRef.current.setLatLngs(data)
            heatLayerRef.current.redraw()
        }
    }, [data])



    useEffect(() => {
        return () => {
            if (!heatLayerRef.current) return
            map.removeLayer(heatLayerRef.current)
            heatLayerRef.current = null
        }
    }, [map])

    return null
}

function MapFocusController({ targetDrone, focusRequestId, circleRefs }) {
    const map = useMap()

    useEffect(() => {
        if (!targetDrone?.id || focusRequestId <= 0) return

        const lat = Number(targetDrone.latitude)
        const lng = Number(targetDrone.longitude)
        if (Number.isNaN(lat) || Number.isNaN(lng)) return

        map.flyTo([lat, lng], Math.max(map.getZoom(), 15), { duration: 0.9 })

        if (circleRefs?.current?.[targetDrone.id]) {
            setTimeout(() => {
                map.closePopup()
                const circle = circleRefs.current[targetDrone.id]
                if (circle && circle.openPopup) {
                    circle.openPopup()
                }
            }, 300) // Small delay to let panning start
        }
    }, [map, focusRequestId, targetDrone?.id, targetDrone?.latitude, targetDrone?.longitude, circleRefs])

    return null
}

// ─── Geocode a region name via Nominatim search ──────────────────────────────
const NOMINATIM_SEARCH = 'https://nominatim.openstreetmap.org/search'

async function geocodeRegion(query) {
    const url = `${NOMINATIM_SEARCH}?q=${encodeURIComponent(query + ', India')}&format=json&limit=1&addressdetails=0`
    try {
        const res = await fetch(url, { headers: { 'Accept-Language': 'en' } })
        if (!res.ok) return null
        const data = await res.json()
        if (!data.length) return null
        const { boundingbox } = data[0]
        // boundingbox: [minLat, maxLat, minLng, maxLng]
        return [
            [Number(boundingbox[0]), Number(boundingbox[2])],
            [Number(boundingbox[1]), Number(boundingbox[3])],
        ]
    } catch {
        return null
    }
}

/**
 * Watches filterState / filterDistrict and flies the map to the matched region.
 * District takes priority; falls back to state; clears to India view when both reset.
 */
function MapRegionController({ filterState, filterDistrict }) {
    const map = useMap()

    useEffect(() => {
        // Determine what to geocode: district > state > nothing
        const query = filterDistrict !== 'all'
            ? `${filterDistrict}${filterState !== 'all' ? ', ' + filterState : ''}`
            : filterState !== 'all'
                ? filterState
                : null

        if (!query) {
            // Both cleared — reset to India overview
            map.flyTo([22.5, 80.0], 5, { duration: 1.2 })
            return
        }

        let cancelled = false
        geocodeRegion(query).then(bounds => {
            if (cancelled || !bounds) return
            map.flyToBounds(bounds, { padding: [40, 40], maxZoom: filterDistrict !== 'all' ? 13 : 8, duration: 1.2 })
        })

        return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterState, filterDistrict])

    return null
}

/**
 * Watches resetTrigger and flies the map back to the full India overview.
 */
function MapResetController({ resetTrigger }) {
    const map = useMap()

    useEffect(() => {
        if (resetTrigger <= 0) return
        map.flyTo([22.5, 80.0], 5, { duration: 1.2 })
        map.closePopup()
    }, [map, resetTrigger])

    return null
}

export default function MapView({
    focusedDroneId = null,
    focusRequestId = 0,
    maxIntensityByDrone = {},
    setMaxIntensityByDrone = () => {},
    selectedDrone = null,
    setSelectedDrone = () => {},
    filterState = 'all',
    filterDistrict = 'all',
    setFocusedDroneId = () => {},
    setFocusRequestId = () => {},
}) {
    const { processStreamData } = useNotification()
    const { showLivePanelInfo, theme } = useSettings()
    const defaultCenter = [28.5900, 77.2200]
    const detailsPanelRef = useRef(null)
    const dragOffsetRef = useRef({ x: 0, y: 0 })
    const circleRefs = useRef({})
    const [drones, setDrones] = useState([])
    const activeDrones = drones.filter((d) => d.status === 'active' || d.status === 'debug')
    const center = activeDrones.length > 0
        ? [Number(activeDrones[0].latitude || defaultCenter[0]), Number(activeDrones[0].longitude || defaultCenter[1])]
        : defaultCenter

    // ── Reset trigger: increment to fly back to India overview ────────────────
    const [resetTrigger, setResetTrigger] = useState(0)
    const [showMarkers, setShowMarkers] = useState(false)

    // Refs for intervals to prevent stale closures
    const dronesRef = useRef(drones)
    const maxIntensityRef = useRef(maxIntensityByDrone)
    
    useEffect(() => {
        dronesRef.current = drones
        maxIntensityRef.current = maxIntensityByDrone
    }, [drones, maxIntensityByDrone])

    const [liveData, setLiveData] = useState({ headcount: 0, headcount_density: 0, frame_index: 0 })
    const [streamMetricsByVideo, setStreamMetricsByVideo] = useState({})
    const [isPlaying, setIsPlaying] = useState(true)
    const [loopVideo, setLoopVideo] = useState(true)
    const [isDraggingDetails, setIsDraggingDetails] = useState(false)
    const [detailsPanelPosition, setDetailsPanelPosition] = useState({ x: 18, y: 92 })
    const debugPlayback = new URLSearchParams(window.location.search).get('debugPlayback') === '1'
    const focusedDrone = useMemo(
        () => drones.find((d) => d.id === focusedDroneId) || null,
        [drones, focusedDroneId]
    )
    // User requested the map to always use the light theme tiles
    const tileTheme = 'light_all'
    const mapTileUrl = `https://{s}.basemaps.cartocdn.com/${tileTheme}/{z}/{x}/{y}{r}.png`

    useEffect(() => {
        const fetchDrones = async () => {
            try {
                const res = await fetch(`http://localhost:8000/api/drones/?include_debug=${debugPlayback}`)
                if (res.ok) {
                    const data = await res.json()
                    setDrones(data.drones || [])
                }
            } catch (err) {
                console.error('Error fetching live streams', err)
            }
        }

        fetchDrones()
        const interval = setInterval(fetchDrones, 1000)
        return () => clearInterval(interval)
    }, [])

    // Poll actual live API instead of CSV
    useEffect(() => {
        let frameCounter = 0;
        const fetchDensity = async () => {
            if (!isPlaying) return;
            try {
                const res = await fetch('http://localhost:8000/api/density/current');
                if (res.ok) {
                    const data = await res.json();
                    const streams = data.active_streams || {}
                    const byVideo = {}
                    let totalPoints = 0
                    let totalHeadcount = 0
                    let anyLoopTrue = false

                    Object.entries(streams).forEach(([source, stream]) => {
                        const videoName = getVideoNameFromUrl(source)
                        if (!videoName) return
                        byVideo[videoName] = stream
                        totalPoints += Number(stream?.points_count || 0)
                        totalHeadcount += Number(stream?.headcount || 0)
                        anyLoopTrue = anyLoopTrue || stream?.loop_video !== false
                    })

                    frameCounter++;
                    setStreamMetricsByVideo(byVideo)
                    setLoopVideo(Object.keys(byVideo).length > 0 ? anyLoopTrue : (data.current_data?.loop_video !== false));
                    setLiveData({
                        headcount: totalPoints,
                        headcount_density: totalHeadcount,
                        frame_index: frameCounter
                    });
                    
                    // Trigger alert processing loop using refs to avoid stale closures
                    processStreamData(dronesRef.current, byVideo, maxIntensityRef.current);
                }
            } catch (err) {
                console.error("Error fetching live density", err);
            }
        };

        fetchDensity();
        const interval = setInterval(fetchDensity, 1000); // refresh every 1s
        return () => clearInterval(interval);
    }, [isPlaying]);

    // Use liveData as frameData
    const frameData = liveData;

    useEffect(() => {
        if (!isDraggingDetails) return

        const handleMouseMove = (event) => {
            const panelWidth = detailsPanelRef.current?.offsetWidth || 420
            const panelHeight = detailsPanelRef.current?.offsetHeight || 520

            let nextX = event.clientX - dragOffsetRef.current.x
            let nextY = event.clientY - dragOffsetRef.current.y

            nextX = Math.max(8, Math.min(nextX, window.innerWidth - panelWidth - 8))
            nextY = Math.max(8, Math.min(nextY, window.innerHeight - panelHeight - 8))

            setDetailsPanelPosition({ x: nextX, y: nextY })
        }

        const handleMouseUp = () => setIsDraggingDetails(false)

        window.addEventListener('mousemove', handleMouseMove)
        window.addEventListener('mouseup', handleMouseUp)

        return () => {
            window.removeEventListener('mousemove', handleMouseMove)
            window.removeEventListener('mouseup', handleMouseUp)
        }
    }, [isDraggingDetails])

    const startDraggingDetails = (event) => {
        if (!detailsPanelRef.current) return
        const panelRect = detailsPanelRef.current.getBoundingClientRect()
        dragOffsetRef.current = {
            x: event.clientX - panelRect.left,
            y: event.clientY - panelRect.top,
        }
        setIsDraggingDetails(true)
    }

    const selectedDroneMetrics = useMemo(() => {
        if (!selectedDrone?.video_url) return null
        const videoName = getVideoNameFromUrl(selectedDrone.video_url)
        return streamMetricsByVideo[videoName] || null
    }, [selectedDrone, streamMetricsByVideo])

    const getDroneMaxIntensity = (drone) => {
        if (!drone?.id) return 100
        return Number(maxIntensityByDrone[drone.id] ?? 100)
    }

    const settingsDrone = selectedDrone || focusedDrone || activeDrones[0] || null
    const settingsDroneLimit = settingsDrone ? getDroneMaxIntensity(settingsDrone) : 100

    // Generate dynamic heatmap data based on the current frame density
    const dynamicHeatmapData = useMemo(() => {
        if (!frameData.headcount_density) return [];

        const points = [];
        
        activeDrones.forEach(liveDrone => {
            if (liveDrone.status !== 'active' && liveDrone.status !== 'debug') return;
            
            const metrics = streamMetricsByVideo[getVideoNameFromUrl(liveDrone.video_url)]
            const streamHeadcount = Number(metrics?.headcount ?? liveDrone.headcountDensity ?? 0)
            if (streamHeadcount <= 0) return

            const baseLat = Number(liveDrone.latitude || center[0]);
            const baseLng = Number(liveDrone.longitude || center[1]);
            const footprintRadiusMeters = getDroneFootprintRadiusMeters(liveDrone)
            const droneMaxIntensity = getDroneMaxIntensity(liveDrone)
            const intensity = Math.min(streamHeadcount / droneMaxIntensity, 1.0)
            const latRad = (baseLat * Math.PI) / 180
            const metersPerDegLat = 111320
            const metersPerDegLng = 111320 * Math.max(0.2, Math.cos(latRad))

            points.push([baseLat, baseLng, intensity]);

            // Deterministic footprint points inside the drone coverage circle.
            // This avoids jitter and keeps the heatmap stable when the drone is still.
            const spreadCount = Math.max(10, Math.floor(intensity * 22));
            const goldenAngle = Math.PI * (3 - Math.sqrt(5))

            for (let i = 0; i < spreadCount; i++) {
                const t = (i + 1) / spreadCount
                const radiusMeters = footprintRadiusMeters * Math.sqrt(t)
                const angle = i * goldenAngle

                const northMeters = radiusMeters * Math.cos(angle)
                const eastMeters = radiusMeters * Math.sin(angle)

                const latOffset = northMeters / metersPerDegLat
                const lngOffset = eastMeters / metersPerDegLng

                points.push([
                    baseLat + latOffset,
                    baseLng + lngOffset,
                    Math.max(0.08, intensity * (1 - t * 0.7))
                ]);
            }
        });
        
        return points;
    }, [frameData.headcount_density, activeDrones, center, streamMetricsByVideo, maxIntensityByDrone]);

    const handleDroneClick = (drone) => {
        setSelectedDrone(drone)
        setFocusedDroneId(drone.id)
        setFocusRequestId(prev => prev + 1)
    }

    return (
        <div className="map-container">
            <div className="map-header">
                <div>
                    <div className="map-header-title">Live Heatmap View</div>
                    <div className="map-header-subtitle">
                        Real-time crowd density overlay · {activeDrones.length} active drones
                    </div>
                </div>
                <div className="map-controls">
                    <button
                        className="map-control-btn map-reset-btn"
                        id="map-reset-btn"
                        onClick={() => {
                            setResetTrigger(t => t + 1)
                            setSelectedDrone(null)
                            setFocusedDroneId(null)
                        }}
                        title="Reset to India view"
                    >
                        <RotateCcw size={13} />
                        Reset View
                    </button>
                    <button 
                        className={`map-control-btn ${showMarkers ? 'active' : ''}`} 
                        id="markers-toggle"
                        onClick={() => setShowMarkers(m => !m)}
                    >
                        Markers
                    </button>
                </div>
            </div>

            <MapContainer
                center={center}
                zoom={12}
                className="leaflet-map"
                zoomControl={true}
                preferCanvas={true}
                maxZoom={18}
            >
                <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
                    url={mapTileUrl}
                />
                <MapFocusController targetDrone={focusedDrone} focusRequestId={focusRequestId} circleRefs={circleRefs} />
                <MapRegionController filterState={filterState} filterDistrict={filterDistrict} />
                <MapResetController resetTrigger={resetTrigger} />
                <HeatmapLayer data={dynamicHeatmapData} />
                {activeDrones.map((drone) => {
                    const isLiveDrone = drone.status === 'active' || drone.status === 'debug'
                    const metrics = streamMetricsByVideo[getVideoNameFromUrl(drone.video_url)]
                    const headcount = isLiveDrone ? Number(metrics?.headcount ?? drone.headcountDensity ?? 0) : drone.peopleCounted
                    const droneMaxIntensity = getDroneMaxIntensity(drone)
                    const color = getHeatColor(headcount, droneMaxIntensity)
                    const densityLabel = getDensityLabel(headcount, droneMaxIntensity)

                    // Ground footprint for vertical camera view:
                    // radius = altitude * tan(FOV/2)
                    // altitude in meters, FOV in degrees.
                    const viewAngleDeg = getDroneViewAngle(drone)
                    const footprintRadiusMeters = getDroneFootprintRadiusMeters(drone)

                    const circleElement = (
                        <Circle
                            key={drone.id}
                            ref={(r) => {
                                if (r) {
                                    circleRefs.current[drone.id] = r
                                }
                            }}
                            center={[drone.latitude, drone.longitude]}
                            radius={footprintRadiusMeters}
                            pathOptions={{
                                fillColor: color,
                                fillOpacity: 0.28,
                                stroke: false,
                            }}
                            eventHandlers={{
                                click: () => handleDroneClick(drone),
                            }}
                        >
                            <Popup>
                                <div style={{ color: 'var(--color-text-primary)', fontSize: '13px', lineHeight: 1.6 }}>
                                    <strong>{drone.name}</strong> ({drone.id})<br />
                                    Zone: {drone.zone || 'Live Stream Zone'}<br />
                                    Altitude: {drone.altitude ?? 100}m<br />
                                    View Angle: {viewAngleDeg}°<br />
                                    Coverage Radius: {Math.round(footprintRadiusMeters)}m<br />
                                    People: {Math.round(headcount || 0)}<br />
                                    Crowd Level: <strong style={{ color }}>{densityLabel}</strong><br />
                                    Battery: {drone.battery ?? 100}%
                                </div>
                            </Popup>
                        </Circle>
                    )

                    return (
                        <FeatureGroup key={`container-${drone.id}`}>
                            {circleElement}
                            {showMarkers && (
                                <Marker 
                                    position={[drone.latitude, drone.longitude]}
                                    icon={L.divIcon({
                                        className: 'custom-colored-marker',
                                        html: `<div style="background-color: ${color}; width: 16px; height: 16px; border-radius: 50%; border: 2px solid #ffffff; box-shadow: 0 2px 4px rgba(0,0,0,0.5);"></div>`,
                                        iconSize: [16, 16],
                                        iconAnchor: [8, 8]
                                    })}
                                    eventHandlers={{
                                        click: () => handleDroneClick(drone),
                                    }}
                                >
                                    <Popup>
                                        <div style={{ color: 'var(--color-text-primary)', fontSize: '13px', lineHeight: 1.6 }}>
                                            <strong>{drone.name}</strong> ({drone.id})<br />
                                            Zone: {drone.zone || 'Live Stream Zone'}<br />
                                            People: {Math.round(headcount || 0)}<br />
                                            Crowd Level: <strong style={{ color }}>{densityLabel}</strong>
                                        </div>
                                    </Popup>
                                </Marker>
                            )}
                        </FeatureGroup>
                    )
                })}
            </MapContainer>

            {/* ─── Playback Controls ─── */}
            {/* ─── Live Data Badge ─── */}
            <div className="playback-controls">
                <span className="frame-label">
                    {Math.round(frameData.headcount_density)} Estimated Crowd Count
                </span>
            </div>


            {/* ─── Draggable Drone Details Panel ─── */}
            {selectedDrone && (
                <div
                    ref={detailsPanelRef}
                    className="drone-feed-floating-panel"
                    style={{ left: `${detailsPanelPosition.x}px`, top: `${detailsPanelPosition.y}px` }}
                >
                    <div className="drone-feed-modal">
                        <div 
                            className="drone-feed-modal-header"
                            style={{ cursor: 'move', userSelect: 'none' }}
                            onMouseDown={startDraggingDetails}
                        >
                            <h3 title="Drag to move">
                                {selectedDrone.name} Live Feed
                            </h3>
                            <button
                                className="drone-feed-modal-close"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    setSelectedDrone(null)
                                }}
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: 'var(--color-text-secondary)',
                                    fontSize: '20px',
                                    padding: '4px',
                                }}
                            >
                                <X size={20} />
                            </button>
                        </div>
                        <div className="drone-feed-modal-content">
                            <div className="feed-video">
                                {selectedDrone.status === 'active' && (
                                    <div className="feed-live-badge">
                                        <span className="feed-live-dot" />
                                        Live
                                    </div>
                                )}
                                {selectedDrone.status === 'debug' && (
                                    <div className="feed-live-badge" style={{ background: '#7c3aed', color: '#ede9fe' }}>
                                        Debug Playback
                                    </div>
                                )}
                                {(selectedDrone.status === 'active' || selectedDrone.status === 'debug') ? (
                                    // Priority 1: backend provided an HLS URL (RTSP/RTMP via MediaMTX)
                                    selectedDrone.hls_url ? (
                                        <HlsPlayer
                                            src={selectedDrone.hls_url}
                                            className="feed-video-player"
                                        />
                                    // Priority 2: source is itself an HLS playlist (HTTP .m3u8)
                                    ) : isHlsUrl(selectedDrone.video_url) ? (
                                        <HlsPlayer
                                            src={selectedDrone.video_url}
                                            className="feed-video-player"
                                        />
                                    // Priority 3: non-playable protocol (RTMP without MediaMTX, etc.)
                                    ) : isNonPlayableUrl(selectedDrone.video_url) ? (
                                        <div className="feed-video-placeholder" style={{ gap: 10, padding: '20px 12px', fontSize: 12 }}>
                                            <Radio size={36} style={{ color: 'var(--color-accent-green)' }} />
                                            <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>
                                                {selectedDrone.name} — Live Stream
                                            </span>
                                            <span style={{ color: 'var(--color-text-muted)', wordBreak: 'break-all', maxWidth: 260, textAlign: 'center' }}>
                                                {selectedDrone.video_url}
                                            </span>
                                            <span style={{ color: 'var(--color-text-secondary)' }}>
                                                This stream protocol cannot be played in the browser.
                                            </span>
                                        </div>
                                    // Priority 4: local file or HTTP MJPEG — try native <video>
                                    ) : (
                                        <video
                                            key={selectedDrone.video_url}
                                            className="feed-video-player"
                                            autoPlay
                                            muted
                                            loop={loopVideo}
                                            playsInline
                                        >
                                            <source src={selectedDrone.video_url} type="video/mp4" />
                                            Your browser does not support the video tag.
                                        </video>
                                    )
                                ) : (
                                    <div className="feed-video-placeholder">
                                        <Video size={48} />
                                        <span>
                                            {selectedDrone.status === 'idle'
                                                ? `${selectedDrone.name} — Standby`
                                                : `${selectedDrone.name} — Offline`}
                                        </span>
                                    </div>
                                )}
                            </div>
                            <div className="drone-feed-details">
                                <h4 style={{ marginBottom: '12px', fontSize: '13px', fontWeight: 600 }}>
                                    Live Analytics
                                </h4>

                                {/* ─── Live CSV Data Panel ─── */}
                                {selectedDrone.status === 'active' && (
                                    <div className="live-csv-panel">
                                        <h4 style={{ margin: '16px 0 10px', fontSize: '13px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                                            <BarChart3 size={14} />
                                            Real-Time Detection Data
                                        </h4>
                                        <div className="csv-data-grid">

                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Peak Points</span>
                                                <span className="csv-stat-value">{Number(selectedDroneMetrics?.points_count ?? selectedDrone.peopleCounted ?? 0)}</span>
                                            </div>
                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Density Count</span>
                                                <span className="csv-stat-value" style={{
                                                    color: getHeatColor(
                                                        Number(selectedDroneMetrics?.headcount ?? selectedDrone.headcountDensity ?? 0),
                                                        getDroneMaxIntensity(selectedDrone)
                                                    )
                                                }}>
                                                    {Number(selectedDroneMetrics?.headcount ?? selectedDrone.headcountDensity ?? 0).toFixed(1)}
                                                </span>
                                            </div>
                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Intensity</span>
                                                <span className="csv-stat-value">
                                                    {getDensityLabel(
                                                        Number(selectedDroneMetrics?.headcount ?? selectedDrone.headcountDensity ?? 0),
                                                        getDroneMaxIntensity(selectedDrone)
                                                    )}
                                                </span>
                                            </div>
                                        </div>

                                        {/* Mini history bar chart removed for live stream */}
                                    </div>
                                )}

                                {/* ─── Drone Metadata Panel ─── */}
                                {showLivePanelInfo && selectedDrone && (
                                    <div className="live-metadata-panel" style={{ marginTop: '16px', background: 'var(--color-bg-secondary)', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                                        <h4 style={{ marginBottom: '10px', fontSize: '13px', fontWeight: 600 }}>Drone Metadata</h4>
                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px', color: 'var(--color-text-primary)' }}>
                                            <div><strong style={{ color: 'var(--color-text-secondary)' }}>Zone:</strong> {selectedDrone.zone || 'Unknown'}</div>
                                            <div><strong style={{ color: 'var(--color-text-secondary)' }}>Altitude:</strong> {selectedDrone.altitude}m</div>
                                            <div><strong style={{ color: 'var(--color-text-secondary)' }}>View Angle:</strong> {selectedDrone.viewAngle || 60}°</div>
                                            <div><strong style={{ color: 'var(--color-text-secondary)' }}>Coverage Radius:</strong> {selectedDrone.coverageRadius || 50}m</div>
                                            <div><strong style={{ color: 'var(--color-text-secondary)' }}>People:</strong> {Number(selectedDroneMetrics?.headcount ?? selectedDrone.headcountDensity ?? 0).toFixed(0)}</div>
                                            <div>
                                                <strong style={{ color: 'var(--color-text-secondary)' }}>Crowd Level:</strong>{' '}
                                                <span style={{ 
                                                    color: getHeatColor(
                                                        Number(selectedDroneMetrics?.headcount ?? selectedDrone.headcountDensity ?? 0),
                                                        getDroneMaxIntensity(selectedDrone)
                                                    ),
                                                    fontWeight: 'bold'
                                                }}>
                                                    {getDensityLabel(
                                                        Number(selectedDroneMetrics?.headcount ?? selectedDrone.headcountDensity ?? 0),
                                                        getDroneMaxIntensity(selectedDrone)
                                                    )}
                                                </span>
                                            </div>
                                            <div><strong style={{ color: 'var(--color-text-secondary)' }}>Battery:</strong> {selectedDrone.battery}%</div>
                                        </div>
                                    </div>
                                )}

                                {selectedDrone.status !== 'active' && !showLivePanelInfo && (
                                    <div className="detail-item">
                                        <span style={{ color: 'var(--color-text-secondary)' }}>
                                            Detailed metadata is available in the map popup.
                                        </span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
