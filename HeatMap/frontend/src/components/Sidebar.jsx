import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import {
    LayoutDashboard, Video, BarChart3, Radio,
    Shield, Info, WifiOff, PlusCircle, UserPlus, LogOut, Settings2,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import AdminPanel from './AdminPanel'

// MUI
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import MenuItem from '@mui/material/MenuItem'
import CloseIcon from '@mui/icons-material/Close'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import PersonAddIcon from '@mui/icons-material/PersonAdd'

const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/feeds', label: 'Live Feeds', icon: Video },
    { path: '/analytics', label: 'Analytics', icon: BarChart3 },
    { path: '/about', label: 'About', icon: Info },
]

// ── Add Drone Modal ──────────────────────────────────────────────────────────
function AddDroneModal({ open, onClose, authFetch }) {
    const init = { drone_id: '', drone_name: '', source: '', latitude: '', longitude: '', altitude: '100', zone: 'Live Stream Zone', fps: '5', loop: false, model: 'sdnet', device: 'cpu' }
    const [form, setForm] = useState(init)
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState(null)   // { text, severity }

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

    const handleClose = () => { setForm(init); setMsg(null); onClose() }

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!form.drone_id || !form.drone_name || !form.source || !form.latitude || !form.longitude) {
            setMsg({ text: 'Please fill all required fields.', severity: 'error' }); return
        }
        setLoading(true); setMsg(null)
        try {
            const res = await authFetch('http://localhost:8000/api/auth/drones/launch', {
                method: 'POST',
                body: JSON.stringify({ ...form, latitude: parseFloat(form.latitude), longitude: parseFloat(form.longitude), altitude: parseFloat(form.altitude), fps: parseInt(form.fps, 10) }),
            })
            const data = await res.json()
            if (!res.ok) { setMsg({ text: data.detail || 'Launch failed.', severity: 'error' }) }
            else { setMsg({ text: data.message, severity: 'success' }); setTimeout(handleClose, 2000) }
        } catch { setMsg({ text: 'Cannot reach server.', severity: 'error' }) }
        finally { setLoading(false) }
    }

    const field = (label, key, props = {}) => (
        <TextField
            label={label} value={form[key]} size="small" fullWidth
            onChange={e => { set(key, e.target.value); setMsg(null) }}
            {...props}
        />
    )

    return (
        <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
                <RocketLaunchIcon fontSize="small" sx={{ color: 'primary.main' }} />
                Add New Drone
                <IconButton onClick={handleClose} sx={{ ml: 'auto' }} size="small">
                    <CloseIcon fontSize="small" />
                </IconButton>
            </DialogTitle>

            <DialogContent dividers>
                <form id="add-drone-form" onSubmit={handleSubmit}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            {field('Drone ID *', 'drone_id', { placeholder: 'e.g. DRN-005', autoFocus: true })}
                            {field('Drone Name *', 'drone_name', { placeholder: 'e.g. Alpha-5' })}
                        </div>

                        {field('Stream Source *', 'source', {
                            placeholder: '../media/videos/droneVid.mp4  or  rtsp://192.168.1.10:554/live',
                            helperText: 'Relative to cv_pipeline/ — file path, RTSP, RTMP, or HTTP URL'
                        })}

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                            {field('Latitude *', 'latitude', { type: 'number', inputProps: { step: 'any' }, placeholder: '28.6139' })}
                            {field('Longitude *', 'longitude', { type: 'number', inputProps: { step: 'any' }, placeholder: '77.2090' })}
                            {field('Altitude (m)', 'altitude', { type: 'number' })}
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            {field('Zone Name', 'zone')}
                            {field('FPS', 'fps', { type: 'number', inputProps: { min: 1, max: 30 } })}
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            <TextField
                                select label="Detection Model" value={form.model} size="small" fullWidth
                                onChange={e => set('model', e.target.value)}
                                SelectProps={{ MenuProps: { disablePortal: true } }}
                            >
                                <MenuItem value="sdnet">SDNet (crowd density)</MenuItem>
                                <MenuItem value="yolo">YOLO (object detection)</MenuItem>
                            </TextField>
                            <TextField
                                select label="Device" value={form.device} size="small" fullWidth
                                onChange={e => set('device', e.target.value)}
                                SelectProps={{ MenuProps: { disablePortal: true } }}
                            >
                                <MenuItem value="cpu">CPU</MenuItem>
                                <MenuItem value="cuda">GPU (CUDA)</MenuItem>
                            </TextField>
                        </div>

                        <FormControlLabel
                            control={<Checkbox checked={form.loop} onChange={e => set('loop', e.target.checked)} size="small" />}
                            label={<span style={{ fontSize: 13 }}>Loop (for local file sources)</span>}
                        />

                        {msg && <Alert severity={msg.severity} sx={{ py: 0.5 }}>{msg.text}</Alert>}
                    </div>
                </form>
            </DialogContent>

            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={handleClose} color="inherit" size="small">Cancel</Button>
                <Button
                    type="submit" form="add-drone-form" variant="contained" size="small"
                    disabled={loading}
                    startIcon={loading ? <CircularProgress size={14} color="inherit" /> : <RocketLaunchIcon />}
                >
                    {loading ? 'Launching…' : 'Launch Drone'}
                </Button>
            </DialogActions>
        </Dialog>
    )
}

// ── Add Member Modal ─────────────────────────────────────────────────────────
function AddMemberModal({ open, onClose, authFetch }) {
    const init = { username: '', password: '' }
    const [form, setForm] = useState(init)
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState(null)

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

    const handleClose = () => { setForm(init); setMsg(null); onClose() }

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!form.username || !form.password) {
            setMsg({ text: 'Username and password are required.', severity: 'error' }); return
        }
        setLoading(true); setMsg(null)
        try {
            const res = await authFetch('http://localhost:8000/api/auth/users', {
                method: 'POST',
                body: JSON.stringify({ ...form, role: 'member' }),
            })
            const data = await res.json()
            if (!res.ok) { setMsg({ text: data.detail || 'Failed to create user.', severity: 'error' }) }
            else { setMsg({ text: `User '${form.username}' created!`, severity: 'success' }); setTimeout(handleClose, 1800) }
        } catch { setMsg({ text: 'Cannot reach server.', severity: 'error' }) }
        finally { setLoading(false) }
    }

    return (
        <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
                <PersonAddIcon fontSize="small" sx={{ color: 'primary.main' }} />
                Add New Member
                <IconButton onClick={handleClose} sx={{ ml: 'auto' }} size="small">
                    <CloseIcon fontSize="small" />
                </IconButton>
            </DialogTitle>

            <DialogContent dividers>
                <form id="add-member-form" onSubmit={handleSubmit}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>
                        <TextField
                            label="Username *" value={form.username} size="small" fullWidth autoFocus
                            placeholder="e.g. john_doe"
                            onChange={e => { set('username', e.target.value); setMsg(null) }}
                        />
                        <TextField
                            label="Password *" type="password" value={form.password} size="small" fullWidth
                            placeholder="Choose a strong password"
                            onChange={e => { set('password', e.target.value); setMsg(null) }}
                        />

                        {msg && <Alert severity={msg.severity} sx={{ py: 0.5 }}>{msg.text}</Alert>}
                    </div>
                </form>
            </DialogContent>

            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={handleClose} color="inherit" size="small">Cancel</Button>
                <Button
                    type="submit" form="add-member-form" variant="contained" size="small"
                    disabled={loading}
                    startIcon={loading ? <CircularProgress size={14} color="inherit" /> : <PersonAddIcon />}
                >
                    {loading ? 'Creating…' : 'Create Member'}
                </Button>
            </DialogActions>
        </Dialog>
    )
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
export default function Sidebar() {
    const location = useLocation()
    const navigate = useNavigate()
    const [isOnline, setIsOnline] = useState(true)
    const [showAddDrone, setShowAddDrone] = useState(false)
    const [showAddMember, setShowAddMember] = useState(false)
    const [showAdminPanel, setShowAdminPanel] = useState(false)
    const { user, logout, authFetch } = useAuth()
    const isAdmin = user?.role === 'admin'

    useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await fetch('http://localhost:8000/api/drones/', { method: 'GET' })
                setIsOnline(res.ok)
            } catch { setIsOnline(false) }
        }
        checkStatus()
        const interval = setInterval(checkStatus, 3000)
        return () => clearInterval(interval)
    }, [])

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
                            <button id="sidebar-add-member-btn" className="nav-link nav-link-action" onClick={() => setShowAddMember(true)}>
                                <UserPlus /><span>Add Member</span>
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
            <AddMemberModal open={showAddMember} onClose={() => setShowAddMember(false)} authFetch={authFetch} />
            {showAdminPanel && <AdminPanel onClose={() => setShowAdminPanel(false)} />}
        </>
    )
}
