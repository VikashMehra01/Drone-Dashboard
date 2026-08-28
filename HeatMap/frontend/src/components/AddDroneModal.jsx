import { useState } from 'react'
import { useModelOptions } from '../utils/useModelOptions'

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

// Shared between the sidebar's quick-access button and the Manage panel's
// Drones tab — launching a drone is common enough to deserve both entry
// points, unlike Add Member which only lives in Manage now.
export default function AddDroneModal({ open, onClose, authFetch, onSuccess = () => {} }) {
    const init = { drone_id: '', drone_name: '', source: '', latitude: '', longitude: '', altitude: '100', zone: 'Live Stream Zone', fps: '5', loop: false, model: 'sdnet', device: 'cpu' }
    const [form, setForm] = useState(init)
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState(null)   // { text, severity }
    const modelOptions = useModelOptions(authFetch)

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
            else {
                setMsg({ text: data.message, severity: 'success' })
                onSuccess(data.message)
                setTimeout(handleClose, 2000)
            }
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
                            placeholder: '../media/videos/droneVid.mp4  ·  rtsp://192.168.1.10:554/live  ·  rtmp://localhost:1935/mystream',
                            helperText: 'File path (relative to cv_pipeline/), or an RTSP / RTMP / HTTP stream URL'
                        })}

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                            {field('Latitude *', 'latitude', { type: 'number', slotProps: { htmlInput: { step: 'any' } }, placeholder: '28.6139' })}
                            {field('Longitude *', 'longitude', { type: 'number', slotProps: { htmlInput: { step: 'any' } }, placeholder: '77.2090' })}
                            {field('Altitude (m)', 'altitude', { type: 'number' })}
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            {field('Zone Name', 'zone')}
                            {field('FPS', 'fps', { type: 'number', slotProps: { htmlInput: { min: 1, max: 30 } } })}
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            <TextField
                                select label="Detection Model" value={form.model} size="small" fullWidth
                                onChange={e => set('model', e.target.value)}
                                slotProps={{ select: { MenuProps: { disablePortal: true } } }}
                            >
                                {modelOptions.map(m => (
                                    <MenuItem key={m.key} value={m.key}>{m.label}</MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                select label="Device" value={form.device} size="small" fullWidth
                                onChange={e => set('device', e.target.value)}
                                slotProps={{ select: { MenuProps: { disablePortal: true } } }}
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
