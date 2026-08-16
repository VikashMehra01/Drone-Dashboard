import {
    AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Brush,
} from 'recharts'
import { useEffect, useMemo, useState } from 'react'

const COLORS = ['#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#ef4444']
const TIME_WINDOWS = ['15m', '30m', '1h', '2h', '6h']
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function parseApiTimestamp(raw) {
    if (!raw) {
        return new Date()
    }
    // Backend may return ISO timestamps without timezone (UTC-naive).
    // Append Z so browser interprets them as UTC, then render in local time.
    const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(raw)
    return new Date(hasTimezone ? raw : `${raw}Z`)
}

function formatTimelineLabel(date, windowKey) {
    const includeSeconds = windowKey === '15m' || windowKey === '30m' || windowKey === '1h'
    return date.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        ...(includeSeconds ? { second: '2-digit' } : {}),
    })
}

const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        return (
            <div style={customTooltipStyle}>
                <p style={{ margin: '0 0 5px 0', fontWeight: 600 }}>{label}</p>
                {payload.map((entry, index) => (
                    <p key={index} style={{ margin: '2px 0', color: entry.stroke || entry.fill }}>
                        {entry.name}: {entry.value}
                    </p>
                ))}
            </div>
        )
    }
    return null
}

const customTooltipStyle = {
    backgroundColor: 'var(--color-bg-card)',
    border: '1px solid var(--color-border)',
    borderRadius: '8px',
    padding: '12px',
    color: 'var(--color-text-primary)',
    fontSize: '12px',
}

export default function Analytics() {
    const [timeline, setTimeline] = useState([])
    const [drones, setDrones] = useState([])
    const [selectedWindow, setSelectedWindow] = useState('30m')
    const [selectedDrone, setSelectedDrone] = useState('all')
    const [isLoadingHistory, setIsLoadingHistory] = useState(false)
    const [historyError, setHistoryError] = useState('')

    const intervalByWindow = {
        '15m': 5,
        '30m': 5,
        '1h': 5,
        '2h': 10,
        '6h': 30,
    }

    useEffect(() => {
        const fetchDrones = async () => {
            try {
                const dronesRes = await fetch(`${API_BASE}/api/drones/`)
                if (dronesRes.ok) {
                    const dronesData = await dronesRes.json()
                    setDrones(dronesData.drones || [])
                }
            } catch (err) {
                console.error('Failed to load drone list:', err)
            }
        }

        const fetchHistory = async () => {
            try {
                setIsLoadingHistory(true)
                setHistoryError('')

                const intervalSeconds = intervalByWindow[selectedWindow] || 10
                const params = new URLSearchParams({
                    window: selectedWindow,
                    interval_seconds: String(intervalSeconds),
                })

                if (selectedDrone !== 'all') {
                    params.set('drone_id', selectedDrone)
                }

                const historyRes = await fetch(`${API_BASE}/api/density/history?${params.toString()}`)
                if (!historyRes.ok) {
                    throw new Error(`History request failed with status ${historyRes.status}`)
                }

                const history = await historyRes.json()

                if (Array.isArray(history.points)) {
                    const normalized = history.points.map((point) => {
                        const date = parseApiTimestamp(point.timestamp)
                        return {
                            timestamp: point.timestamp,
                            timeLabel: formatTimelineLabel(date, selectedWindow),
                            people: Number(point.people_count || 0),
                            density: Number(point.density_level || 0),
                        }
                    })
                    setTimeline(normalized)
                    return
                }

                const pointsByTimestamp = new Map()
                for (const series of history.series || []) {
                    for (const point of series.points || []) {
                        const key = point.timestamp
                        if (!pointsByTimestamp.has(key)) {
                            pointsByTimestamp.set(key, {
                                timestamp: key,
                                people: 0,
                                densityTotal: 0,
                                densityCount: 0,
                            })
                        }

                        const item = pointsByTimestamp.get(key)
                        item.people += Number(point.people_count || 0)
                        item.densityTotal += Number(point.density_level || 0)
                        item.densityCount += 1
                    }
                }

                const aggregated = Array.from(pointsByTimestamp.values())
                    .sort((a, b) => parseApiTimestamp(a.timestamp) - parseApiTimestamp(b.timestamp))
                    .map((item) => {
                        const date = parseApiTimestamp(item.timestamp)
                        return {
                            timestamp: item.timestamp,
                            timeLabel: formatTimelineLabel(date, selectedWindow),
                            people: item.people,
                            density: item.densityCount ? item.densityTotal / item.densityCount : 0,
                        }
                    })

                setTimeline(aggregated)

            } catch (err) {
                console.error('Failed to load history:', err)
                setHistoryError('Could not load historical data')
            } finally {
                setIsLoadingHistory(false)
            }
        }

        fetchDrones()
        fetchHistory()

        const dronesInterval = setInterval(fetchDrones, 5000)
        const historyInterval = setInterval(fetchHistory, 5000)

        return () => {
            clearInterval(dronesInterval)
            clearInterval(historyInterval)
        }
    }, [selectedWindow, selectedDrone])

    useEffect(() => {
        if (selectedDrone === 'all') {
            return
        }
        const hasDrone = drones.some((d) => d.id === selectedDrone)
        if (!hasDrone) {
            setSelectedDrone('all')
        }
    }, [drones, selectedDrone])

    const zoneDensity = useMemo(
        () => drones.map((d) => ({ zone: d.name, density: Number(d.peopleCounted || 0) })),
        [drones],
    )

    const pieData = useMemo(
        () => zoneDensity.filter((z) => z.density > 0).map((z) => ({ name: z.zone, value: z.density })),
        [zoneDensity],
    )

    return (
        <>
            <h2 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '20px' }}>
                Analytics & Reports
            </h2>
            <div className="analytics-grid">
                {/* Density Over Time */}
                <div className="chart-card full-width" id="density-timeline-chart">
                    <div className="chart-title">Crowd Density Over Time</div>
                    <div className="chart-subtitle">Zoomable people trend with 15m / 30m / 1h / 2h / 6h windows</div>
                    <div className="analytics-controls" style={{ marginBottom: '14px' }}>
                        <div className="window-switcher">
                            {TIME_WINDOWS.map((range) => (
                                <button
                                    key={range}
                                    type="button"
                                    className={`window-btn ${selectedWindow === range ? 'active' : ''}`}
                                    onClick={() => setSelectedWindow(range)}
                                >
                                    {range.toUpperCase()}
                                </button>
                            ))}
                        </div>

                        <select
                            className="analytics-select"
                            value={selectedDrone}
                            onChange={(e) => setSelectedDrone(e.target.value)}
                        >
                            <option value="all">All Drones</option>
                            {drones.map((drone) => (
                                <option key={drone.id} value={drone.id}>
                                    {drone.name} ({drone.id})
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="chart-container">
                        {historyError ? (
                            <div className="chart-empty-state">{historyError}</div>
                        ) : null}
                        {!historyError && !isLoadingHistory && timeline.length === 0 ? (
                            <div className="chart-empty-state">No history yet. Start a stream to collect points.</div>
                        ) : null}
                        <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={timeline}>
                                <defs>
                                    <linearGradient id="gradDensity" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                                    </linearGradient>
                                    <linearGradient id="gradPeople" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                                <XAxis dataKey="timeLabel" stroke="var(--color-text-muted)" fontSize={12} />
                                <YAxis stroke="var(--color-text-muted)" fontSize={12} />
                                <Tooltip content={<CustomTooltip />} />
                                <Legend />
                                <Area type="monotone" dataKey="density" name="Density"
                                    stroke="#3b82f6" fill="url(#gradDensity)" strokeWidth={2} />
                                <Area type="monotone" dataKey="people" name="People"
                                    stroke="#10b981" fill="url(#gradPeople)" strokeWidth={2} />
                                <Brush
                                    dataKey="timeLabel"
                                    height={24}
                                    stroke="#3b82f6"
                                    travellerWidth={10}
                                    fill="var(--color-bg-secondary)"
                                />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Zone Density Bar Chart */}
                <div className="chart-card" id="zone-density-chart">
                    <div className="chart-title">Zone-wise Density</div>
                    <div className="chart-subtitle">Current person count by live stream</div>
                    <div className="chart-container">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={zoneDensity} layout="vertical">
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                                <XAxis type="number" stroke="var(--color-text-muted)" fontSize={12} />
                                <YAxis dataKey="zone" type="category" stroke="var(--color-text-muted)" fontSize={11} width={100} />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="density" name="People" radius={[0, 6, 6, 0]}>
                                    {zoneDensity.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Distribution Pie Chart */}
                <div className="chart-card" id="distribution-chart">
                    <div className="chart-title">Crowd Distribution</div>
                    <div className="chart-subtitle">Percentage share across active zones</div>
                    <div className="chart-container">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={pieData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={60}
                                    outerRadius={80}
                                    paddingAngle={5}
                                    dataKey="value"
                                    label={({ name, percent }) => `${name.split(' ')[0]} ${(percent * 100).toFixed(0)}%`}
                                    labelLine={{ stroke: 'var(--color-text-muted)' }}
                                >
                                    {pieData.map((entry, index) => (
                                        <Cell
                                            key={`cell-${index}`}
                                            fill={COLORS[index % COLORS.length]}
                                            stroke="transparent"
                                        />
                                    ))}
                                </Pie>
                                <Tooltip contentStyle={customTooltipStyle} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </>
    )
}
