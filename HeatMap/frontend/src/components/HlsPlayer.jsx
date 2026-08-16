/**
 * HlsPlayer.jsx
 *
 * A React component that plays an HLS stream (.m3u8 playlist) using hls.js.
 * Falls back to native <video> HLS support on Safari.
 *
 * Props:
 *   src        {string}   URL to the .m3u8 playlist
 *   className  {string}   CSS class applied to the <video> element
 *   autoPlay   {boolean}  Auto-play on mount (default true)
 *   muted      {boolean}  Muted (default true — required for autoPlay in most browsers)
 *   loop       {boolean}  Loop (default false — live streams don't loop)
 */
import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { Radio, RefreshCw, Loader } from 'lucide-react'

export default function HlsPlayer({
    src,
    className = '',
    autoPlay = true,
    muted = true,
    loop = false,
}) {
    const videoRef = useRef(null)
    const hlsRef = useRef(null)
    const [status, setStatus] = useState('loading') // 'loading' | 'playing' | 'error'
    const [errorMsg, setErrorMsg] = useState('')

    const initPlayer = () => {
        const video = videoRef.current
        if (!video || !src) return

        setStatus('loading')
        setErrorMsg('')

        // Destroy any existing hls instance before re-initialising
        if (hlsRef.current) {
            hlsRef.current.destroy()
            hlsRef.current = null
        }

        if (Hls.isSupported()) {
            const hls = new Hls({
                lowLatencyMode: true,       // minimise live delay
                backBufferLength: 0,        // don't retain past segments
                maxBufferLength: 4,         // keep playback buffer small
                liveSyncDurationCount: 2,   // stay close to live edge
            })
            hlsRef.current = hls

            hls.loadSource(src)
            hls.attachMedia(video)

            hls.on(Hls.Events.MANIFEST_PARSED, () => {
                setStatus('playing')
                if (autoPlay) {
                    video.play().catch(() => {
                        // Autoplay blocked by browser policy — user must interact
                    })
                }
            })

            hls.on(Hls.Events.ERROR, (_, data) => {
                if (data.fatal) {
                    setStatus('error')
                    setErrorMsg(
                        data.type === Hls.ErrorTypes.NETWORK_ERROR
                            ? 'Network error — stream may not be ready yet'
                            : `Playback error: ${data.details}`
                    )
                    hls.destroy()
                    hlsRef.current = null
                }
            })
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            // Safari has native HLS support
            video.src = src
            video.addEventListener('loadedmetadata', () => {
                setStatus('playing')
                if (autoPlay) video.play().catch(() => {})
            }, { once: true })
            video.addEventListener('error', () => {
                setStatus('error')
                setErrorMsg('Could not load HLS stream')
            }, { once: true })
        } else {
            setStatus('error')
            setErrorMsg('HLS is not supported in this browser')
        }
    }

    useEffect(() => {
        initPlayer()
        return () => {
            if (hlsRef.current) {
                hlsRef.current.destroy()
                hlsRef.current = null
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [src])

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            {/* The actual video element — always in DOM so hls.js can attach */}
            <video
                ref={videoRef}
                className={className}
                muted={muted}
                loop={loop}
                playsInline
                style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    display: status === 'playing' ? 'block' : 'none',
                }}
            />

            {/* Loading overlay */}
            {status === 'loading' && (
                <div style={overlayStyle}>
                    <Loader
                        size={36}
                        style={{ color: 'var(--color-accent-green)', animation: 'spin 1s linear infinite' }}
                    />
                    <span style={labelStyle}>Connecting to live stream…</span>
                    <span style={subStyle}>{src}</span>
                </div>
            )}

            {/* Error overlay with retry */}
            {status === 'error' && (
                <div style={overlayStyle}>
                    <Radio size={36} style={{ color: 'var(--color-accent-amber)' }} />
                    <span style={{ ...labelStyle, color: 'var(--color-accent-amber)' }}>Stream unavailable</span>
                    <span style={subStyle}>{errorMsg}</span>
                    <button
                        onClick={initPlayer}
                        style={{
                            marginTop: 10,
                            padding: '6px 16px',
                            background: 'var(--color-bg-card)',
                            border: '1px solid var(--color-border)',
                            borderRadius: 6,
                            color: 'var(--color-text-secondary)',
                            cursor: 'pointer',
                            fontSize: 12,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                        }}
                    >
                        <RefreshCw size={13} />
                        Retry
                    </button>
                </div>
            )}

            {/* Live badge shown while playing */}
            {status === 'playing' && (
                <div
                    style={{
                        position: 'absolute',
                        top: 8,
                        left: 8,
                        background: 'rgba(16,185,129,0.9)',
                        color: '#fff',
                        fontSize: 11,
                        fontWeight: 700,
                        padding: '2px 8px',
                        borderRadius: 4,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 5,
                        letterSpacing: '0.05em',
                    }}
                >
                    <span
                        style={{
                            width: 7,
                            height: 7,
                            borderRadius: '50%',
                            background: 'var(--color-text-primary)',
                            animation: 'pulse 1.5s infinite',
                            display: 'inline-block',
                        }}
                    />
                    LIVE
                </div>
            )}
        </div>
    )
}

// ── Shared overlay styles ─────────────────────────────────────────────────────
const overlayStyle = {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'var(--color-bg-secondary)',
    gap: 8,
    padding: '16px 12px',
}

const labelStyle = {
    fontSize: 13,
    fontWeight: 700,
    color: 'var(--color-text-primary)',
    textAlign: 'center',
}

const subStyle = {
    fontSize: 10,
    color: 'var(--color-text-secondary)',
    wordBreak: 'break-all',
    maxWidth: 280,
    textAlign: 'center',
}
