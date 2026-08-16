import { useState } from 'react'
import { Battery, BatteryFull, BatteryMedium, BatteryLow, BatteryWarning, ArrowUp, Users, Edit2, MapPin, Plane } from 'lucide-react'
import { Dialog, DialogTitle, DialogContent, DialogContentText, DialogActions, TextField, Button } from '@mui/material'
import droneIcon from '../assets/drone.png'
import { useSettings } from '../context/SettingsContext'

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
    const badgeClass = isCritical ? 'critical' : drone.status
    const badgeLabel = isCritical ? 'critical' : drone.status
    const { hideFleetLabels, dashboardTextSize } = useSettings()
    const [showThresholdModal, setShowThresholdModal] = useState(false)
    const [tempThreshold, setTempThreshold] = useState(threshold)

    return (
        <div
            className={`drone-card ${isFocused ? 'focused' : ''} ${isCritical ? 'critical' : ''}`}
            id={`drone-${drone.id}`}
            onClick={drone.status === 'idle' ? undefined : onClick}
            style={{ cursor: drone.status === 'idle' ? 'default' : 'pointer' }}
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

            {/* Region label — shown when available */}
            {regionLabel && drone.status !== 'idle' && (
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
