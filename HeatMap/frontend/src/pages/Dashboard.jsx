import { useEffect, useMemo, useState } from 'react'
import MapView from '../components/MapView'
import DensityStats from '../components/DensityStats'
import DroneCard from '../components/DroneCard'
import FleetFilterBar from '../components/FleetFilterBar'
import { useRegionResolver } from '../utils/useRegionResolver'

// ── Persist filter state across page refreshes ───────────────────────────────
function loadPersistedFilters() {
    try {
        const raw = localStorage.getItem('fleetFilters')
        if (!raw) return {}
        return JSON.parse(raw)
    } catch {
        return {}
    }
}

function persistFilters(filters) {
    try {
        localStorage.setItem('fleetFilters', JSON.stringify(filters))
    } catch { /* ignore */ }
}

// ── Sort comparator ───────────────────────────────────────────────────────────
function compareDrones(a, b, sortBy, maxIntensityByDrone) {
    switch (sortBy) {
        case 'name-asc':
            return a.name.localeCompare(b.name)
        case 'name-desc':
            return b.name.localeCompare(a.name)
        case 'headcount-desc':
            return (b.headcountDensity || 0) - (a.headcountDensity || 0)
        case 'battery-asc':
            return (a.battery || 0) - (b.battery || 0)
        case 'critical-first': {
            const isLive = d => d.status === 'active' || d.status === 'debug'
            const isCrit = d => isLive(d) && (d.headcountDensity || 0) >= Number(maxIntensityByDrone[d.id] ?? 100)
            return (isCrit(b) ? 1 : 0) - (isCrit(a) ? 1 : 0)
        }
        default:
            return 0
    }
}

export default function Dashboard() {
    const debugPlayback = new URLSearchParams(window.location.search).get('debugPlayback') === '1'

    // ── Core data ────────────────────────────────────────────────────────────
    const [drones, setDrones] = useState([])
    const [focusedDroneId, setFocusedDroneId] = useState(null)
    const [focusRequestId, setFocusRequestId] = useState(0)
    const [selectedDrone, setSelectedDrone] = useState(null)
    const [autoViewDrones, setAutoViewDrones] = useState(() => {
        try {
            const raw = localStorage.getItem('autoViewDrones')
            if (!raw) return {}
            const parsed = JSON.parse(raw)
            return parsed && typeof parsed === 'object' ? parsed : {}
        } catch {
            return {}
        }
    })
    const [filterName, setFilterName] = useState('')
    const [filterRegion, setFilterRegion] = useState('')
    const [maxIntensityByDrone, setMaxIntensityByDrone] = useState(() => {
        try {
            const raw = localStorage.getItem('maxIntensityByDrone')
            if (!raw) return {}
            const parsed = JSON.parse(raw)
            return parsed && typeof parsed === 'object' ? parsed : {}
        } catch {
            return {}
        }
    })

    // ── Filter / sort state (persisted to localStorage) ──────────────────────
    const persisted = loadPersistedFilters()
    const [searchQuery,    setSearchQuery]    = useState(persisted.searchQuery    || '')
    const [filterState,    setFilterState]    = useState(persisted.filterState    || 'all')
    const [filterDistrict, setFilterDistrict] = useState(persisted.filterDistrict || 'all')
    const [filterStatus,   setFilterStatus]   = useState(persisted.filterStatus   || 'all')
    const [sortBy,         setSortBy]         = useState(persisted.sortBy         || 'default')

    // ── Nominatim region resolver ─────────────────────────────────────────────────────
    const getRegion = useRegionResolver(drones)

    // ── Persist filter changes ────────────────────────────────────────────────
    useEffect(() => {
        persistFilters({ searchQuery, filterState, filterDistrict, filterStatus, sortBy })
    }, [searchQuery, filterState, filterDistrict, filterStatus, sortBy])

    // ── Persist intensity thresholds to localStorage ───────────────────────────
    useEffect(() => {
        try {
            localStorage.setItem('maxIntensityByDrone', JSON.stringify(maxIntensityByDrone))
        } catch { /* ignore */ }
    }, [maxIntensityByDrone])

    // ── Fetch drones from backend ─────────────────────────────────────────────
    useEffect(() => {
        try {
            localStorage.setItem('autoViewDrones', JSON.stringify(autoViewDrones))
        } catch {
            // Ignore storage failures.
        }
    }, [autoViewDrones])

    useEffect(() => {
        const fetchDrones = async () => {
            try {
                const res = await fetch(`http://localhost:8000/api/drones/?include_debug=${debugPlayback}`)
                if (res.ok) {
                    const data = await res.json()
                    setDrones(data.drones || [])
                }
            } catch (err) {
                console.error('Failed to load drones:', err)
            }
        }
        fetchDrones()
        const interval = setInterval(fetchDrones, 5000)
        return () => clearInterval(interval)
    }, [])

    // ── Derive per-drone isCritical ───────────────────────────────────────────
    const dronesWithMeta = useMemo(() => drones.map(drone => {
        const threshold = Number(maxIntensityByDrone[drone.id] ?? 100)
        const density   = Number(drone.headcountDensity || 0)
        const isLive    = drone.status === 'active' || drone.status === 'debug'
        const isCritical = isLive && density >= threshold
        const region    = getRegion(drone.latitude, drone.longitude)
        return { ...drone, threshold, isCritical, region }
    }), [drones, maxIntensityByDrone, getRegion])

    // ── Available states / districts (from current drone set only) ───────────
    const availableStates = useMemo(() => {
        const states = new Set()
        dronesWithMeta.forEach(d => { if (d.region.state) states.add(d.region.state) })
        return [...states].sort()
    }, [dronesWithMeta])

    const availableDistricts = useMemo(() => {
        const districts = new Set()
        dronesWithMeta.forEach(d => {
            // When a state is selected, only show districts belonging to that state
            if (filterState !== 'all' && d.region.state !== filterState) return
            if (d.region.district) districts.add(d.region.district)
        })
        return [...districts].sort()
    }, [dronesWithMeta, filterState])

    // ── Filter ────────────────────────────────────────────────────────────────
    const filteredDrones = useMemo(() => {
        return dronesWithMeta.filter(drone => {
            const nameMatch = drone.name.toLowerCase().includes(searchQuery.toLowerCase())

            const stateMatch =
                filterState === 'all' || drone.region.state === filterState

            const districtMatch =
                filterDistrict === 'all' || drone.region.district === filterDistrict

            const statusMatch =
                filterStatus === 'all' ||
                (filterStatus === 'critical' && drone.isCritical) ||
                (filterStatus === 'safe'     && !drone.isCritical)

            return nameMatch && stateMatch && districtMatch && statusMatch
        })
    }, [dronesWithMeta, searchQuery, filterState, filterDistrict, filterStatus])

    // ── Sort ──────────────────────────────────────────────────────────────────
    const sortedDrones = useMemo(() => {
        if (sortBy === 'default') return filteredDrones
        return [...filteredDrones].sort((a, b) => compareDrones(a, b, sortBy, maxIntensityByDrone))
    }, [filteredDrones, sortBy, maxIntensityByDrone])

    // ── Counts ────────────────────────────────────────────────────────────────
    const activeDrones = drones.filter(d => d.status === 'active')
    const totalDrones  = drones.length

    const handleClearAll = () => {
        setSearchQuery('')
        setFilterState('all')
        setFilterDistrict('all')
        setFilterStatus('all')
    }

    return (
        <>
            <DensityStats />
            <div className="dashboard-grid">
                <MapView
                    focusedDroneId={focusedDroneId}
                    focusRequestId={focusRequestId}
                    maxIntensityByDrone={maxIntensityByDrone}
                    setMaxIntensityByDrone={setMaxIntensityByDrone}
                    selectedDrone={selectedDrone}
                    setSelectedDrone={setSelectedDrone}
                    filterState={filterState}
                    filterDistrict={filterDistrict}
                    setFocusedDroneId={setFocusedDroneId}
                    setFocusRequestId={setFocusRequestId}
                />

                <div className="drones-panel">
                    {/* Panel header */}
                    <div className="drones-panel-header">
                        <h3 className="drones-panel-title">Fleet Status</h3>
                        <span className="drones-count" id="drone-count-badge">
                            {activeDrones.length}/{totalDrones}
                        </span>
                    </div>

                    {/* Search + filter bar */}
                    <FleetFilterBar
                        searchQuery={searchQuery}
                        onSearch={setSearchQuery}
                        filterState={filterState}
                        onStateChange={setFilterState}
                        filterDistrict={filterDistrict}
                        onDistrictChange={setFilterDistrict}
                        filterStatus={filterStatus}
                        onStatusChange={setFilterStatus}
                        sortBy={sortBy}
                        onSortChange={setSortBy}
                        availableStates={availableStates}
                        availableDistricts={availableDistricts}
                        onClearAll={handleClearAll}
                        totalCount={totalDrones}
                        filteredCount={sortedDrones.length}
                    />

                    {/* Drone list */}
                    <div className="drones-list">
                        {sortedDrones.length === 0 ? (
                            <div className="fleet-empty-state">
                                <span className="fleet-empty-icon">🛸</span>
                                <p className="fleet-empty-title">No drones match</p>
                                <p className="fleet-empty-sub">Try adjusting your search or filters</p>
                                <button className="fleet-empty-clear" onClick={handleClearAll}>
                                    Clear filters
                                </button>
                            </div>
                        ) : (
                            sortedDrones.map(drone => (
                                <DroneCard
                                    key={drone.id}
                                    drone={drone}
                                    threshold={drone.threshold}
                                    isCritical={drone.isCritical}
                                    isFocused={focusedDroneId === drone.id}
                                    isAutoView={!!autoViewDrones[drone.id]}
                                    onToggleView={(e) => {
                                        e.stopPropagation()
                                        setAutoViewDrones(prev => ({
                                            ...prev,
                                            [drone.id]: !prev[drone.id]
                                        }))
                                    }}
                                    onThresholdChange={(newThreshold) => {
                                        setMaxIntensityByDrone(prev => ({
                                            ...prev,
                                            [drone.id]: newThreshold
                                        }))
                                    }}
                                    searchTerm={searchQuery}
                                    regionLabel={
                                        drone.region.district
                                            ? `${drone.region.district}, ${drone.region.state}`
                                            : drone.region.state || drone.zone || ''
                                    }
                                    onClick={() => {
                                        setFocusedDroneId(drone.id)
                                        setFocusRequestId(prev => prev + 1)
                                        setSelectedDrone(drone)
                                    }}
                                />
                            ))
                        )}
                    </div>
                </div>
            </div>
        </>
    )
}
