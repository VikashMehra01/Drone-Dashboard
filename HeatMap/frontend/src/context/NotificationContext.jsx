import { createContext, useContext, useState, useRef, useCallback, useEffect } from 'react';
import { AlertTriangle, Info, X } from 'lucide-react';

const NotificationContext = createContext();

export function NotificationProvider({ children }) {
    // Array of notification objects
    const [notifications, setNotifications] = useState([]);
    const [toasts, setToasts] = useState([]); // Array for active popup toasts
    
    // Track last alert time to prevent spam (30s cooldown per drone)
    const lastAlertTimeRef = useRef({});
    
    // Track the last 20 frames of density headcount per drone
    // Shape: { [droneId]: [val1, val2, ... val20] }
    const frameHistoryRef = useRef({});

    const removeToast = useCallback((id) => {
        setToasts(prev => prev.filter(t => t.id !== id));
    }, []);

    const addNotification = useCallback((notification) => {
        const id = Math.random().toString(36).substr(2, 9);
        const newNotif = {
            id,
            timestamp: new Date().toISOString(),
            isRead: false,
            ...notification
        };

        setNotifications(prev => [newNotif, ...prev]);
        
        // Also trigger a popup toast
        setToasts(prev => [...prev, newNotif]);
        
        // Auto-remove toast after 5 seconds
        setTimeout(() => {
            removeToast(id);
        }, 5000);
    }, [removeToast]);

    const markAsRead = useCallback((id) => {
        setNotifications(prev => 
            prev.map(n => n.id === id ? { ...n, isRead: true } : n)
        );
    }, []);

    const markAllAsRead = useCallback(() => {
        setNotifications(prev => 
            prev.map(n => ({ ...n, isRead: true }))
        );
    }, []);

    const processStreamData = useCallback((drones, streamMetricsByVideo, maxIntensityByDrone) => {
        const now = Date.now();
        const COOLDOWN_MS = 30000; // 30 seconds

        drones.forEach(drone => {
            if (drone.status !== 'active' && drone.status !== 'debug') return;

            // Find the video name for parsing metrics
            const urlParts = drone.video_url?.split('/') || [];
            const videoName = urlParts[urlParts.length - 1] || '';
            const metrics = streamMetricsByVideo[videoName];
            
            // Getting headcount and threshold
            const headcount = Number(metrics?.headcount ?? drone.headcountDensity ?? 0);
            const threshold = Number(maxIntensityByDrone[drone.id] ?? 100);

            // 1. Maintain the 20-frame rolling window
            if (!frameHistoryRef.current[drone.id]) {
                frameHistoryRef.current[drone.id] = [];
            }
            const history = frameHistoryRef.current[drone.id];
            
            history.push({ headcount, threshold });
            
            if (history.length > 20) {
                history.shift(); // Keep only the last 20 frames
            }

            // 2. Check violation condition
            // Condition: headcount > threshold for MORE THAN 5 frames
            const violationFrames = history.filter(frame => frame.headcount > frame.threshold).length;
            
            if (violationFrames > 5) {
                const lastAlert = lastAlertTimeRef.current[drone.id] || 0;
                
                // If we haven't alerted in the last 30 seconds
                if (now - lastAlert > COOLDOWN_MS) {
                    const message = `Critical crowd density detected! Over ${threshold} people sustained for multiple frames.`
                    
                    addNotification({
                        droneId: drone.id,
                        droneName: drone.name,
                        type: 'critical',
                        message: message,
                    });
                    
                    // Trigger Telegram Broadcast asynchronously
                    fetch('http://localhost:8000/api/alerts/broadcast', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'key': 'sk_skywatch_local_secret_123',
                        },
                        body: JSON.stringify({
                            title: "SkyWatch Critical Alert",
                            message: message,
                            level: "critical",
                            drone_name: drone.name,
                            zone: drone.zone || "Unknown Zone",
                            latitude: drone.latitude ? parseFloat(drone.latitude) : null,
                            longitude: drone.longitude ? parseFloat(drone.longitude) : null
                        })
                    }).catch(err => console.error("Failed to trigger telegram alert", err));
                    
                    lastAlertTimeRef.current[drone.id] = now;
                } else {
                    console.log(`[Notification] Cooldown active for drone ${drone.id} (needs ${COOLDOWN_MS - (now - lastAlert)}ms more)`);
                }
            } else {
                console.log(`[Notification] Drone ${drone.id} (${videoName}): headcount ${headcount} vs threshold ${threshold}. Violation frames: ${violationFrames}/20`);
            }
        });
    }, [addNotification]);

    const unreadCount = notifications.filter(n => !n.isRead).length;

    return (
        <NotificationContext.Provider value={{
            notifications,
            unreadCount,
            addNotification,
            markAsRead,
            markAllAsRead,
            processStreamData
        }}>
            {children}
            
            {/* Global Toast Container */}
            <div className="toast-container">
                {toasts.map(toast => (
                    <div key={`toast-${toast.id}`} className={`toast-item ${toast.type}`}>
                        <div className="toast-icon">
                            {toast.type === 'critical' ? <AlertTriangle size={20} /> : <Info size={20} />}
                        </div>
                        <div className="toast-content">
                            <div className="toast-title">{toast.droneName}</div>
                            <div className="toast-message">{toast.message}</div>
                        </div>
                        <button className="toast-close" onClick={() => removeToast(toast.id)}>
                            <X size={16} />
                        </button>
                    </div>
                ))}
            </div>
        </NotificationContext.Provider>
    );
}

export const useNotification = () => useContext(NotificationContext);
