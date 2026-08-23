import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import {
    LayoutDashboard, Video, BarChart3, Radio,
    Shield, Info, WifiOff, PlusCircle, LogOut, Settings2,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useDrones } from '../context/DronesContext'
import AdminPanel from './AdminPanel'
import AddDroneModal from './AddDroneModal'

const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/feeds', label: 'Live Feeds', icon: Video },
    { path: '/analytics', label: 'Analytics', icon: BarChart3 },
    { path: '/about', label: 'About', icon: Info },
]

// ── Sidebar ──────────────────────────────────────────────────────────────────
// Add Member now lives inside the Manage panel's Users tab (AdminPanel.jsx),
// next to the user list it affects, instead of as a separate sidebar button.
export default function Sidebar() {
    const location = useLocation()
    const navigate = useNavigate()
    const { isOnline } = useDrones()
    const [showAddDrone, setShowAddDrone] = useState(false)
    const [showAdminPanel, setShowAdminPanel] = useState(false)
    const { user, logout, authFetch } = useAuth()
    const isAdmin = user?.role === 'admin'

    const handleLogout = () => { logout(); navigate('/login', { replace: true }) }

    return (
        <>
            <aside className="sidebar">
                <div className="sidebar-header">
                    <div className="sidebar-logo"><Shield /></div>
                    <div>
                        <div className="sidebar-title">SkyWatch</div>
                        <div className="sidebar-subtitle">Surveillance Portal</div>
                    </div>
                </div>

                <nav className="sidebar-nav">
                    <div className="sidebar-section-label">Main Menu</div>
                    {navItems.map((item) => {
                        const Icon = item.icon
                        return (
                            <NavLink
                                key={item.path}
                                to={item.path}
                                className={`nav-link ${location.pathname === item.path ? 'active' : ''}`}
                            >
                                <Icon /><span>{item.label}</span>
                            </NavLink>
                        )
                    })}

                    {isAdmin && (
                        <>
                            <div className="sidebar-section-label" style={{ marginTop: 12 }}>Admin Controls</div>
                            <button id="sidebar-add-drone-btn" className="nav-link nav-link-action" onClick={() => setShowAddDrone(true)}>
                                <PlusCircle /><span>Add Drone</span>
                            </button>
                            <button id="sidebar-manage-btn" className="nav-link nav-link-action nav-link-manage" onClick={() => setShowAdminPanel(true)}>
                                <Settings2 /><span>Manage</span>
                            </button>
                        </>
                    )}
                </nav>

                <div className="sidebar-footer">
                    {user && (
                        <div className="sidebar-user">
                            <div className="sidebar-user-avatar">{user.username.charAt(0).toUpperCase()}</div>
                            <div className="sidebar-user-info">
                                <div className="sidebar-user-name">{user.username}</div>
                                <div className="sidebar-user-role">{user.role}</div>
                            </div>
                            <button id="sidebar-logout-btn" className="sidebar-logout" onClick={handleLogout} title="Sign out">
                                <LogOut size={15} />
                            </button>
                        </div>
                    )}
                    <div className="sidebar-status" style={!isOnline ? { background: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.2)' } : {}}>
                        <div className="status-dot" style={!isOnline ? { background: '#ef4444', animation: 'none' } : {}} />
                        {isOnline ? <Radio size={14} style={{ color: '#10b981' }} /> : <WifiOff size={14} style={{ color: '#ef4444' }} />}
                        <span className="status-text" style={!isOnline ? { color: '#ef4444' } : {}}>
                            {isOnline ? 'System Online' : 'System Offline'}
                        </span>
                    </div>
                </div>
            </aside>

            <AddDroneModal open={showAddDrone} onClose={() => setShowAddDrone(false)} authFetch={authFetch} />
            {showAdminPanel && <AdminPanel onClose={() => setShowAdminPanel(false)} />}
        </>
    )
}
