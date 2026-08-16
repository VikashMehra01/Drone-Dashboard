import { useEffect, useRef, useState } from 'react'
import { Search, X, SlidersHorizontal } from 'lucide-react'
import { Select, MenuItem } from '@mui/material'

/**
 * FleetFilterBar — search input, "Filters" popup trigger, active-filter pills.
 *
 * The popup state is managed internally so the popup can anchor correctly
 * relative to the filter bar itself (no cross-component positioning issues).
 */
export default function FleetFilterBar({
  // search
  searchQuery,
  onSearch,
  // filters
  filterState,
  onStateChange,
  filterDistrict,
  onDistrictChange,
  filterStatus,
  onStatusChange,
  sortBy,
  onSortChange,
  // option lists
  availableStates,
  availableDistricts,
  // actions
  onClearAll,
  totalCount,
  filteredCount,
}) {
  const [popupOpen, setPopupOpen] = useState(false)
  const popupRef   = useRef(null)
  const triggerRef = useRef(null)

  const hasActiveFilters =
    !!searchQuery ||
    filterState    !== 'all' ||
    filterDistrict !== 'all' ||
    filterStatus   !== 'all'

  // Count of filter/sort selections that are non-default (for badge)
  const activeFilterCount = [
    filterState    !== 'all',
    filterDistrict !== 'all',
    filterStatus   !== 'all',
    sortBy         !== 'default',
  ].filter(Boolean).length

  // Build dismissible pill list
  const pills = []
  if (filterState !== 'all')
    pills.push({
      label: filterState,
      onRemove: () => { onStateChange('all'); onDistrictChange('all') },
    })
  if (filterDistrict !== 'all')
    pills.push({ label: filterDistrict, onRemove: () => onDistrictChange('all') })
  if (filterStatus !== 'all')
    pills.push({
      label: filterStatus === 'critical' ? '⚠ Critical' : '✓ Safe',
      onRemove: () => onStatusChange('all'),
    })
  if (searchQuery)
    pills.push({ label: `"${searchQuery}"`, onRemove: () => onSearch('') })

  // Close popup on Escape key
  useEffect(() => {
    if (!popupOpen) return
    const handler = (e) => { if (e.key === 'Escape') setPopupOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [popupOpen])

  // Close popup on click outside (but not on the trigger button itself)
  useEffect(() => {
    if (!popupOpen) return
    const handler = (e) => {
      // Ignore if element was removed from DOM
      if (!document.contains(e.target)) return;

      // Ignore clicks outside the main React root (e.g., inside MUI Portals like Select dropdowns)
      const rootElement = document.getElementById('root');
      if (rootElement && !rootElement.contains(e.target)) return;

      if (
        popupRef.current   && !popupRef.current.contains(e.target) &&
        triggerRef.current && !triggerRef.current.contains(e.target)
      ) {
        setPopupOpen(false)
      }
    }
    const id = setTimeout(() => document.addEventListener('mousedown', handler), 60)
    return () => {
      clearTimeout(id)
      document.removeEventListener('mousedown', handler)
    }
  }, [popupOpen])

  return (
    <div className="fleet-filter-bar">

      {/* ── Top row: search + Filters button ────────────────────── */}
      <div className="fleet-search-row">
        {/* Search */}
        <div className="fleet-search-wrapper">
          <Search size={14} className="fleet-search-icon" />
          <input
            id="fleet-search-input"
            type="text"
            className="fleet-search-input"
            placeholder="Search drones by name…"
            value={searchQuery}
            onChange={e => onSearch(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          {searchQuery && (
            <button
              className="fleet-search-clear"
              onClick={() => onSearch('')}
              aria-label="Clear search"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Filters trigger button */}
        <button
          id="fleet-filter-toggle"
          ref={triggerRef}
          className={`fleet-filter-btn${popupOpen ? ' active' : ''}`}
          onClick={() => setPopupOpen(o => !o)}
          aria-label="Filters & Sort"
          title="Filters & Sort"
        >
          <SlidersHorizontal size={13} />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span className="fleet-filter-badge">{activeFilterCount}</span>
          )}
        </button>
      </div>

      {/* ── Active filter pills ─────────────────────────────────── */}
      {(pills.length > 0 || filteredCount < totalCount) && (
        <div className="fleet-pills-row">
          <span className="fleet-filtered-count">
            <span className={filteredCount < totalCount ? 'count-amber' : 'count-blue'}>
              {filteredCount}
            </span>
            {' '}of {totalCount}
          </span>

          <div className="fleet-pills">
            {pills.map((pill, idx) => (
              <span key={idx} className="filter-pill">
                {pill.label}
                <button
                  className="filter-pill-remove"
                  onClick={pill.onRemove}
                  aria-label={`Remove filter ${pill.label}`}
                >
                  <X size={9} />
                </button>
              </span>
            ))}
          </div>

          {hasActiveFilters && (
            <button className="filter-clear-btn" onClick={onClearAll}>
              Clear all
            </button>
          )}
        </div>
      )}

      {/* ── Filter popup (anchored to fleet-filter-bar) ─────────── */}
      {popupOpen && (
        <div ref={popupRef} className="filter-popup" role="dialog" aria-label="Filters & Sort">
          {/* Header */}
          <div className="filter-popup-header">
            <span className="filter-popup-title">
              <SlidersHorizontal size={13} />
              Filters &amp; Sort
            </span>
            <button
              className="filter-popup-close"
              onClick={() => setPopupOpen(false)}
              aria-label="Close filters"
            >
              <X size={14} />
            </button>
          </div>

          {/* Body */}
          <div className="filter-popup-body">
            <label className="filter-popup-label" htmlFor="fp-state">State</label>
            <Select
              id="fp-state"
              className="filter-popup-select"
              value={filterState}
              onChange={e => { onStateChange(e.target.value); onDistrictChange('all') }}
              size="small"
              fullWidth
            >
              <MenuItem value="all">All States</MenuItem>
              {availableStates.map(s => (
                <MenuItem key={s} value={s}>{s}</MenuItem>
              ))}
            </Select>

            <label className="filter-popup-label" htmlFor="fp-district">District</label>
            <Select
              id="fp-district"
              className="filter-popup-select"
              value={filterDistrict}
              onChange={e => onDistrictChange(e.target.value)}
              size="small"
              fullWidth
            >
              <MenuItem value="all">All Districts</MenuItem>
              {availableDistricts.map(d => (
                <MenuItem key={d} value={d}>{d}</MenuItem>
              ))}
            </Select>

            <label className="filter-popup-label" htmlFor="fp-status">Zone Status</label>
            <Select
              id="fp-status"
              className="filter-popup-select"
              value={filterStatus}
              onChange={e => onStatusChange(e.target.value)}
              size="small"
              fullWidth
            >
              <MenuItem value="all">All Zones</MenuItem>
              <MenuItem value="critical">⚠ Critical</MenuItem>
              <MenuItem value="safe">✓ Safe</MenuItem>
            </Select>

            <label className="filter-popup-label" htmlFor="fp-sort">Sort By</label>
            <Select
              id="fp-sort"
              className="filter-popup-select filter-popup-select--sort"
              value={sortBy}
              onChange={e => onSortChange(e.target.value)}
              size="small"
              fullWidth
            >
              <MenuItem value="default">Default</MenuItem>
              <MenuItem value="name-asc">Name A → Z</MenuItem>
              <MenuItem value="name-desc">Name Z → A</MenuItem>
              <MenuItem value="headcount-desc">Headcount ↓</MenuItem>
              <MenuItem value="battery-asc">Battery ↑</MenuItem>
              <MenuItem value="critical-first">Critical First</MenuItem>
            </Select>
          </div>

          {/* Footer */}
          {hasActiveFilters && (
            <div className="filter-popup-footer">
              <button
                className="filter-popup-clear"
                onClick={() => { onClearAll(); setPopupOpen(false) }}
              >
                Clear All Filters
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
