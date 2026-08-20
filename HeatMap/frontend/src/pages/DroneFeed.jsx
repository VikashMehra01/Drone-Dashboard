import { useState, useMemo, useEffect } from 'react'
import { Video, MapPin, Battery, Users, Activity, BarChart3, Radio } from 'lucide-react'
import HlsPlayer from '../components/HlsPlayer'
import { useDrones } from '../context/DronesContext'

function getVideoNameFromUrl(url) {
    try {
        const parsed = new URL(url)
        return parsed.pathname.split('/').pop() || ''
    } catch {
        return (url || '').split('/').pop() || ''
    }
}

/**
 * Returns true for protocols browsers cannot play natively (RTSP, RTMP …).
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

function getHeatColor(value, maxIntensity) {
    const ratio = Math.min(value / maxIntensity, 1.0)
    const stops = [
        { pos: 0.0, r: 21, g: 101, b: 192 },
        { pos: 0.25, r: 76, g: 175, b: 80 },
        { pos: 0.5, r: 255, g: 235, b: 59 },
        { pos: 0.75, r: 255, g: 152, b: 0 },
        { pos: 1.0, r: 244, g: 67, b: 54 },
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

export default function DroneFeed() {
    const { drones, currentDensity } = useDrones()
    const maxIntensity = 100
    const debugPlayback = new URLSearchParams(window.location.search).get('debugPlayback') === '1'
    // Counts how many currentDensity updates have been seen, for the
    // "Frame N" display below — a genuine subscription (depends on update
    // sequence, not just the current value), so it's the one thing here that
    // stays in an effect rather than the useMemo.
    const [frameIndex, setFrameIndex] = useState(0)
    useEffect(() => {
        // Not derivable via useMemo: this counts *how many* updates have
        // occurred, not a function of currentDensity's current value.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setFrameIndex((prev) => prev + 1)
    }, [currentDensity])

    // drones and currentDensity both come from the shared DronesContext poll
    // (one /api/drones/ + /api/density/current fetch per second, shared with
    // Sidebar/Dashboard/MapView/DensityStats) — this is a pure derivation of
    // that, so no effect/fetch of its own is needed.
    const { liveData, streamMetricsByVideo } = useMemo(() => {
        const streams = currentDensity.active_streams || {}
        const byVideo = {}
        let totalPoints = 0
        let totalHeadcount = 0

        Object.entries(streams).forEach(([source, stream]) => {
            const videoName = getVideoNameFromUrl(source)
            if (!videoName) return
            byVideo[videoName] = stream
            totalPoints += Number(stream?.points_count || 0)
            totalHeadcount += Number(stream?.headcount || 0)
        })

        return {
            streamMetricsByVideo: byVideo,
            liveData: {
                points_count: totalPoints,
                headcount: totalHeadcount,
                timestamp: currentDensity.current_data?.timestamp || null,
            },
        }
    }, [currentDensity])

    const frameData = {
        frame_index: frameIndex,
        headcount: liveData.points_count || 0,
        headcount_density: liveData.headcount || 0,
    }

    return (
        <>
            {drones.length === 0 && (
                <div className="feed-card" style={{ padding: 16, marginBottom: 16 }}>
                    No active live streams found. Start the stream processor to publish live data.
                    {import.meta.env.DEV && !debugPlayback && (
                        <span style={{ display: 'block', marginTop: 8, color: 'var(--color-text-secondary)' }}>
                            For quick UI debugging, open this page with <strong>?debugPlayback=1</strong>.
                        </span>
                    )}
                </div>
            )}
            <div className="feed-grid">
                {drones.map((drone) => {
                    const isLive = drone.status === 'active' || drone.status === 'debug'
                    const streamMetrics = streamMetricsByVideo[getVideoNameFromUrl(drone.video_url)] || {}
                    const dronePeakPoints = Number(streamMetrics.points_count ?? drone.peopleCounted ?? 0)
                    const droneDensity = Number(streamMetrics.headcount ?? drone.headcountDensity ?? 0)
                    const headcount = Math.round(dronePeakPoints)
                    const loopVideo = streamMetrics.loop_video !== false

                    return (
                        <div key={drone.id} className="feed-card" id={`feed-${drone.id}`}>
                            <div className="feed-video">
                                {drone.status === 'active' && (
                                    <div className="feed-live-badge">
                                        <span className="feed-live-dot" />
                                        Live
                                    </div>
                                )}
                                {drone.status === 'debug' && (
                                    <div className="feed-live-badge" style={{ background: '#7c3aed', color: '#ede9fe' }}>
                                        Debug Playback
                                    </div>
                                )}
                                {(drone.status === 'active' || drone.status === 'debug') ? (
                                    // Priority 1: backend provided an HLS URL (RTSP/RTMP via MediaMTX)
                                    drone.hls_url ? (
                                        <HlsPlayer
                                            src={drone.hls_url}
                                            className="feed-video-player"
                                        />
                                    // Priority 2: source is itself an HLS playlist (HTTP .m3u8)
                                    ) : isHlsUrl(drone.video_url) ? (
                                        <HlsPlayer
                                            src={drone.video_url}
                                            className="feed-video-player"
                                        />
                                    // Priority 3: non-playable protocol without MediaMTX proxy
                                    ) : isNonPlayableUrl(drone.video_url) ? (
                                        <div className="feed-video-placeholder" style={{ gap: 10, padding: '24px 16px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <Radio size={40} style={{ color: 'var(--color-accent-green)', animation: 'pulse 1.5s infinite' }} />
                                                <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary)' }}>
                                                    {drone.name} — Live Connection
                                                </span>
                                            </div>
                                            <span style={{ fontSize: 11, color: 'var(--color-text-muted)', wordBreak: 'break-all', maxWidth: 280, textAlign: 'center' }}>
                                                {drone.video_url}
                                            </span>
                                            <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginTop: 4 }}>
                                                Non-browser protocol. Backend is relaying metrics.
                                            </span>
                                        </div>
                                    // Priority 4: local file or HTTP MJPEG — try native <video>
                                    ) : (
                                        <video
                                            className="feed-video-player"
                                            autoPlay
                                            muted
                                            loop={loopVideo}
                                            playsInline
                                        >
                                            <source src={drone.video_url} type="video/mp4" />
                                            Your browser does not support the video tag.
                                        </video>
                                    )
                                ) : (
                                    <div className="feed-video-placeholder">
                                        <Video />
                                        <span>
                                            {drone.status === 'idle'
                                                ? `${drone.name} — Standby`
                                                : `${drone.name} — Offline`}
                                        </span>
                                    </div>
                                )}
                            </div>
                            <div className="feed-info">
                                <div className="feed-info-header">
                                    <span className="feed-drone-name">{drone.name}</span>
                                    <span className={`drone-status-badge ${drone.status}`}>
                                        {drone.status}
                                    </span>
                                </div>
                                <div className="feed-location">
                                    <MapPin size={12} style={{ display: 'inline', marginRight: 4 }} />
                                    {drone.zone || 'Standby Zone'} 
                                    {drone.latitude && drone.longitude ? ` · ${Number(drone.latitude).toFixed(4)}, ${Number(drone.longitude).toFixed(4)}` : ' · Location Unavailable'}
                                </div>
                                <div className="feed-meta">
                                    <div className="feed-meta-item">
                                        <Battery size={14} />
                                        {drone.battery ?? 100}%
                                    </div>
                                    <div className="feed-meta-item">
                                        <Users size={14} />
                                        {headcount} detected
                                    </div>
                                </div>

                                {isLive && (
                                    <div className="live-csv-panel" style={{ marginTop: 12 }}>
                                        <h4 style={{ fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, color: 'var(--color-text-secondary)' }}>
                                            <BarChart3 size={13} />
                                            Detection Data — Frame {frameData.frame_index || 0}
                                        </h4>
                                        <div className="csv-data-grid">
                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Frame</span>
                                                <span className="csv-stat-value" style={{ fontSize: 15 }}>{frameData.frame_index}</span>
                                            </div>
                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Peak Pts</span>
                                                <span className="csv-stat-value" style={{ fontSize: 15 }}>{dronePeakPoints}</span>
                                            </div>
                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Density</span>
                                                <span className="csv-stat-value" style={{ fontSize: 15, color: getHeatColor(droneDensity, maxIntensity) }}>
                                                    {Number(droneDensity || 0).toFixed(1)}
                                                </span>
                                            </div>
                                            <div className="csv-stat">
                                                <span className="csv-stat-label">Intensity</span>
                                                <span className="csv-stat-value" style={{ fontSize: 15 }}>
                                                    {(Number(droneDensity || 0) / maxIntensity * 100).toFixed(0)}%
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </>
    )
}
