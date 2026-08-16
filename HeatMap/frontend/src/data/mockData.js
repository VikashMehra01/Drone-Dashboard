// Mock data for the drone surveillance portal

export const mockDrones = [
    {
        id: 'DRN-001',
        name: 'Alpha-1',
        status: 'active',
        latitude: 28.6139,
        longitude: 77.2090,
        altitude: 120,
        battery: 87,
        speed: 12.5,
        peopleCounted: 342,
        zone: 'Connaught Place',
    },
    {
        id: 'DRN-002',
        name: 'Bravo-2',
        status: 'active',
        latitude: 28.6304,
        longitude: 77.2177,
        altitude: 95,
        battery: 64,
        speed: 8.3,
        peopleCounted: 218,
        zone: 'Chandni Chowk',
    },
    {
        id: 'DRN-003',
        name: 'Charlie-3',
        status: 'idle',
        latitude: 28.5535,
        longitude: 77.2588,
        altitude: 0,
        battery: 100,
        speed: 0,
        peopleCounted: 0,
        zone: 'Nehru Place',
    },
    {
        id: 'DRN-004',
        name: 'Delta-4',
        status: 'active',
        latitude: 28.5672,
        longitude: 77.2100,
        altitude: 110,
        battery: 45,
        speed: 15.1,
        peopleCounted: 567,
        zone: 'Hauz Khas',
    },
    {
        id: 'DRN-005',
        name: 'Echo-5',
        status: 'offline',
        latitude: 28.6292,
        longitude: 77.1780,
        altitude: 0,
        battery: 12,
        speed: 0,
        peopleCounted: 0,
        zone: 'Karol Bagh',
    },
]

export const mockHeatmapData = [
    // Connaught Place cluster
    [28.6139, 77.2090, 0.9],
    [28.6145, 77.2095, 0.85],
    [28.6133, 77.2085, 0.8],
    [28.6150, 77.2100, 0.7],
    [28.6125, 77.2080, 0.75],
    [28.6142, 77.2110, 0.6],
    [28.6120, 77.2070, 0.5],
    [28.6155, 77.2115, 0.45],
    // Chandni Chowk cluster
    [28.6304, 77.2177, 0.7],
    [28.6310, 77.2185, 0.65],
    [28.6298, 77.2170, 0.6],
    [28.6315, 77.2190, 0.55],
    [28.6290, 77.2165, 0.5],
    [28.6320, 77.2200, 0.4],
    // Hauz Khas cluster
    [28.5672, 77.2100, 0.95],
    [28.5680, 77.2110, 0.9],
    [28.5665, 77.2095, 0.85],
    [28.5690, 77.2120, 0.75],
    [28.5660, 77.2090, 0.7],
    [28.5695, 77.2130, 0.6],
    [28.5650, 77.2080, 0.5],
    // Nehru Place cluster
    [28.5535, 77.2588, 0.3],
    [28.5540, 77.2595, 0.25],
    [28.5530, 77.2580, 0.2],
    // Karol Bagh cluster
    [28.6292, 77.1780, 0.15],
    [28.6300, 77.1790, 0.1],
]

export const mockDensityHistory = [
    { time: '00:00', connaught: 120, chandni: 85, hauz: 200, nehru: 40 },
    { time: '02:00', connaught: 80, chandni: 45, hauz: 150, nehru: 25 },
    { time: '04:00', connaught: 40, chandni: 20, hauz: 60, nehru: 10 },
    { time: '06:00', connaught: 90, chandni: 70, hauz: 110, nehru: 35 },
    { time: '08:00', connaught: 250, chandni: 180, hauz: 280, nehru: 80 },
    { time: '10:00', connaught: 380, chandni: 290, hauz: 420, nehru: 150 },
    { time: '12:00', connaught: 450, chandni: 350, hauz: 500, nehru: 200 },
    { time: '14:00', connaught: 420, chandni: 320, hauz: 480, nehru: 180 },
    { time: '16:00', connaught: 380, chandni: 280, hauz: 450, nehru: 160 },
    { time: '18:00', connaught: 500, chandni: 400, hauz: 550, nehru: 220 },
    { time: '20:00', connaught: 340, chandni: 250, hauz: 380, nehru: 140 },
    { time: '22:00', connaught: 200, chandni: 150, hauz: 250, nehru: 70 },
]

export const mockZoneDensity = [
    { zone: 'Connaught Place', density: 342, level: 'high', change: +12 },
    { zone: 'Chandni Chowk', density: 218, level: 'medium', change: -5 },
    { zone: 'Hauz Khas', density: 567, level: 'critical', change: +28 },
    { zone: 'Nehru Place', density: 45, level: 'low', change: -2 },
    { zone: 'Karol Bagh', density: 0, level: 'none', change: 0 },
]

export const mockAlerts = [
    { id: 1, type: 'critical', zone: 'Hauz Khas', message: 'Crowd density exceeded safe threshold', time: '2 min ago' },
    { id: 2, type: 'warning', zone: 'Connaught Place', message: 'Rapid crowd buildup detected', time: '8 min ago' },
    { id: 3, type: 'info', zone: 'Chandni Chowk', message: 'Drone DRN-002 battery below 70%', time: '15 min ago' },
]
