import { useEffect, useMemo, useState } from 'react'
import { MapContainer, Marker, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet.heat'
import 'leaflet/dist/leaflet.css'
import { DEFAULT_MAX_EXPECTED_PEOPLE, droneHubPosition, hotspotData } from './mapData'

const CARTO_TILE_URL_LIGHT = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
const CARTO_TILE_URL_DARK = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const DEFAULT_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

function configureDefaultMarkerIcons() {
  // Leaflet's default marker icon assets aren't always resolved by bundlers.
  // Use CDN-hosted icons to keep markers visible in Vite/React builds.
  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
    iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  })
}

configureDefaultMarkerIcons()

function getIntensityFromPeopleCount(peopleCount, maxExpectedPeople) {
  if (maxExpectedPeople <= 0) {
    return 0;
  }

  return Math.min(peopleCount / maxExpectedPeople, 1);
}

function getHeatmapRadius(zoomLevel) {
  const baseRadius = 22;
  const zoomBoost = Math.max(zoomLevel - 11, 0) * 5;

  return Math.min(baseRadius + zoomBoost, 60);
}

const droneIcon = new L.Icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  tooltipAnchor: [16, -28],
  shadowSize: [41, 41],
})

function HeatmapLayer({ points, maxExpectedPeople }) {
  const map = useMap();
  const [zoomLevel, setZoomLevel] = useState(() => map.getZoom());

  useEffect(() => {
    const handleZoomEnd = () => {
      setZoomLevel(map.getZoom());
    };

    map.on('zoomend', handleZoomEnd);

    return () => {
      map.off('zoomend', handleZoomEnd);
    };
  }, [map]);

  useEffect(() => {
    const heatLayer = L.heatLayer(
      points.map(({ position, peopleCount }) => [
        position[0],
        position[1],
        getIntensityFromPeopleCount(peopleCount, maxExpectedPeople),
      ]),
      {
        radius: getHeatmapRadius(zoomLevel),
        blur: Math.max(18, Math.round(getHeatmapRadius(zoomLevel) * 0.75)),
        maxZoom: 17,
        minOpacity: 0.4,
        gradient: {
          0.2: '#38bdf8',
          0.45: '#22c55e',
          0.7: '#f59e0b',
          1.0: '#ef4444',
        },
      },
    ).addTo(map)

    return () => {
      map.removeLayer(heatLayer)
    }
  }, [map, maxExpectedPeople, points, zoomLevel])

  return null;
}

export function LeafletHeatmapMap({
  className = 'leaflet-map',
  center = droneHubPosition,
  zoom = 13,
  points = hotspotData,
  maxExpectedPeople = DEFAULT_MAX_EXPECTED_PEOPLE,
  scrollWheelZoom = true,
  tileUrl,
  theme = 'light',
  attribution = DEFAULT_ATTRIBUTION,
  showHeatmap = true,
  showMarkers = true,
  showHubMarker = true,
}) {
  const resolvedTileUrl = tileUrl || CARTO_TILE_URL_LIGHT

  return (
    <MapContainer
      center={center}
      zoom={zoom}
      scrollWheelZoom={scrollWheelZoom}
      className={className}
      preferCanvas={true}
      fadeAnimation={true}
      maxZoom={18}
    >
      <TileLayer
        attribution={attribution}
        url={resolvedTileUrl}
        keepBuffer={8}
        updateWhenZooming={false}
        updateWhenIdle={true}
        reuseTiles={true}
      />
      {showHeatmap ? <HeatmapLayer points={points} maxExpectedPeople={maxExpectedPeople} /> : null}

      {showHubMarker ? (
        <Marker position={center} icon={droneIcon}>
          <Popup>
            Drone hub<br />
            New Delhi operations center.
          </Popup>
        </Marker>
      ) : null}

      {showMarkers
        ? points.map(({ id, label, position, peopleCount }) => (
            <Marker key={id} position={position}>
              <Tooltip direction="top" offset={[0, -24]} opacity={0.95}>
                <strong>{label}</strong>
                <br />
                People detected: {peopleCount}
              </Tooltip>
              <Popup>
                <strong>{label}</strong>
                <br />
                People detected: {peopleCount}
                <br />
                Heat weight: {getIntensityFromPeopleCount(peopleCount, maxExpectedPeople).toFixed(2)}
              </Popup>
            </Marker>
          ))
        : null}
    </MapContainer>
  )
}

export default function App() {
  const [maxExpectedPeople, setMaxExpectedPeople] = useState(DEFAULT_MAX_EXPECTED_PEOPLE);

  const totalPeopleDetected = useMemo(
    () => hotspotData.reduce((sum, hotspot) => sum + hotspot.peopleCount, 0),
    [],
  );

  return (
    <main className="page-shell">
      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">OpenStreetMap + Leaflet</p>
          <h1>Drone surveillance dashboard</h1>
          <p className="description">
            Live-ready map canvas for plotting drone routes, checkpoints, and
            monitored zones on top of OpenStreetMap tiles.
          </p>
        </div>
        <div className="status-card">
          <span className="status-dot" />
          <div>
            <strong>Monitoring active</strong>
            <p>
              {hotspotData.length} dummy hotspots with {totalPeopleDetected} detected
              people centered on New Delhi, India.
            </p>
          </div>
        </div>
      </section>

      <section className="map-card">
        <div className="map-card-header">
          <div>
            <h2>Mission map</h2>
            <p>
              Dummy backend coordinates rendered as a crowd-density heatmap over
              OpenStreetMap.
            </p>
          </div>
          <div className="legend">
            <span className="legend-title">Crowd density</span>
            <div className="legend-scale" aria-hidden="true" />
            <div className="legend-labels">
              <span>Low</span>
              <span>High</span>
            </div>
            <label className="legend-control" htmlFor="maxExpectedPeople">
              <span>Max expected people</span>
              <input
                id="maxExpectedPeople"
                type="number"
                min="1"
                step="1"
                value={maxExpectedPeople}
                onChange={(event) => {
                  const nextValue = Number(event.target.value);

                  setMaxExpectedPeople(nextValue > 0 ? nextValue : 1);
                }}
              />
            </label>
            <p className="legend-note">Heat radius expands as you zoom in for broader area impact.</p>
          </div>
        </div>

        <LeafletHeatmapMap
          className="map-view"
          maxExpectedPeople={maxExpectedPeople}
          points={hotspotData}
          center={droneHubPosition}
          zoom={13}
        />

        <div className="hotspot-grid">
          {hotspotData.map(({ id, label, peopleCount }) => (
            <article key={id} className="hotspot-card">
              <span className="hotspot-index">#{String(id).padStart(2, '0')}</span>
              <strong>{label}</strong>
              <p>People detected: {peopleCount}</p>
              <p>
                Heat weight: {getIntensityFromPeopleCount(peopleCount, maxExpectedPeople).toFixed(2)}
              </p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
