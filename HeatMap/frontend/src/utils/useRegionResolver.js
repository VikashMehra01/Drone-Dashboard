import { useState, useEffect, useRef } from 'react'

const NOMINATIM_BASE = 'https://nominatim.openstreetmap.org/reverse'

// Bump this number whenever the extraction logic changes to discard stale entries
const CACHE_VERSION = 4

// Module-level cache — survives re-renders and component unmounts
const _cache = new Map()

/**
 * Resolves Indian state + district from (lat, lng) using Nominatim reverse geocoding.
 * Results are cached module-wide so each coordinate is fetched only once.
 * Respects Nominatim's 1 request/second rate limit.
 *
 * @param {Array} drones - array of drone objects with .latitude and .longitude
 * @returns {Function} getRegion(lat, lng) → { state: string, district: string }
 */
export function useRegionResolver(drones) {
  // Incrementing tick is used purely to trigger re-renders when the cache populates
  const [, setTick] = useState(0)
  const pendingRef  = useRef(new Set())
  const isMounted   = useRef(true)

  useEffect(() => {
    isMounted.current = true
    return () => { isMounted.current = false }
  }, [])

  useEffect(() => {
    if (!drones || drones.length === 0) return

    // Collect unique coords that haven't been fetched or are in-flight
    const toFetch = drones
      .map(d => ({
        key: `v${CACHE_VERSION}:${d.latitude},${d.longitude}`,
        lat: d.latitude,
        lng: d.longitude,
      }))
      .filter(({ key }) => !_cache.has(key) && !pendingRef.current.has(key))

    if (toFetch.length === 0) return

    toFetch.forEach(({ key }) => pendingRef.current.add(key))

    let cancelled = false

    ;(async () => {
      for (let i = 0; i < toFetch.length; i++) {
        if (cancelled) break
        const { key, lat, lng } = toFetch[i]

        // Skip uninitialized (0,0) coordinates
        if (lat === 0 && lng === 0) {
          _cache.set(key, { state: '', district: '' })
          pendingRef.current.delete(key)
          continue
        }

        try {
          const res = await fetch(
            // zoom=10 gives district-level results for India (admin_level 6)
            `${NOMINATIM_BASE}?lat=${lat}&lon=${lng}&format=json&addressdetails=1&zoom=10`,
            { headers: { 'Accept-Language': 'en' } }
          )
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const data = await res.json()
          const addr = data.address || {}

          // Indian addresses: Nominatim may use different fields for states/UTs.
          // For NCT Delhi and other union territories, addr.state can be absent;
          // fall back through multiple OSM fields that carry the top-level region.
          const state =
            addr.state ||
            addr.state_district ||
            addr['ISO3166-2-lvl4'] ||   // e.g. "IN-DL" – filter below
            addr.region ||
            ''

          // If the resolved "state" looks like an ISO code, use state_district instead
          let cleanState = /^[A-Z]{2}-[A-Z]{2,}$/.test(state)
            ? addr.state_district || addr.region || ''
            : state

          let district =
            addr.county ||
            addr.city_district ||
            addr.district ||
            addr.state_district ||
            addr.city ||
            addr.town ||
            addr.village ||
            addr.suburb ||
            ''

          // Special case for Delhi: Ensure state is "Delhi" and map district correctly
          if (
              state === 'IN-DL' || 
              String(cleanState).toLowerCase().includes('delhi') || 
              String(district).toLowerCase().includes('delhi')
          ) {
              cleanState = 'Delhi'
              if (district.toLowerCase() === 'delhi' || district === '') {
                  district = addr.county || addr.city_district || addr.city || addr.suburb || 'New Delhi'
              }
          }

          _cache.set(key, { state: cleanState, district })
        } catch {
          // On any error, cache an empty record so we don't retry forever
          _cache.set(key, { state: '', district: '' })
        }

        pendingRef.current.delete(key)

        // Trigger a re-render so filter dropdowns update
        if (isMounted.current && !cancelled) {
          setTick(t => t + 1)
        }

        // Nominatim rate limit: max 1 request / second
        if (i < toFetch.length - 1 && !cancelled) {
          await new Promise(r => setTimeout(r, 1150))
        }
      }
    })()

    return () => { cancelled = true }
  }, [drones])

  /**
   * Synchronously look up the cached region for a given coordinate.
   * Returns { state: '', district: '' } while the fetch is still in progress.
   */
  return function getRegion(lat, lng) {
    return _cache.get(`v${CACHE_VERSION}:${lat},${lng}`) || { state: '', district: '' }
  }
}
