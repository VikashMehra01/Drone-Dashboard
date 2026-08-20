import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { Bell, Settings, AlertTriangle, Info, CheckCircle2 } from 'lucide-react'
import { Switch, Select, MenuItem } from '@mui/material'
import { useNotification } from '../context/NotificationContext'
import { useSettings } from '../context/SettingsContext'

const pageTitles = {
    '/': 'Command Center',
    '/feeds': 'Live Drone Feeds',
    '/analytics': 'Analytics & Reports',
    '/about': 'About',
}

export default function Navbar() {
    const location = useLocation()
    const [currentTime, setCurrentTime] = useState(new Date())
    const [isNotificationOpen, setIsNotificationOpen] = useState(false)
    const [isSettingsOpen, setIsSettingsOpen] = useState(false)
    const dropdownRef = useRef(null)
    const settingsRef = useRef(null)
    const { notifications, unreadCount, markAsRead, markAllAsRead } = useNotification()
    const { hideFleetLabels, setHideFleetLabels, dashboardTextSize, setDashboardTextSize, showLivePanelInfo, setShowLivePanelInfo, theme, setTheme } = useSettings()

    useEffect(() => {
        const timer = setInterval(() => setCurrentTime(new Date()), 1000)
        return () => clearInterval(timer)
    }, [])

    useEffect(() => {
        function handleClickOutside(event) {
            // Ignore if element was removed from DOM
            if (!document.contains(event.target)) return;

            // Ignore clicks outside the main React root (e.g., inside MUI Portals like Select dropdowns)
            const rootElement = document.getElementById('root');
            if (rootElement && !rootElement.contains(event.target)) {
                return;
            }

            if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
                setIsNotificationOpen(false)
            }
            if (settingsRef.current && !settingsRef.current.contains(event.target)) {
                setIsSettingsOpen(false)
            }
        }
        document.addEventListener("mousedown", handleClickOutside)
        return () => document.removeEventListener("mousedown", handleClickOutside)
    }, [])

    const formatTime = (date) =>
        date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        })

    const formatDate = (date) =>
        date.toLocaleDateString('en-US', {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
        })

    return (
        <header className="navbar">
            <div className="navbar-left">
                <div>
                    <h1 className="navbar-title">
                        {pageTitles[location.pathname] || 'Dashboard'}
                    </h1>

                </div>
            </div>

            <div className="navbar-right">
                <span className="navbar-time">
                    {formatDate(currentTime)} &nbsp;·&nbsp; {formatTime(currentTime)}
                </span>
                
                <div className="notification-wrapper" ref={dropdownRef}>
                    <button 
                        className={`navbar-btn ${unreadCount > 0 ? 'notification-badge' : ''}`}
                        onClick={() => setIsNotificationOpen(!isNotificationOpen)}
                    >
                        <Bell size={18} />
                        {unreadCount > 0 && <span className="notification-count">{unreadCount}</span>}
                    </button>

                    {isNotificationOpen && (
                        <div className="notification-dropdown">
                            <div className="notification-header">
                                <h3>Notifications</h3>
                                {unreadCount > 0 && (
                                    <button className="mark-all-read" onClick={markAllAsRead}>
                                        Mark all as read
                                    </button>
                                )}
                            </div>
                            
                            <div className="notification-list">
                                {notifications.length === 0 ? (
                                    <div className="notification-empty">
                                        <CheckCircle2 size={32} />
                                        <p>You're all caught up!</p>
                                    </div>
                                ) : (
                                    notifications.map(notif => (
                                        <div 
                                            key={notif.id} 
                                            className={`notification-item ${notif.isRead ? 'read' : 'unread'} ${notif.type}`}
                                            onClick={() => markAsRead(notif.id)}
                                        >
                                            <div className="notification-icon">
                                                {notif.type === 'critical' ? <AlertTriangle size={18} /> : <Info size={18} />}
                                            </div>
                                            <div className="notification-content">
                                                <div className="notification-title">{notif.droneName}</div>
                                                <div className="notification-message">{notif.message}</div>
                                                <div className="notification-time">
                                                    {new Date(notif.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                </div>
                                            </div>
                                            {!notif.isRead && <div className="notification-dot" />}
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <div className="notification-wrapper" ref={settingsRef}>
                    <button className="navbar-btn" id="settings-btn" onClick={() => setIsSettingsOpen(!isSettingsOpen)}>
                        <Settings size={18} />
                    </button>
                    {isSettingsOpen && (
                        <div className="notification-dropdown settings-dropdown">
                            <div className="notification-header">
                                <h3>Settings</h3>
                            </div>
                            <div className="notification-list" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px', maxHeight: 'none' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span style={{ fontSize: '13px' }}>Hide Fleet Labels</span>
                                    <Switch 
                                        checked={hideFleetLabels} 
                                        onChange={(e) => setHideFleetLabels(e.target.checked)} 
                                        size="small"
                                    />
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span style={{ fontSize: '13px' }}>Show Live Panel Info</span>
                                    <Switch 
                                        checked={showLivePanelInfo} 
                                        onChange={(e) => setShowLivePanelInfo(e.target.checked)} 
                                        size="small"
                                    />
                                </div>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                    <span style={{ fontSize: '13px' }}>Theme</span>
                                    <Select 
                                        value={theme} 
                                        onChange={(e) => setTheme(e.target.value)}
                                        size="small"
                                    >
                                        <MenuItem value="dark">Dark Mode</MenuItem>
                                        <MenuItem value="light">Light Mode</MenuItem>
                                    </Select>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </header>
    )
}
