import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import Map, { Source, Layer, Marker, Popup, NavigationControl } from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'
import { X, Video, BarChart3, SlidersHorizontal, Radio, RotateCcw, Loader2, Minimize2, Maximize2 } from 'lucide-react'
import { useNotification } from '../context/NotificationContext'
import { useSettings } from '../context/SettingsContext'
import { useDrones } from '../context/DronesContext'
import HlsPlayer from './HlsPlayer'

// OpenFreeMap — free, no API key, no signup. "positron" mirrors the plain
// light basemap this app always used; "dark" is a real dark cartographic
// style, replacing the old approach of CSS-filtering a light basemap.
const MAP_STYLES = {
  light: 'https://tiles.openfreemap.org/styles/positron',
  dark: 'https://tiles.openfreemap.org/styles/dark',
}

const INDIA_OVERVIEW = { longitude: 80.0, latitude: 22.5, zoom: 5 }

// Matches --navbar-height in index.css — keeps the floating drone-details
// panel's drag bounds from letting it overlap the sticky navbar.
const NAVBAR_HEIGHT = 64

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

/**
 * Builds a geodesic circle polygon (GeoJSON ring, [lng, lat] pairs) around
 * a center point — MapLibre has no built-in "circle sized in meters"
 * primitive like Leaflet's L.circle, so this fills that gap with the same
 * flat-earth approximation the heatmap footprint math already used.
 */
function makeGeoCircleRing(lat, lng, radiusMeters, numPoints = 64) {
    const latRad = (lat * Math.PI) / 180
    const metersPerDegLat = 111320
    const metersPerDegLng = 111320 * Math.max(0.2, Math.cos(latRad))
    const ring = []
    for (let i = 0; i <= numPoints; i++) {
        const angle = (i / numPoints) * 2 * Math.PI
        const dLat = (radiusMeters * Math.cos(angle)) / metersPerDegLat
        const dLng = (radiusMeters * Math.sin(angle)) / metersPerDegLng
        ring.push([lng + dLng, lat + dLat])
    }
    return ring
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
        // Nominatim boundingbox: [minLat, maxLat, minLng, maxLng].
        // MapLibre fitBounds wants [[west,south],[east,north]] — lng,lat order.
        return [
            [Number(boundingbox[2]), Number(boundingbox[0])],
            [Number(boundingbox[3]), Number(boundingbox[1])],
        ]
    } catch {
        return null
    }
}

const HEATMAP_PAINT = {
    'heatmap-weight': ['interpolate', ['linear'], ['get', 'weight'], 0, 0, 1, 1],
    'heatmap-intensity': 1,
    'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 5, 15, 11, 35, 15, 70],
    'heatmap-opacity': 0.75,
    'heatmap-color': [
        'interpolate', ['linear'], ['heatmap-density'],
        0, 'rgba(0,0,0,0)',
        0.2, '#1a237e',
        0.4, '#1565c0',
        0.6, '#4caf50',
        0.8, '#ffeb3b',
        1, '#f44336',
    ],
}

export default function MapView({
    focusedDroneId = null,
    focusRequestId = 0,
    maxIntensityByDrone = {},
    setMaxIntensityByDrone = () => {},
    selectedDroneId = null,
    setSelectedDroneId = () => {},
    filterState = 'all',
    filterDistrict = 'all',
    setFocusedDroneId = () => {},
    setFocusRequestId = () => {},
}) {
    const { processStreamData } = useNotification()
    const { showLivePanelInfo, theme } = useSettings()
    const defaultCenter = { latitude: 28.5900, longitude: 77.2200 }
    const detailsPanelRef = useRef(null)
    const dragOffsetRef = useRef({ x: 0, y: 0 })
    const mapRef = useRef(null)
    const { drones, currentDensity } = useDrones()
    const activeDrones = drones.filter((d) => d.status === 'active' || d.status === 'debug')
    const center = activeDrones.length > 0
        ? { latitude: Number(activeDrones[0].latitude || defaultCenter.latitude), longitude: Number(activeDrones[0].longitude || defaultCenter.longitude) }
        : defaultCenter

    // ── Reset trigger: increment to fly back to India overview ────────────────
    const [resetTrigger, setResetTrigger] = useState(0)
    const [showMarkers, setShowMarkers] = useState(false)
    const [popupDroneId, setPopupDroneId] = useState(null)
    // MapLibre needs a network round-trip (style JSON, sprites, glyphs,
    // vector tiles) before anything is visible — unlike Leaflet's raster
    // tiles this isn't instant, so show a loading state instead of a blank
    // box while that's in flight.
    const [mapLoaded, setMapLoaded] = useState(false)

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
    // Collapses the floating panel down to just video + drone name — toggled
    // by the "M" key (see effect below) or the header button.
    const [isPanelMinimized, setIsPanelMinimized] = useState(false)
    const focusedDrone = useMemo(
        () => drones.find((d) => d.id === focusedDroneId) || null,
        [drones, focusedDroneId]
    )
    // Re-derived fresh every render from the live `drones` poll — not a
    // frozen click-time snapshot — so the floating panel below reflects the
    // drone's actual current status/battery/etc. instead of going stale the
    // moment it stops matching what was true when it was clicked.
    const selectedDrone = useMemo(
        () => drones.find((d) => d.id === selectedDroneId) || null,
        [drones, selectedDroneId]
    )
    const popupDrone = useMemo(
        () => activeDrones.find((d) => d.id === popupDroneId) || null,
        [activeDrones, popupDroneId]
    )
    const mapStyleUrl = MAP_STYLES[theme === 'light' ? 'light' : 'dark']

    // drones and currentDensity both come from the shared DronesContext poll
    // (one /api/drones/ + /api/density/current fetch per second, shared with
    // Sidebar/Dashboard/DensityStats/DroneFeed). The breakdown below is a
    // pure derivation of currentDensity, recomputed on every poll tick
    // regardless of isPlaying.
    const densityDerived = useMemo(() => {
        const streams = currentDensity.active_streams || {}
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

        return {
            byVideo,
            loopVideo: Object.keys(byVideo).length > 0 ? anyLoopTrue : (currentDensity.current_data?.loop_video !== false),
            headcount: totalPoints,
            headcount_density: totalHeadcount,
        }
    }, [currentDensity])

    const frameCounterRef = useRef(0)
    // Not a pure derivation, so this stays an effect rather than folding into
    // the useMemo above: it (a) freezes the displayed snapshot while paused
    // instead of tracking densityDerived live, and (b) fires the alert-
    // processing side effect below.
    useEffect(() => {
        if (!isPlaying) return;

        frameCounterRef.current += 1;
        setStreamMetricsByVideo(densityDerived.byVideo)
        setLoopVideo(densityDerived.loopVideo);
        setLiveData({
            headcount: densityDerived.headcount,
            headcount_density: densityDerived.headcount_density,
            frame_index: frameCounterRef.current
        });

        // Trigger alert processing loop using refs to avoid stale closures
        processStreamData(dronesRef.current, densityDerived.byVideo, maxIntensityRef.current);
    }, [densityDerived, isPlaying]);

    // Use liveData as frameData
    const frameData = liveData;

    useEffect(() => {
        if (!isDraggingDetails) return

        let rafId = null
        let pendingPosition = null

        const applyPending = () => {
            if (pendingPosition) {
                setDetailsPanelPosition(pendingPosition)
                pendingPosition = null
            }
            rafId = null
        }

        const handleMouseMove = (event) => {
            const panelWidth = detailsPanelRef.current?.offsetWidth || 420
            const panelHeight = detailsPanelRef.current?.offsetHeight || 520
            const minX = 8, maxX = window.innerWidth - panelWidth - 8
            // Top bound sits below the sticky navbar (--navbar-height: 64px),
            // not just 8px from the viewport edge — otherwise the panel can
            // be dragged up underneath/into the navbar and overlap it.
            const minY = NAVBAR_HEIGHT + 12, maxY = window.innerHeight - panelHeight - 8

            let nextX = event.clientX - dragOffsetRef.current.x
            let nextY = event.clientY - dragOffsetRef.current.y

            nextX = Math.max(minX, Math.min(nextX, maxX))
            nextY = Math.max(minY, Math.min(nextY, maxY))

            // Coalesce to at most one state update per animation frame.
            // Without this, mousemove fires far faster than the screen can
            // repaint (well over 60Hz on many mice/trackpads), which was
            // queuing more re-renders of this component — a live MapLibre
            // map plus heatmap and drone-circle layers — than the browser
            // could keep up with, and that backlog is what made dragging
            // feel laggy rather than tracking the cursor 1:1.
            pendingPosition = { x: nextX, y: nextY }
            if (rafId === null) {
                rafId = requestAnimationFrame(applyPending)
            }
        }

        const handleMouseUp = () => setIsDraggingDetails(false)

        window.addEventListener('mousemove', handleMouseMove)
        window.addEventListener('mouseup', handleMouseUp)

        return () => {
            if (rafId !== null) cancelAnimationFrame(rafId)
            window.removeEventListener('mousemove', handleMouseMove)
            window.removeEventListener('mouseup', handleMouseUp)
        }
    }, [isDraggingDetails])

    // "M" toggles the floating panel between full and minimized (video +
    // name only) while it's open. Ignored while typing anywhere else in the
    // app (search boxes, form fields, etc.) so it doesn't hijack normal text
    // entry — only fires when no input/textarea/select/contentEditable is
    // focused.
    useEffect(() => {
        if (!selectedDrone) return

        const handleKeyDown = (event) => {
            if (event.key.toLowerCase() !== 'm' || event.metaKey || event.ctrlKey || event.altKey) return
            const active = document.activeElement
            const tag = active?.tagName
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active?.isContentEditable) return
            setIsPanelMinimized((prev) => !prev)
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [selectedDrone])

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

    // Per-drone metrics used by both the footprint circles and the heatmap
    // source below — computed once so the two stay visually consistent.
    const droneVisuals = useMemo(() => {
        return activeDrones.map((drone) => {
            const metrics = streamMetricsByVideo[getVideoNameFromUrl(drone.video_url)]
            const headcount = Number(metrics?.headcount ?? drone.headcountDensity ?? 0)
            const droneMaxIntensity = getDroneMaxIntensity(drone)
            const color = getHeatColor(headcount, droneMaxIntensity)
            const densityLabel = getDensityLabel(headcount, droneMaxIntensity)
            const viewAngleDeg = getDroneViewAngle(drone)
            const footprintRadiusMeters = getDroneFootprintRadiusMeters(drone)
            const intensity = Math.min(headcount / droneMaxIntensity, 1.0)
            return { drone, headcount, color, densityLabel, viewAngleDeg, footprintRadiusMeters, intensity }
        })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeDrones, streamMetricsByVideo, maxIntensityByDrone])

    // Native MapLibre heatmap layer — one weighted point per drone, radius
    // scaled by zoom. Replaces the old manual point-spreading hack (spiral of
    // synthetic points around each drone) that leaflet.heat needed; MapLibre's
    // GPU heatmap shader does that spreading itself from a single point.
    const heatmapGeoJSON = useMemo(() => ({
        type: 'FeatureCollection',
        features: droneVisuals
            .filter((v) => v.headcount > 0)
            .map((v) => ({
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [Number(v.drone.longitude), Number(v.drone.latitude)] },
                properties: { weight: v.intensity },
            })),
    }), [droneVisuals])

    const droneLayerIds = useMemo(() => droneVisuals.map((v) => `drone-circle-${v.drone.id}`), [droneVisuals])

    const focusOnDrone = useCallback((drone, { openPopup = true } = {}) => {
        if (!drone) return
        const lat = Number(drone.latitude)
        const lng = Number(drone.longitude)
        if (Number.isNaN(lat) || Number.isNaN(lng)) return
        const map = mapRef.current
        if (map) {
            map.flyTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 15), duration: 900 })
        }
        if (openPopup) {
            setTimeout(() => setPopupDroneId(drone.id), 300)
        }
    }, [])

    const handleDroneClick = (drone) => {
        setSelectedDroneId(drone.id)
        setFocusedDroneId(drone.id)
        setFocusRequestId(prev => prev + 1)
    }

    // ── Focus-on-drone (triggered by focusRequestId, e.g. clicking a Fleet
    // Status card) ──────────────────────────────────────────────────────────
    useEffect(() => {
        if (!focusedDrone?.id || focusRequestId <= 0) return
        focusOnDrone(focusedDrone)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusRequestId, focusedDrone?.id, focusedDrone?.latitude, focusedDrone?.longitude])

    // ── Region filter (state/district dropdowns) — geocode + fly to bounds ───
    useEffect(() => {
        const query = filterDistrict !== 'all'
            ? `${filterDistrict}${filterState !== 'all' ? ', ' + filterState : ''}`
            : filterState !== 'all'
                ? filterState
                : null

        const map = mapRef.current
        if (!map) return

        if (!query) {
            map.flyTo({ center: [INDIA_OVERVIEW.longitude, INDIA_OVERVIEW.latitude], zoom: INDIA_OVERVIEW.zoom, duration: 1200 })
            return
        }

        let cancelled = false
        geocodeRegion(query).then((bounds) => {
            if (cancelled || !bounds) return
            map.fitBounds(bounds, { padding: 40, maxZoom: filterDistrict !== 'all' ? 13 : 8, duration: 1200 })
        })

        return () => { cancelled = true }
    }, [filterState, filterDistrict])

    // ── Reset view ────────────────────────────────────────────────────────────
    useEffect(() => {
        if (resetTrigger <= 0) return
        const map = mapRef.current
        if (!map) return
        map.flyTo({ center: [INDIA_OVERVIEW.longitude, INDIA_OVERVIEW.latitude], zoom: INDIA_OVERVIEW.zoom, duration: 1200 })
        setPopupDroneId(null)
    }, [resetTrigger])

    const onMapClick = useCallback((event) => {
        const feature = event.features?.[0]
        if (!feature) return
        const droneId = feature.properties?.droneId
        const visual = droneVisuals.find((v) => v.drone.id === droneId)
        if (!visual) return
        handleDroneClick(visual.drone)
        focusOnDrone(visual.drone)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [droneVisuals, focusOnDrone])

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
                            setSelectedDroneId(null)
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

            {/*
              react-map-gl's `className` prop does NOT merge with MapLibre's
              own internal "maplibregl-map" class on the root div (it gets
              silently dropped), so `.maplibre-map`'s CSS never matched when
              applied directly on <Map>. This wrapper div is what actually
              carries the sizing class instead; <Map> just fills it via 100%.
            */}
            <div className="maplibre-map">
            {!mapLoaded && (
                <div className="map-loading-overlay">
                    <Loader2 size={22} className="spin-icon" />
                    <span>Loading map…</span>
                </div>
            )}
            <Map
                ref={mapRef}
                initialViewState={{ longitude: center.longitude, latitude: center.latitude, zoom: 12 }}
                mapStyle={mapStyleUrl}
                interactiveLayerIds={droneLayerIds}
                onClick={onMapClick}
                maxZoom={18}
                style={{ width: '100%', height: '100%' }}
                cursor={droneLayerIds.length ? 'pointer' : 'grab'}
                onLoad={() => setMapLoaded(true)}
            >
                <NavigationControl position="top-left" showCompass={false} />

                {heatmapGeoJSON.features.length > 0 && (
                    <Source id="crowd-heatmap" type="geojson" data={heatmapGeoJSON}>
                        <Layer id="crowd-heatmap-layer" type="heatmap" paint={HEATMAP_PAINT} />
                    </Source>
                )}

                {droneVisuals.map(({ drone, color, footprintRadiusMeters }) => {
                    const lat = Number(drone.latitude)
                    const lng = Number(drone.longitude)
                    if (Number.isNaN(lat) || Number.isNaN(lng)) return null
                    const ring = makeGeoCircleRing(lat, lng, footprintRadiusMeters)
                    const geojson = {
                        type: 'Feature',
                        properties: { droneId: drone.id },
                        geometry: { type: 'Polygon', coordinates: [ring] },
                    }
                    return (
                        <Source key={drone.id} id={`drone-circle-src-${drone.id}`} type="geojson" data={geojson}>
                            <Layer
                                id={`drone-circle-${drone.id}`}
                                type="fill"
                                paint={{ 'fill-color': color, 'fill-opacity': 0.28 }}
                            />
                        </Source>
                    )
                })}

                {showMarkers && droneVisuals.map(({ drone, color }) => {
                    const lat = Number(drone.latitude)
                    const lng = Number(drone.longitude)
                    if (Number.isNaN(lat) || Number.isNaN(lng)) return null
                    return (
                        <Marker
                            key={drone.id}
                            longitude={lng}
                            latitude={lat}
                            onClick={(e) => {
                                e.originalEvent.stopPropagation()
                                handleDroneClick(drone)
                                focusOnDrone(drone)
                            }}
                        >
                            <div
                                className="custom-colored-marker"
                                style={{
                                    background: color, width: 16, height: 16, borderRadius: '50%',
                                    border: '2px solid #ffffff', boxShadow: '0 2px 4px rgba(0,0,0,0.5)', cursor: 'pointer',
                                }}
                            />
                        </Marker>
                    )
                })}

                {popupDrone && (() => {
                    const visual = droneVisuals.find((v) => v.drone.id === popupDrone.id)
                    if (!visual) return null
                    const { color, densityLabel, headcount, footprintRadiusMeters, viewAngleDeg } = visual
                    return (
                        <Popup
                            longitude={Number(popupDrone.longitude)}
                            latitude={Number(popupDrone.latitude)}
                            onClose={() => setPopupDroneId(null)}
                            closeButton
                            closeOnClick={false}
                            anchor="bottom"
                        >
                            <div style={{ color: 'var(--color-text-primary)', fontSize: '13px', lineHeight: 1.6 }}>
                                <strong>{popupDrone.name}</strong> ({popupDrone.id})<br />
                                Zone: {popupDrone.zone || 'Live Stream Zone'}<br />
                                Altitude: {popupDrone.altitude ?? 100}m<br />
                                View Angle: {viewAngleDeg}°<br />
                                Coverage Radius: {Math.round(footprintRadiusMeters)}m<br />
                                People: {Math.round(headcount || 0)}<br />
                                Crowd Level: <strong style={{ color }}>{densityLabel}</strong><br />
                                Battery: {popupDrone.battery ?? 100}%
                            </div>
                        </Popup>
                    )
                })()}
            </Map>
            </div>

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
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <button
                                    className="drone-feed-modal-close"
                                    onMouseDown={(e) => e.stopPropagation()}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setIsPanelMinimized((prev) => !prev)
                                    }}
                                    title={`${isPanelMinimized ? 'Expand' : 'Minimize'} panel (M)`}
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        color: 'var(--color-text-secondary)',
                                        padding: '4px',
                                        display: 'flex',
                                    }}
                                >
                                    {isPanelMinimized ? <Maximize2 size={15} /> : <Minimize2 size={15} />}
                                </button>
                                <button
                                    className="drone-feed-modal-close"
                                    onMouseDown={(e) => e.stopPropagation()}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setSelectedDroneId(null)
                                    }}
                                    title="Close"
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
                            {!isPanelMinimized && (
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
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
