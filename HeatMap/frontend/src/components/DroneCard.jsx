import { useState, useEffect } from 'react'
import { Battery, BatteryFull, BatteryMedium, BatteryLow, BatteryWarning, ArrowUp, Users, Edit2, MapPin, Power, Loader2, AlertTriangle } from 'lucide-react'
import { Dialog, DialogTitle, DialogContent, DialogContentText, DialogActions, TextField, Button } from '@mui/material'
import droneIcon from '../assets/drone.png'
import { useSettings } from '../context/SettingsContext'
import { useAuth } from '../context/AuthContext'

/**
 * Highlights occurrences of `term` inside `text` by wrapping them in <mark>.
 */
function HighlightedText({ text, term }) {
    if (!term || !text) return <>{text}</>

    const lowerText = text.toLowerCase()
    const lowerTerm = term.toLowerCase()
    const parts = []
    let cursor = 0

    while (cursor < text.length) {
        const matchIdx = lowerText.indexOf(lowerTerm, cursor)
        if (matchIdx === -1) {
            parts.push(text.slice(cursor))
            break
        }
        if (matchIdx > cursor) {
            parts.push(text.slice(cursor, matchIdx))
        }
        parts.push(
            <mark key={matchIdx} className="drone-name-highlight">
                {text.slice(matchIdx, matchIdx + term.length)}
            </mark>
        )
        cursor = matchIdx + term.length
    }

    return <>{parts}</>
}

/**
 * Returns a dynamic battery icon with appropriate color based on charge level
 */
function DynamicBatteryIcon({ level }) {
    const size = 12
    const style = { display: 'inline', marginRight: 4 }
    
    if (level === undefined || level === null) return <Battery size={size} style={style} />
    
    if (level > 80) return <BatteryFull size={size} style={{ ...style, color: 'var(--color-accent-green)' }} />
    if (level > 30) return <BatteryMedium size={size} style={{ ...style, color: '#eab308' }} /> // Yellow/Amber
    if (level > 15) return <BatteryLow size={size} style={{ ...style, color: '#f97316' }} /> // Orange
    return <BatteryWarning size={size} style={{ ...style, color: 'var(--color-accent-red)' }} />
}

export default function DroneCard({
    drone,
    threshold = 100,
    isCritical = false,
    onClick,
    isFocused = false,
    isAutoView = false,
    onToggleView,
    onThresholdChange,
    searchTerm = '',
    regionLabel = '',
}) {
    const hasError = drone.status === 'error'
    const badgeClass = isCritical ? 'critical' : drone.status
    const badgeLabel = isCritical ? 'critical' : drone.status
    const { hideFleetLabels, dashboardTextSize } = useSettings()
    const { user, authFetch } = useAuth()
    const [showThresholdModal, setShowThresholdModal] = useState(false)
    const [tempThreshold, setTempThreshold] = useState(threshold)

    // ── Admin power toggle (active ⇄ idle) ───────────────────────────────────
    // active       → POST /api/auth/drones/stop/{id}    (kills the CV subprocess)
    // idle / error → POST /api/auth/drones/resume/{id}  (relaunches from saved config)
    // The DronesContext 1s poll flips the badge once the backend confirms.
    const isAdmin = user?.role === 'admin'
    const isActive = drone.status === 'active'
    const canToggle = isAdmin && ['active', 'idle', 'error'].includes(drone.status)
    const [pending, setPending] = useState(null)   // 'active' | 'idle' | null
    const busy = pending !== null
    const [toggleErr, setToggleErr] = useState('')

    useEffect(() => {
        if (!toggleErr) return
        const t = setTimeout(() => setToggleErr(''), 5000)
        return () => clearTimeout(t)
    }, [toggleErr])

    const setPowerState = async (next) => {
        // 'idle' (stop) is always allowed — a drone can look idle on the
        // dashboard while its worker is still alive reconnecting, and the user
        // needs a way to force-kill it. 'active' (resume) is a no-op if already
        // streaming.
        if (busy || (next === 'active' && isActive)) return
        const endpoint = next === 'active' ? 'resume' : 'stop'
        setPending(next)
        setToggleErr('')
        try {
            const res = await authFetch(
                `http://localhost:8000/api/auth/drones/${endpoint}/${drone.id}`,
                { method: 'POST' }
            )
            const data = await res.json().catch(() => ({}))
            if (!res.ok) setToggleErr(data.detail || `Couldn't set ${next}`)
        } catch {
            setToggleErr('Cannot reach server')
        } finally {
            setPending(null)
        }
    }

    return (
        <div
            className={`drone-card ${isFocused ? 'focused' : ''} ${isCritical ? 'critical' : ''} ${hasError ? 'errored' : ''}`}
            id={`drone-${drone.id}`}
            onClick={(drone.status === 'idle' || hasError) ? undefined : onClick}
            style={{ cursor: (drone.status === 'idle' || hasError) ? 'default' : 'pointer' }}
        >
            <div className="drone-card-top">
                <div className="drone-name">
                    <img src={droneIcon} alt="Drone" style={{ width: 16, height: 16, objectFit: 'contain' }} />
                    <HighlightedText text={drone.name} term={searchTerm} />
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            setTempThreshold(threshold)
                            setShowThresholdModal(true)
                        }}
                        title="Set Crowd Threshold"
                        style={{
                            background: 'var(--color-bg-secondary)',
                            border: '1px solid var(--color-border)',
                            color: 'var(--color-text-secondary)',
                            borderRadius: '4px',
                            padding: '4px 8px',
                            fontSize: '11px',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px'
                        }}
                    >
                        <Edit2 size={11} />
                        Crowd Threshold
                    </button>
                    <span className={`drone-status-badge ${badgeClass}`}>
                        {badgeLabel}
                    </span>
                </div>
            </div>

            {/* Stream error — source unreachable / refused; worker has exited */}
            {hasError && (
                <div className="drone-card-error">
                    <AlertTriangle size={13} />
                    <span>{drone.error || 'Stream unreachable — the drone feed could not be opened.'}</span>
                </div>
            )}

            {/* Region label — shown when available */}
            {regionLabel && drone.status !== 'idle' && !hasError && (
                <div className="drone-region-label">
                    <MapPin size={10} />
                    {regionLabel}
                </div>
            )}

            <div className="drone-card-stats">
                <div className="drone-stat">
                    <div className="drone-stat-value">
                        <DynamicBatteryIcon level={drone.battery} />
                        {drone.battery}%
                    </div>
                    {!hideFleetLabels && <div className="drone-stat-label">Battery</div>}
                </div>
                <div className="drone-stat">
                    <div className="drone-stat-value">
                        <ArrowUp size={12} style={{ display: 'inline', marginRight: 4 }} />
                        {drone.altitude}m
                    </div>
                    {!hideFleetLabels && <div className="drone-stat-label">Altitude</div>}
                </div>
                <div className="drone-stat">
                    <div className="drone-stat-value">
                        <Users size={12} style={{ display: 'inline', marginRight: 4 }} />
                        {threshold}
                    </div>
                    {!hideFleetLabels && <div className="drone-stat-label">Crowd Threshold</div>}
                </div>
            </div>

            {canToggle && (
                <div
                    className="drone-power"
                    onClick={(e) => e.stopPropagation()}
                >
                    <span className="drone-power-label">
                        <Power size={11} />
                        Power
                    </span>
                    <div className="drone-power-seg" role="group" aria-label="Drone power state">
                        <button
                            type="button"
                            className={`drone-power-seg-btn ${isActive ? 'on-active' : ''}`}
                            aria-pressed={isActive}
                            disabled={busy || isActive}
                            title={isActive ? 'Streaming' : 'Start / restart this drone'}
                            onClick={() => setPowerState('active')}
                        >
                            {pending === 'active'
                                ? <Loader2 size={11} className="spin-icon" />
                                : <span className="drone-power-dot active" />}
                            Active
                        </button>
                        <button
                            type="button"
                            className={`drone-power-seg-btn ${!isActive ? 'on-idle' : ''}`}
                            aria-pressed={!isActive}
                            disabled={busy}
                            title={isActive ? 'Stop this drone' : 'Force-stop (kills any lingering worker)'}
                            onClick={() => setPowerState('idle')}
                        >
                            {pending === 'idle'
                                ? <Loader2 size={11} className="spin-icon" />
                                : <span className="drone-power-dot idle" />}
                            Idle
                        </button>
                    </div>
                </div>
            )}

            {toggleErr && <div className="drone-power-error">{toggleErr}</div>}

            <Dialog
                open={showThresholdModal} 
                onClose={() => setShowThresholdModal(false)}
                PaperProps={{
                    sx: {
                        background: 'var(--color-bg-card)',
                        color: 'var(--color-text-primary)',
                        border: '1px solid var(--color-border)',
                        borderRadius: '12px',
                        boxShadow: 'var(--glass-shadow)',
                    }
                }}
            >
                <DialogTitle sx={{ fontWeight: 600 }}>Set Crowd Threshold</DialogTitle>
                <DialogContent>
                    <DialogContentText sx={{ color: 'var(--color-text-secondary)', marginBottom: '16px', fontSize: '14px' }}>
                        Enter the maximum expected crowd threshold for <strong style={{color: 'var(--color-text-primary)'}}>{drone.name}</strong>. Alerts will trigger if exceeded.
                    </DialogContentText>
                    <TextField
                        autoFocus
                        margin="dense"
                        type="number"
                        fullWidth
                        variant="outlined"
                        value={tempThreshold}
                        onChange={(e) => setTempThreshold(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                const val = Number(tempThreshold)
                                if (!isNaN(val) && val > 0) {
                                    onThresholdChange && onThresholdChange(val)
                                    setShowThresholdModal(false)
                                }
                            }
                        }}
                    />
                </DialogContent>
                <DialogActions sx={{ padding: '16px', paddingTop: 0 }}>
                    <Button 
                        onClick={() => setShowThresholdModal(false)}
                        sx={{ color: 'var(--color-text-secondary)', textTransform: 'none', fontWeight: 500 }}
                    >
                        Cancel
                    </Button>
                    <Button 
                        onClick={() => {
                            const val = Number(tempThreshold)
                            if (!isNaN(val) && val > 0) {
                                onThresholdChange && onThresholdChange(val)
                                setShowThresholdModal(false)
                            }
                        }}
                        variant="contained"
                        sx={{ 
                            background: 'var(--color-accent-blue)', 
                            textTransform: 'none', 
                            fontWeight: 600,
                            boxShadow: '0 4px 6px -1px rgba(59, 130, 246, 0.2)',
                            '&:hover': {
                                background: '#2563eb'
                            }
                        }}
                    >
                        Save Limit
                    </Button>
                </DialogActions>
            </Dialog>
        </div>
    )
}
