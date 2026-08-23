import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
    X, Users, Cpu, Trash2, Key, RefreshCw, ShieldCheck,
    ShieldOff, Loader2, AlertCircle, CheckCircle2,
    MapPin, Activity, ChevronDown, ChevronUp,
    Square, Play, Search, ArrowUpDown, Edit, UserPlus, PlusCircle,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useModelOptions } from '../utils/useModelOptions'
import AddDroneModal from './AddDroneModal'

// MUI
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import CloseIcon from '@mui/icons-material/Close'
import KeyIcon from '@mui/icons-material/Key'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import Select from '@mui/material/Select'
import MenuItem from '@mui/material/MenuItem'
import FormControl from '@mui/material/FormControl'
import InputLabel from '@mui/material/InputLabel'

// ── Toast ────────────────────────────────────────────────────────────────────
function Toast({ msg, onDone }) {
    useEffect(() => {
        const t = setTimeout(onDone, 3500)
        return () => clearTimeout(t)
    }, [onDone])
    if (!msg) return null
    return (
        <div className={`admin-toast ${msg.type}`}>
            {msg.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
            {msg.text}
        </div>
    )
}

// ── Search bar ────────────────────────────────────────────────────────────────
function SearchBar({ value, onChange, placeholder }) {
    return (
        <div className="admin-search-bar">
            <Search size={14} className="admin-search-icon" />
            <input
                className="admin-search-input"
                type="text"
                placeholder={placeholder}
                value={value}
                onChange={e => onChange(e.target.value)}
            />
            {value && (
                <button className="admin-search-clear" onClick={() => onChange('')}>
                    <X size={12} />
                </button>
            )}
        </div>
    )
}

// ── Confirm Delete dialog ────────────────────────────────────────────────────
function ConfirmDeleteDialog({ title, body, onConfirm, onClose }) {
    return (
        <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
                <Trash2 size={16} style={{ color: '#ef4444' }} />
                {title}
                <IconButton onClick={onClose} sx={{ ml: 'auto' }} size="small"><CloseIcon fontSize="small" /></IconButton>
            </DialogTitle>
            <DialogContent dividers>
                <p style={{ margin: 0, fontSize: 14 }}>{body}</p>
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={onClose} color="inherit" size="small">Cancel</Button>
                <Button onClick={onConfirm} variant="contained" color="error" size="small" startIcon={<Trash2 size={14} />}>
                    Delete
                </Button>
            </DialogActions>
        </Dialog>
    )
}

// ── Change-Password modal ─────────────────────────────────────────────────────
function ChangePasswordModal({ username, onClose, authFetch, onSuccess }) {
    const [pw, setPw] = useState('')
    const [loading, setLoading] = useState(false)
    const [err, setErr] = useState('')

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (pw.length < 4) { setErr('Min 4 characters'); return }
        setLoading(true)
        try {
            const res = await authFetch(`http://localhost:8000/api/auth/users/${username}/password`, {
                method: 'PATCH',
                body: JSON.stringify({ new_password: pw }),
            })
            const data = await res.json()
            if (!res.ok) { setErr(data.detail || 'Failed'); return }
            onSuccess(`Password updated for '${username}'.`)
            onClose()
        } catch { setErr('Server error') }
        finally { setLoading(false) }
    }

    return (
        <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
                <KeyIcon fontSize="small" sx={{ color: 'primary.main' }} />
                Change Password — {username}
                <IconButton onClick={onClose} sx={{ ml: 'auto' }} size="small"><CloseIcon fontSize="small" /></IconButton>
            </DialogTitle>
            <DialogContent dividers>
                <form id="chpw-form" onSubmit={handleSubmit}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, paddingTop: 4 }}>
                        <TextField
                            label="New Password *" type="password" autoFocus fullWidth size="small"
                            placeholder="At least 4 characters" value={pw}
                            onChange={e => { setPw(e.target.value); setErr('') }}
                        />
                        {err && <Alert severity="error" sx={{ py: 0.5 }}>{err}</Alert>}
                    </div>
                </form>
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={onClose} color="inherit" size="small">Cancel</Button>
                <Button type="submit" form="chpw-form" variant="contained" size="small"
                    disabled={loading}
                    startIcon={loading ? <CircularProgress size={14} color="inherit" /> : <KeyIcon />}
                >
                    {loading ? 'Saving…' : 'Update Password'}
                </Button>
            </DialogActions>
        </Dialog>
    )
}

// ── Edit Drone modal ─────────────────────────────────────────────────────────
function EditDroneModal({ drone, onClose, authFetch, onSuccess }) {
    const [formData, setFormData] = useState({
        drone_name: drone.name || '',
        source: drone.video_url || drone.config?.source || '',
        latitude: drone.latitude || '',
        longitude: drone.longitude || '',
        altitude: drone.altitude || 100,
        zone: drone.zone || '',
        fps: drone.fps || drone.config?.fps || 5,
        model: drone.model || drone.config?.model || 'sdnet',
        device: drone.device || drone.config?.device || 'cpu',
    })
    const [loading, setLoading] = useState(false)
    const [err, setErr] = useState('')
    const modelOptions = useModelOptions(authFetch)

    const handleChange = (e) => {
        const { name, value } = e.target
        setFormData(prev => ({ ...prev, [name]: value }))
        setErr('')
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setLoading(true)
        try {
            const payload = {
                ...formData,
                latitude: parseFloat(formData.latitude),
                longitude: parseFloat(formData.longitude),
                altitude: parseFloat(formData.altitude),
                fps: parseInt(formData.fps, 10)
            }
            const res = await authFetch(`http://localhost:8000/api/auth/drones/${drone.id}`, {
                method: 'PATCH',
                body: JSON.stringify(payload),
            })
            const data = await res.json()
            if (!res.ok) { setErr(data.detail || 'Failed to update'); return }
            onSuccess(`Drone '${drone.id}' updated successfully.`)
            onClose()
        } catch { setErr('Server error') }
        finally { setLoading(false) }
    }

    return (
        <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
                <Edit size={16} style={{ color: '#3b82f6' }} />
                Edit Drone — {drone.id}
                <IconButton onClick={onClose} sx={{ ml: 'auto' }} size="small"><CloseIcon fontSize="small" /></IconButton>
            </DialogTitle>
            <DialogContent dividers>
                <form id="edit-drone-form" onSubmit={handleSubmit} style={{ display: 'grid', gap: '16px', gridTemplateColumns: '1fr 1fr', paddingTop: 4 }}>
                    <TextField label="Name" name="drone_name" size="small" required
                        value={formData.drone_name} onChange={handleChange} fullWidth />
                    <TextField label="Stream URL" name="source" size="small" required
                        value={formData.source} onChange={handleChange} fullWidth />

                    <TextField label="Latitude" name="latitude" type="number" slotProps={{ htmlInput: { step: "any" } }} size="small" required
                        value={formData.latitude} onChange={handleChange} fullWidth />
                    <TextField label="Longitude" name="longitude" type="number" slotProps={{ htmlInput: { step: "any" } }} size="small" required
                        value={formData.longitude} onChange={handleChange} fullWidth />
                    
                    <TextField label="Altitude (m)" name="altitude" type="number" size="small"
                        value={formData.altitude} onChange={handleChange} fullWidth />
                    <TextField label="Zone" name="zone" size="small"
                        value={formData.zone} onChange={handleChange} fullWidth />
                    
                    <TextField label="FPS" name="fps" type="number" size="small"
                        value={formData.fps} onChange={handleChange} fullWidth style={{ gridColumn: '1 / -1' }}/>
                    
                    <FormControl size="small" fullWidth>
                        <InputLabel>Model</InputLabel>
                        <Select name="model" value={formData.model} onChange={handleChange} label="Model">
                            {modelOptions.map(m => (
                                <MenuItem key={m.key} value={m.key}>{m.label}</MenuItem>
                            ))}
                        </Select>
                    </FormControl>

                    <FormControl size="small" fullWidth>
                        <InputLabel>Device</InputLabel>
                        <Select name="device" value={formData.device} onChange={handleChange} label="Device">
                            <MenuItem value="cpu">CPU</MenuItem>
                            <MenuItem value="cuda">CUDA (GPU)</MenuItem>
                        </Select>
                    </FormControl>

                    {err && <div style={{ gridColumn: '1 / -1' }}><Alert severity="error" sx={{ py: 0.5 }}>{err}</Alert></div>}
                </form>
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={onClose} color="inherit" size="small">Cancel</Button>
                <Button type="submit" form="edit-drone-form" variant="contained" size="small"
                    disabled={loading}
                    startIcon={loading ? <CircularProgress size={14} color="inherit" /> : <Edit size={14} />}
                >
                    {loading ? 'Saving…' : 'Save Changes'}
                </Button>
            </DialogActions>
        </Dialog>
    )
}

// ── Add Member modal ─────────────────────────────────────────────────────────
// Lives here (not the sidebar) so creating a member sits next to the list it
// affects — matches "+ Add Drone" living in the Drones tab below.
function AddMemberModal({ onClose, authFetch, onSuccess }) {
    const [form, setForm] = useState({ username: '', password: '' })
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState(null)

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

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
            if (!res.ok) { setMsg({ text: data.detail || 'Failed to create user.', severity: 'error' }); return }
            onSuccess(`User '${form.username}' created.`)
            onClose()
        } catch { setMsg({ text: 'Cannot reach server.', severity: 'error' }) }
        finally { setLoading(false) }
    }

    return (
        <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
                <PersonAddIcon fontSize="small" sx={{ color: 'primary.main' }} />
                Add New Member
                <IconButton onClick={onClose} sx={{ ml: 'auto' }} size="small">
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
                <Button onClick={onClose} color="inherit" size="small">Cancel</Button>
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

// ── Users Tab ─────────────────────────────────────────────────────────────────
const USER_SORTS = [
    { key: 'username_asc',  label: 'Name A→Z' },
    { key: 'username_desc', label: 'Name Z→A' },
    { key: 'role_admin',    label: 'Admin first' },
    { key: 'role_member',   label: 'Member first' },
    { key: 'newest',        label: 'Newest' },
    { key: 'oldest',        label: 'Oldest' },
]

function UsersTab({ authFetch, currentUsername, onToast }) {
    const [users, setUsers] = useState([])
    const [loading, setLoading] = useState(true)
    const [changingPw, setChangingPw] = useState(null)
    const [query, setQuery] = useState('')
    const [sortKey, setSortKey] = useState('username_asc')
    const [confirmDelete, setConfirmDelete] = useState(null)
    const [showAddMember, setShowAddMember] = useState(false)

    const load = useCallback(async () => {
        setLoading(true)
        try {
            const res = await authFetch('http://localhost:8000/api/auth/users')
            if (res.ok) setUsers(await res.json())
        } catch { /* ignore */ }
        finally { setLoading(false) }
    }, [authFetch])

    useEffect(() => { load() }, [load])

    const filtered = useMemo(() => {
        let list = [...users]
        if (query.trim()) {
            const q = query.toLowerCase()
            list = list.filter(u =>
                u.username.toLowerCase().includes(q) || u.role.toLowerCase().includes(q)
            )
        }
        list.sort((a, b) => {
            if (sortKey === 'username_asc')  return a.username.localeCompare(b.username)
            if (sortKey === 'username_desc') return b.username.localeCompare(a.username)
            if (sortKey === 'role_admin')    return a.role === 'admin' ? -1 : 1
            if (sortKey === 'role_member')   return a.role === 'member' ? -1 : 1
            if (sortKey === 'newest') return new Date(b.created_at||0) - new Date(a.created_at||0)
            if (sortKey === 'oldest') return new Date(a.created_at||0) - new Date(b.created_at||0)
            return 0
        })
        return list
    }, [users, query, sortKey])

    const handleDelete = async (username) => {
        try {
            const res = await authFetch(`http://localhost:8000/api/auth/users/${username}`, { method: 'DELETE' })
            const data = await res.json()
            if (!res.ok) { onToast({ text: data.detail || 'Failed', type: 'error' }); return }
            onToast({ text: data.message, type: 'success' })
            load()
        } catch { onToast({ text: 'Server error', type: 'error' }) }
        finally { setConfirmDelete(null) }
    }

    if (loading) return <div className="admin-loading"><Loader2 size={20} className="spin-icon" /> Loading users…</div>

    return (
        <div className="admin-section">
            <div className="admin-section-header">
                <span>{users.length} user{users.length !== 1 ? 's' : ''}</span>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="admin-add-btn" onClick={() => setShowAddMember(true)}>
                        <UserPlus size={13} /> Add Member
                    </button>
                    <button className="admin-refresh-btn" onClick={load} title="Refresh"><RefreshCw size={13} /></button>
                </div>
            </div>

            <div className="admin-filter-row">
                <SearchBar value={query} onChange={setQuery} placeholder="Search by username or role…" />
                <div className="admin-sort-wrap">
                    <ArrowUpDown size={13} className="admin-sort-icon" />
                    <select className="admin-sort-select" value={sortKey} onChange={e => setSortKey(e.target.value)}>
                        {USER_SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
                    </select>
                </div>
            </div>

            {filtered.length === 0 ? (
                <div className="admin-empty">
                    {query ? `No users matching "${query}"` : 'No users found.'}
                </div>
            ) : (
                <table className="admin-table">
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Role</th>
                            <th>Created</th>
                            <th style={{ textAlign: 'right' }}>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map(u => (
                            <tr key={u.username} className={u.username === currentUsername ? 'admin-table-row-self' : ''}>
                                <td>
                                    <span className="admin-username">{u.username}</span>
                                    {u.username === currentUsername && <span className="admin-you-badge">you</span>}
                                </td>
                                <td>
                                    <span className={`admin-role-badge ${u.role}`}>
                                        {u.role === 'admin' ? <ShieldCheck size={11} /> : <ShieldOff size={11} />}
                                        {u.role}
                                    </span>
                                </td>
                                <td className="admin-muted">
                                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                                </td>
                                <td>
                                    <div className="admin-actions-row">
                                        <button
                                            className="admin-action-btn"
                                            title="Change password"
                                            onClick={() => setChangingPw(u.username)}
                                        >
                                            <Key size={13} />
                                        </button>
                                        <button
                                            className="admin-action-btn danger"
                                            title={u.role === 'admin' ? 'Cannot delete admin' : 'Delete user'}
                                            disabled={u.role === 'admin' || u.username === currentUsername}
                                            onClick={() => setConfirmDelete(u.username)}
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}

            {changingPw && (
                <ChangePasswordModal
                    username={changingPw}
                    authFetch={authFetch}
                    onClose={() => setChangingPw(null)}
                    onSuccess={(msg) => { onToast({ text: msg, type: 'success' }); load() }}
                />
            )}

            {confirmDelete && (
                <ConfirmDeleteDialog
                    title={`Delete "${confirmDelete}"?`}
                    body={`This will permanently remove the user "${confirmDelete}". This cannot be undone.`}
                    onConfirm={() => handleDelete(confirmDelete)}
                    onClose={() => setConfirmDelete(null)}
                />
            )}

            {showAddMember && (
                <AddMemberModal
                    authFetch={authFetch}
                    onClose={() => setShowAddMember(false)}
                    onSuccess={(msg) => { onToast({ text: msg, type: 'success' }); load() }}
                />
            )}
        </div>
    )
}

// ── Drones Tab ────────────────────────────────────────────────────────────────
function DronesTab({ authFetch, onToast }) {
    const [drones, setDrones] = useState([])
    const [loading, setLoading] = useState(true)
    const [expanded, setExpanded] = useState({})
    const [busy, setBusy] = useState({})
    const [query, setQuery] = useState('')
    const [statusFilter, setStatusFilter] = useState('all')
    const [confirmDelete, setConfirmDelete] = useState(null)
    const [editingDrone, setEditingDrone] = useState(null) // drone_id
    const [showAddDrone, setShowAddDrone] = useState(false)

    const load = useCallback(async () => {
        setLoading(true)
        try {
            const res = await authFetch('http://localhost:8000/api/auth/drones')
            if (res.ok) setDrones(await res.json())
        } catch { /* ignore */ }
        finally { setLoading(false) }
    }, [authFetch])

    useEffect(() => { load() }, [load])

    const filtered = useMemo(() => {
        let list = drones
        if (statusFilter === 'active')  list = list.filter(d => d.status === 'active')
        if (statusFilter === 'stopped') list = list.filter(d => d.registry_status === 'stopped')
        if (query.trim()) {
            const q = query.toLowerCase()
            list = list.filter(d =>
                d.id?.toLowerCase().includes(q) ||
                d.name?.toLowerCase().includes(q) ||
                d.zone?.toLowerCase().includes(q) ||
                d.status?.toLowerCase().includes(q)
            )
        }
        return list
    }, [drones, query, statusFilter])

    const action = async (drone_id, endpoint, method = 'POST') => {
        setBusy(b => ({ ...b, [drone_id]: true }))
        try {
            const res = await authFetch(`http://localhost:8000/api/auth/drones/${endpoint}/${drone_id}`, { method })
            const data = await res.json()
            if (!res.ok) { onToast({ text: data.detail || 'Failed', type: 'error' }) }
            else { onToast({ text: data.message, type: 'success' }); load() }
        } catch { onToast({ text: 'Server error', type: 'error' }) }
        finally { setBusy(b => ({ ...b, [drone_id]: false })) }
    }

    const handleDelete = async (drone_id) => {
        setBusy(b => ({ ...b, [drone_id]: true }))
        try {
            const res = await authFetch(`http://localhost:8000/api/auth/drones/${drone_id}`, { method: 'DELETE' })
            const data = await res.json()
            if (!res.ok) { onToast({ text: data.detail || 'Failed', type: 'error' }) }
            else { onToast({ text: data.message, type: 'success' }); load() }
        } catch { onToast({ text: 'Server error', type: 'error' }) }
        finally { setBusy(b => ({ ...b, [drone_id]: false })); setConfirmDelete(null) }
    }

    const toggleExpand = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }))

    const activeDrones = filtered.filter(d => d.status === 'active')
    const idleDrones = filtered.filter(d => d.status !== 'active')

    if (loading) return <div className="admin-loading"><Loader2 size={20} className="spin-icon" /> Loading drones…</div>

    const STATUS_CHIPS = [
        { key: 'all',     label: 'All' },
        { key: 'active',  label: 'Active' },
        { key: 'stopped', label: 'Stopped' },
    ]

    const DroneRow = ({ drone }) => {
        const isBusy = busy[drone.id]
        const isActive = drone.status === 'active'
        const isStopped = drone.registry_status === 'stopped'

        return (
            <div className="admin-drone-row">
                <div className="admin-drone-header" onClick={() => toggleExpand(drone.id)}>
                    <div className="admin-drone-title">
                        <span className={`admin-drone-status-dot ${isActive ? 'active' : 'idle'}`} />
                        <span className="admin-drone-name">{drone.name}</span>
                        <span className="admin-drone-id">{drone.id}</span>
                        <span className={`admin-status-chip ${isStopped ? 'stopped' : isActive ? 'active' : 'idle'}`}>
                            {isStopped ? 'stopped' : drone.status}
                        </span>
                        {drone.pid && <span className="admin-drone-id">PID {drone.pid}</span>}
                    </div>
                    <div className="admin-drone-actions">
                        {isActive && (
                            <button
                                className="admin-action-btn danger"
                                title="Stop processing"
                                disabled={isBusy}
                                onClick={(e) => { e.stopPropagation(); action(drone.id, 'stop') }}
                            >
                                {isBusy ? <Loader2 size={13} className="spin-icon" /> : <Square size={13} />}
                            </button>
                        )}
                        {!isActive && isStopped && (
                            <button
                                className="admin-action-btn success"
                                title="Resume processing"
                                disabled={isBusy}
                                onClick={(e) => { e.stopPropagation(); action(drone.id, 'resume') }}
                            >
                                {isBusy ? <Loader2 size={13} className="spin-icon" /> : <Play size={13} />}
                            </button>
                        )}
                        <button
                            className="admin-action-btn"
                            title="Edit drone details"
                            disabled={isBusy}
                            onClick={(e) => { e.stopPropagation(); setEditingDrone(drone) }}
                        >
                            <Edit size={13} />
                        </button>
                        <button
                            className="admin-action-btn danger"
                            title="Delete drone permanently"
                            disabled={isBusy}
                            onClick={(e) => { e.stopPropagation(); setConfirmDelete(drone.id) }}
                        >
                            <Trash2 size={13} />
                        </button>
                        <button className="admin-action-btn" title="Expand details"
                            onClick={(e) => { e.stopPropagation(); toggleExpand(drone.id) }}>
                            {expanded[drone.id] ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                        </button>
                    </div>
                </div>

                {expanded[drone.id] && (
                    <div className="admin-drone-details">
                        <div className="admin-drone-detail-grid">
                            <div className="admin-detail-item">
                                <span className="admin-detail-label"><MapPin size={11} /> Location</span>
                                <span className="admin-detail-value">
                                    {drone.latitude && drone.longitude
                                        ? `${Number(drone.latitude).toFixed(4)}, ${Number(drone.longitude).toFixed(4)}`
                                        : 'Unavailable'}
                                </span>
                            </div>
                            <div className="admin-detail-item">
                                <span className="admin-detail-label"><Activity size={11} /> Altitude</span>
                                <span className="admin-detail-value">{drone.altitude ?? '—'}m</span>
                            </div>
                            <div className="admin-detail-item">
                                <span className="admin-detail-label">Zone</span>
                                <span className="admin-detail-value">{drone.zone || '—'}</span>
                            </div>
                            <div className="admin-detail-item">
                                <span className="admin-detail-label">Model</span>
                                <span className="admin-detail-value">{drone.model || (drone.config?.model) || '—'} / {drone.device || (drone.config?.device) || '—'}</span>
                            </div>
                            <div className="admin-detail-item">
                                <span className="admin-detail-label">FPS / Loop</span>
                                <span className="admin-detail-value">
                                    {drone.fps || drone.config?.fps || '—'} fps · {(drone.loop ?? drone.config?.loop) ? 'looping' : 'no loop'}
                                </span>
                            </div>
                            {drone.video_url && (
                                <div className="admin-detail-item" style={{ gridColumn: '1 / -1' }}>
                                    <span className="admin-detail-label">Stream Source</span>
                                    <span className="admin-detail-value admin-muted" style={{ wordBreak: 'break-all', fontSize: 11 }}>
                                        {drone.video_url}
                                    </span>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="admin-section">
            <div className="admin-section-header">
                <span>{drones.filter(d=>d.status==='active').length} active · {drones.filter(d=>d.status!=='active').length} idle/stopped</span>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="admin-add-btn" onClick={() => setShowAddDrone(true)}>
                        <PlusCircle size={13} /> Add Drone
                    </button>
                    <button className="admin-refresh-btn" onClick={load} title="Refresh"><RefreshCw size={13} /></button>
                </div>
            </div>

            <SearchBar value={query} onChange={setQuery} placeholder="Search by name, ID, zone…" />

            {/* Status chips */}
            <div className="admin-chip-row">
                {STATUS_CHIPS.map(c => (
                    <button key={c.key}
                        className={`admin-chip ${statusFilter === c.key ? 'active' : ''}`}
                        onClick={() => setStatusFilter(c.key)}>
                        {c.label}
                    </button>
                ))}
            </div>

            {drones.length === 0 && (
                <div className="admin-empty">No drones found. Use "Add Drone" to launch a stream processor.</div>
            )}

            {drones.length > 0 && filtered.length === 0 && (
                <div className="admin-empty">No drones match the current filters.</div>
            )}

            {activeDrones.length > 0 && (
                <>
                    <div className="admin-group-label">Active</div>
                    {activeDrones.map(d => <DroneRow key={d.id} drone={d} />)}
                </>
            )}
            {idleDrones.length > 0 && (
                <>
                    <div className="admin-group-label" style={{ marginTop: 16 }}>Idle / Stopped</div>
                    {idleDrones.map(d => <DroneRow key={d.id} drone={d} />)}
                </>
            )}

            {confirmDelete && (
                <ConfirmDeleteDialog
                    title={`Delete "${confirmDelete}"?`}
                    body={`This will permanently remove drone "${confirmDelete}" and stop any active stream. This cannot be undone.`}
                    onConfirm={() => handleDelete(confirmDelete)}
                    onClose={() => setConfirmDelete(null)}
                />
            )}

            {editingDrone && (
                <EditDroneModal
                    drone={editingDrone}
                    authFetch={authFetch}
                    onClose={() => setEditingDrone(null)}
                    onSuccess={(msg) => { onToast({ text: msg, type: 'success' }); load() }}
                />
            )}

            <AddDroneModal
                open={showAddDrone}
                authFetch={authFetch}
                onClose={() => setShowAddDrone(false)}
                onSuccess={(msg) => { onToast({ text: msg, type: 'success' }); load() }}
            />
        </div>
    )
}

// ── Main AdminPanel ───────────────────────────────────────────────────────────
export default function AdminPanel({ onClose }) {
    const { authFetch, user } = useAuth()
    const [tab, setTab] = useState('users')
    const [toast, setToast] = useState(null)

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-card admin-panel" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="modal-header">
                    <h2 className="modal-title">Admin Management Panel</h2>
                    <button className="modal-close" onClick={onClose}><X size={18} /></button>
                </div>

                {/* Tabs */}
                <div className="admin-tabs">
                    <button
                        className={`admin-tab ${tab === 'users' ? 'active' : ''}`}
                        onClick={() => setTab('users')}
                    >
                        <Users size={14} /> Users
                    </button>
                    <button
                        className={`admin-tab ${tab === 'drones' ? 'active' : ''}`}
                        onClick={() => setTab('drones')}
                    >
                        <Cpu size={14} /> Drones
                    </button>
                </div>

                {/* Content — both tabs stay mounted (hidden via CSS rather
                    than conditionally rendered) so switching tabs doesn't
                    unmount+remount them and re-trigger their loading spinner
                    every time; each fetches its data once and keeps it. */}
                <div className="admin-panel-body">
                    <div hidden={tab !== 'users'}>
                        <UsersTab
                            authFetch={authFetch}
                            currentUsername={user?.username}
                            onToast={setToast}
                        />
                    </div>
                    <div hidden={tab !== 'drones'}>
                        <DronesTab
                            authFetch={authFetch}
                            onToast={setToast}
                        />
                    </div>
                </div>

                {toast && <Toast msg={toast} onDone={() => setToast(null)} />}
            </div>
        </div>
    )
}
