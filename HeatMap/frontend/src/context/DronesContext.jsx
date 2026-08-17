import { createContext, useContext, useState, useEffect, useRef } from 'react'

const DronesContext = createContext(null)

const POLL_INTERVAL_MS = 1000

/**
 * One shared poll of /api/drones/ and /api/density/current, used by every
 * component that needs live fleet data (Sidebar, Dashboard, MapView,
 * DensityStats, DroneFeed) — instead of each running its own independent
 * setInterval against the same two endpoints. Before this, being on the
 * Dashboard route alone meant 4 separate concurrent /api/drones/ polls
 * (3s/5s/1s/1s) plus 2 separate /api/density/current polls (1s/1s).
 */
export function DronesProvider({ children }) {
    const [drones, setDrones] = useState([])
    const [currentDensity, setCurrentDensity] = useState({ current_data: null, active_streams: {} })
    const [isOnline, setIsOnline] = useState(true)
    const [loading, setLoading] = useState(true)

    // Read once, like every migrated component used to — debugPlayback isn't
    // expected to change without a full page load.
    const debugPlaybackRef = useRef(new URLSearchParams(window.location.search).get('debugPlayback') === '1')

    useEffect(() => {
        let cancelled = false

        const poll = async () => {
            const [dronesResult, densityResult] = await Promise.allSettled([
                fetch(`http://localhost:8000/api/drones/?include_debug=${debugPlaybackRef.current}`),
                fetch('http://localhost:8000/api/density/current'),
            ])

            if (cancelled) return

            if (dronesResult.status === 'fulfilled' && dronesResult.value.ok) {
                setIsOnline(true)
                try {
                    const data = await dronesResult.value.json()
                    setDrones(data.drones || [])
                } catch {
                    // keep the previous drones list on a parse failure
                }
            } else {
                setIsOnline(false)
            }

            if (densityResult.status === 'fulfilled' && densityResult.value.ok) {
                try {
                    setCurrentDensity(await densityResult.value.json())
                } catch {
                    // keep the previous density snapshot on a parse failure
                }
            }

            setLoading(false)
        }

        poll()
        const interval = setInterval(poll, POLL_INTERVAL_MS)
        return () => { cancelled = true; clearInterval(interval) }
    }, [])

    return (
        <DronesContext.Provider value={{ drones, currentDensity, isOnline, loading }}>
            {children}
        </DronesContext.Provider>
    )
}

export function useDrones() {
    const ctx = useContext(DronesContext)
    if (!ctx) throw new Error('useDrones must be used inside <DronesProvider>')
    return ctx
}
