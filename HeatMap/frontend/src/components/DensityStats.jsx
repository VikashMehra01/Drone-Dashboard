import { useState, useMemo } from 'react'
import { Users, BarChart3, AlertTriangle, Info } from 'lucide-react'
import { useDrones } from '../context/DronesContext'
import droneIcon from '../assets/drone.png'

const DroneImageIcon = ({ size }) => <img src={droneIcon} alt="Drone" style={{ width: size, height: size, objectFit: 'contain' }} />

export default function DensityStats() {
    const { drones } = useDrones()
    const [expandedInfo, setExpandedInfo] = useState(null);

    // All of this is a pure derivation of `drones` (from the shared
    // DronesContext poll) — no fetch of its own, so no effect needed.
    const { liveData, activeDroneCount, totalDroneCount, criticalZonesCount, avgDensity } = useMemo(() => {
        const activeDrones = drones.filter((d) => d.status === 'active' || d.status === 'debug');

        const totalPeopleFromDrones = activeDrones.reduce(
            (sum, d) => sum + Number(d.headcountDensity || 0),
            0,
        );
        const computedAvgDensity = Math.round(totalPeopleFromDrones / (activeDrones.length || 1));

        let thresholdsByDrone = {};
        try {
            const raw = localStorage.getItem('maxIntensityByDrone');
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed && typeof parsed === 'object') {
                    thresholdsByDrone = parsed;
                }
            }
        } catch {
            thresholdsByDrone = {};
        }

        const criticalCount = activeDrones.reduce((count, d) => {
            const threshold = Number(thresholdsByDrone[d.id] ?? 100);
            const density = Number(d.headcountDensity || 0);
            return count + (density >= threshold ? 1 : 0);
        }, 0);

        return {
            liveData: { headcount: totalPeopleFromDrones },
            activeDroneCount: activeDrones.length,
            totalDroneCount: drones.length,
            criticalZonesCount: criticalCount,
            avgDensity: computedAvgDensity,
        };
    }, [drones]);

    // Use liveData.headcount derived from active drone streams
    const totalPeople = Math.round(liveData.headcount) || 0;
    const activeDrones = activeDroneCount
    const alertsCount = criticalZonesCount;

    const stats = [
        {
            label: 'Estimated Crowd Count',
            value: totalPeople.toLocaleString(),
            trend: 'Live Stream',
            trendDir: 'up',
            icon: Users,
            color: 'blue',
            description: 'Total estimated number of people detected across all active drone feeds.',
        },
        {
            label: 'Active Drones',
            value: `${activeDrones} / ${totalDroneCount}`,
            trend: 'Online',
            trendDir: 'up',
            icon: DroneImageIcon,
            color: 'green',
            description: 'Number of drones currently online and streaming live footage out of the total fleet.',
        },
        {
            label: 'Average Crowd',
            value: avgDensity.toLocaleString(),
            trend: '',
            trendDir: '',
            icon: BarChart3,
            color: 'purple',
            description: 'Average number of people detected per active drone stream.',
        },
        {
            label: 'Critical Zones',
            value: alertsCount,
            trend: alertsCount > 0 ? 'Action Needed' : 'All Clear',
            trendDir: alertsCount > 0 ? 'up' : 'down',
            icon: AlertTriangle,
            color: 'amber',
            description: 'Number of zones where the detected crowd size exceeds the defined critical threshold.',
        },
    ]

    return (
        <div className="stats-grid">
            {stats.map((stat, i) => {
                const Icon = stat.icon
                return (
                    <div key={i} className={`stat-card ${stat.color}`} id={`stat-card-${i}`}>
                        <div className="stat-card-header">
                            <div className={`stat-card-icon ${stat.color}`}>
                                <Icon size={20} />
                            </div>
                            <span className={`stat-card-trend ${stat.trendDir}`}>
                                {stat.trend}
                            </span>
                        </div>
                        <div className="stat-card-value">{stat.value}</div>
                        <div className="stat-card-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            {stat.label}
                            <Info 
                                size={14} 
                                style={{ color: 'var(--color-text-muted)', cursor: 'pointer' }} 
                                onClick={() => setExpandedInfo(expandedInfo === i ? null : i)}
                            />
                        </div>
                        {expandedInfo === i && (
                            <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: '1.4', padding: '8px', borderRadius: '6px', border: '1px solid var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}>
                                {stat.description}
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
