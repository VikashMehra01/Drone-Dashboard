import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
    Box, Typography, TextField, Button, IconButton,
    InputAdornment, Alert, CircularProgress, Paper,
    ThemeProvider, createTheme, CssBaseline, Chip
} from '@mui/material'
import { Visibility, VisibilityOff, SecurityOutlined } from '@mui/icons-material'

// ── Light-ish login theme ─────────────────────────────────────────────────────
const theme = createTheme({
    palette: {
        mode: 'light',
        primary: { main: '#2563eb' },
        background: { default: '#e8f0fe', paper: 'rgba(255,255,255,0.80)' },
        text: { primary: '#1e293b', secondary: '#64748b' },
    },
    typography: {
        fontFamily: '"Inter", system-ui, sans-serif',
    },
    shape: { borderRadius: 12 },
    components: {
        MuiTextField: {
            styleOverrides: {
                root: {
                    '& .MuiOutlinedInput-root': {
                        background: 'rgba(255,255,255,0.6)',
                        borderRadius: 10,
                        transition: 'all 0.2s',
                        '& fieldset': { borderColor: 'rgba(37,99,235,0.2)' },
                        '&:hover fieldset': { borderColor: 'rgba(37,99,235,0.5)' },
                        '&.Mui-focused fieldset': { borderColor: '#2563eb', borderWidth: 1.5 },
                    },
                    '& .MuiInputLabel-root.Mui-focused': { color: '#2563eb' },
                },
            },
        },
        MuiButton: {
            styleOverrides: {
                root: {
                    textTransform: 'none',
                    fontWeight: 700,
                    fontSize: 15,
                    letterSpacing: 0.5,
                    borderRadius: 10,
                },
            },
        },
    },
})

// ── Animated canvas radar ─────────────────────────────────────────────────────
function RadarCanvas() {
    const canvasRef = useRef(null)
    useEffect(() => {
        const canvas = canvasRef.current
        if (!canvas) return
        const ctx = canvas.getContext('2d')
        let angle = 0
        let raf

        const resize = () => {
            canvas.width = canvas.offsetWidth
            canvas.height = canvas.offsetHeight
        }
        resize()
        window.addEventListener('resize', resize)

        // Random blips
        const blips = Array.from({ length: 8 }, () => ({
            r: Math.random() * 0.42 + 0.05,
            a: Math.random() * Math.PI * 2,
            life: 0,
            maxLife: Math.random() * 80 + 40,
        }))

        const draw = () => {
            const { width: W, height: H } = canvas
            ctx.clearRect(0, 0, W, H)
            const cx = W / 2, cy = H / 2
            const R = Math.min(W, H) * 0.45

            // Concentric rings
            for (let i = 1; i <= 4; i++) {
                ctx.beginPath()
                ctx.arc(cx, cy, R * i / 4, 0, Math.PI * 2)
                ctx.strokeStyle = `rgba(56,189,248,${0.06 + i * 0.02})`
                ctx.lineWidth = 1
                ctx.stroke()
            }

            // Cross hairs
            ctx.strokeStyle = 'rgba(56,189,248,0.08)'
            ctx.lineWidth = 1
            ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke()

            // Sweep gradient
            const sweep = ctx.createConicalGradient
                ? ctx.createConicalGradient(cx, cy, angle)
                : null

            // Manual sweep via arc fill
            const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R)
            grad.addColorStop(0, 'rgba(56,189,248,0.25)')
            grad.addColorStop(1, 'rgba(56,189,248,0)')
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(cx, cy)
            ctx.arc(cx, cy, R, angle - 1.2, angle)
            ctx.closePath()
            ctx.fillStyle = grad
            ctx.fill()
            ctx.restore()

            // Sweep line
            ctx.beginPath()
            ctx.moveTo(cx, cy)
            ctx.lineTo(cx + Math.cos(angle) * R, cy + Math.sin(angle) * R)
            ctx.strokeStyle = 'rgba(56,189,248,0.7)'
            ctx.lineWidth = 1.5
            ctx.stroke()

            // Blips
            blips.forEach(b => {
                const da = ((angle - b.a) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2)
                if (da < 0.15) b.life = b.maxLife
                if (b.life > 0) {
                    const bx = cx + Math.cos(b.a) * b.r * R * 2
                    const by = cy + Math.sin(b.a) * b.r * R * 2
                    const alpha = b.life / b.maxLife
                    ctx.beginPath()
                    ctx.arc(bx, by, 3, 0, Math.PI * 2)
                    ctx.fillStyle = `rgba(56,189,248,${alpha})`
                    ctx.fill()
                    ctx.beginPath()
                    ctx.arc(bx, by, 8, 0, Math.PI * 2)
                    ctx.strokeStyle = `rgba(56,189,248,${alpha * 0.4})`
                    ctx.lineWidth = 1
                    ctx.stroke()
                    b.life--
                }
            })

            angle = (angle + 0.025) % (Math.PI * 2)
            raf = requestAnimationFrame(draw)
        }
        draw()
        return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize) }
    }, [])

    return <canvas ref={canvasRef} style={{ width: '100%', height: '100%' }} />
}

// ── Light grid background ─────────────────────────────────────────────────────
function GridBg() {
    return (
        <Box sx={{
            position: 'absolute', inset: 0, zIndex: 0,
            backgroundImage: `
                radial-gradient(circle at 30% 20%, rgba(37,99,235,0.10) 0%, transparent 55%),
                radial-gradient(circle at 80% 75%, rgba(99,102,241,0.08) 0%, transparent 50%)
            `,
            '&::before': {
                content: '""', position: 'absolute', inset: 0,
                backgroundImage: `
                    linear-gradient(rgba(37,99,235,0.06) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(37,99,235,0.06) 1px, transparent 1px)
                `,
                backgroundSize: '48px 48px',
            },
        }} />
    )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Login() {
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [showPw, setShowPw] = useState(false)
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)
    const { login, user } = useAuth()
    const navigate = useNavigate()

    // Redirect to dashboard if already logged in
    useEffect(() => {
        if (user) {
            navigate('/', { replace: true })
        }
    }, [user, navigate])


    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!username.trim() || !password.trim()) { setError('Please fill in all fields.'); return }
        setLoading(true); setError('')
        try {
            const res = await fetch('http://localhost:8000/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            })
            const data = await res.json()
            if (!res.ok) setError(data.detail || 'Invalid credentials.')
            else { login(data.access_token, { username: data.username, role: data.role }); navigate('/', { replace: true }) }
        } catch { setError('Cannot reach the server. Is the backend running?') }
        finally { setLoading(false) }
    }

    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <Box sx={{
                minHeight: '100vh', width: '100%', display: 'flex', flex: 1,
                background: 'linear-gradient(140deg, #dbeafe 0%, #ede9fe 50%, #e0f2fe 100%)',
                position: 'relative', overflow: 'hidden',
            }}>
                <GridBg />

                {/* ── LEFT panel — brand + radar ─────────────────────── */}
                <Box sx={{
                    display: { xs: 'none', md: 'flex' },
                    flex: 1, flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                    position: 'relative', p: 6, zIndex: 1,
                    textAlign: 'center',
                }}>
                    {/* Drone watermark */}
                    <Box
                        component="img"
                        src="/drone_watermark.png"
                        alt=""
                        aria-hidden="true"
                        sx={{
                            position: 'absolute',
                            width: '85%', maxWidth: 500,
                            opacity: 0.08,
                            top: '50%', left: '50%',
                            transform: 'translate(-50%, -50%)',
                            pointerEvents: 'none',
                            userSelect: 'none',
                            filter: 'blur(1px) saturate(0.5)',
                        }}
                    />

                    {/* Brand */}
                    <Box sx={{ textAlign: 'center', mb: 5 }}>
                        <Box sx={{
                            width: 80, height: 80, borderRadius: '50%',
                            background: 'linear-gradient(135deg, #2563eb 0%, #6366f1 100%)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            mx: 'auto', mb: 3,
                            boxShadow: '0 8px 32px rgba(37,99,235,0.28)',
                            animation: 'logo-pulse 3s ease-in-out infinite',
                        }}>
                            <SecurityOutlined sx={{ fontSize: 40, color: '#fff' }} />
                        </Box>
                        <Typography variant="h3" fontWeight={800} sx={{
                            background: 'linear-gradient(90deg, #2563eb 0%, #6366f1 100%)',
                            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                            letterSpacing: '-0.03em', mb: 1.5,
                        }}>
                            SkyWatch
                        </Typography>
                        <Typography variant="body1" sx={{
                            maxWidth: 300, mx: 'auto', lineHeight: 1.8,
                            color: '#334155',
                            fontWeight: 500,
                            fontSize: '1rem',
                        }}>
                            AI-powered drone fleet surveillance —{' '}
                            <Box component="span" sx={{ color: '#2563eb', fontWeight: 700 }}>monitor</Box>,{' '}
                            <Box component="span" sx={{ color: '#6366f1', fontWeight: 700 }}>manage</Box>{' '}and{' '}
                            <Box component="span" sx={{ color: '#0891b2', fontWeight: 700 }}>respond</Box>{' '}in real time.
                        </Typography>
                    </Box>

                    {/* Radar */}
                    <Box sx={{
                        width: 280, height: 280,
                        borderRadius: '50%',
                        border: '1.5px solid rgba(37,99,235,0.2)',
                        overflow: 'hidden',
                        boxShadow: '0 0 40px rgba(37,99,235,0.1) inset, 0 8px 32px rgba(37,99,235,0.1)',
                        position: 'relative',
                        background: 'rgba(255,255,255,0.3)',
                        backdropFilter: 'blur(4px)',
                    }}>
                        <RadarCanvas />
                        {/* Center dot */}
                        <Box sx={{
                            position: 'absolute', top: '50%', left: '50%',
                            transform: 'translate(-50%,-50%)',
                            width: 8, height: 8, borderRadius: '50%',
                            background: '#2563eb',
                            boxShadow: '0 0 12px rgba(37,99,235,0.9)',
                        }} />
                    </Box>

                </Box>

                {/* Vertical divider */}
                <Box sx={{
                    display: { xs: 'none', md: 'block' },
                    width: '1px',
                    background: 'linear-gradient(to bottom, transparent, rgba(37,99,235,0.18) 30%, rgba(37,99,235,0.18) 70%, transparent)',
                    alignSelf: 'stretch', my: 6, zIndex: 1,
                }} />

                {/* ── RIGHT panel — login form ────────────────────────── */}
                <Box sx={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    p: { xs: 3, md: 6 },
                    zIndex: 1,
                    position: 'relative',
                    overflow: 'hidden',
                }}>
                    {/* Drone image as full-cover background */}
                    <Box
                        component="img"
                        src="/drone_bg.png"
                        alt=""
                        aria-hidden="true"
                        sx={{
                            position: 'absolute', inset: 0,
                            width: '100%', height: '100%',
                            objectFit: 'cover', objectPosition: 'center',
                        }}
                    />
                    {/* Overlay to keep card readable */}
                    <Box sx={{
                        position: 'absolute', inset: 0,
                        background: 'rgba(232,240,254,0.55)',
                        backdropFilter: 'blur(2px)',
                        pointerEvents: 'none',
                    }} />

                    <Paper elevation={3} sx={{
                        width: '100%', maxWidth: 420, p: 5,
                        border: '1px solid rgba(37,99,235,0.12)',
                        backdropFilter: 'blur(24px)',
                        background: 'rgba(255,255,255,0.92)',
                        borderRadius: 4,
                        position: 'relative', zIndex: 1,
                    }}>
                        {/* Header */}
                        <Box sx={{ mb: 4 }}>
                            <Chip
                                label="● SECURE LOGIN"
                                size="small"
                                sx={{
                                    mb: 2, fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
                                    bgcolor: 'rgba(37,99,235,0.08)', color: '#2563eb',
                                    border: '1px solid rgba(37,99,235,0.2)',
                                    '& .MuiChip-label': { px: 1.5 },
                                }}
                            />
                            <Typography variant="h4" fontWeight={800} sx={{ color: '#1e293b', lineHeight: 1.2, letterSpacing: '-0.02em' }}>
                                Welcome to<br />
                                <Box component="span" sx={{
                                    background: 'linear-gradient(90deg, #2563eb, #6366f1)',
                                    WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                                }}>
                                    SkyWatch
                                </Box>
                            </Typography>
                            <Typography variant="body2" sx={{ mt: 1.5, color: '#64748b' }}>
                                Enter your credentials to continue
                            </Typography>
                        </Box>

                        {/* Form */}
                        <Box component="form" onSubmit={handleSubmit} noValidate>
                            <TextField
                                fullWidth label="Username" id="login-username"
                                autoComplete="username" autoFocus
                                value={username}
                                onChange={e => { setUsername(e.target.value); setError('') }}
                                sx={{ mb: 2.5 }}
                            />
                            <TextField
                                fullWidth label="Password" id="login-password"
                                type={showPw ? 'text' : 'password'}
                                autoComplete="current-password"
                                value={password}
                                onChange={e => { setPassword(e.target.value); setError('') }}
                                slotProps={{
                                    input: {
                                        endAdornment: (
                                            <InputAdornment position="end">
                                                <IconButton
                                                    onClick={() => setShowPw(v => !v)}
                                                    edge="end" size="small"
                                                    aria-label={showPw ? 'Hide password' : 'Show password'}
                                                    sx={{ color: '#64748b', '&:hover': { color: '#2563eb' } }}
                                                >
                                                    {showPw
                                                        ? <VisibilityOff sx={{ fontSize: 20 }} />
                                                        : <Visibility sx={{ fontSize: 20 }} />}
                                                </IconButton>
                                            </InputAdornment>
                                        ),
                                    }
                                }}
                                sx={{ mb: error ? 2.5 : 3.5 }}
                            />

                            {error && (
                                <Alert severity="error" sx={{
                                    mb: 3, py: 1,
                                    bgcolor: 'rgba(239,68,68,0.06)',
                                    color: '#b91c1c',
                                    border: '1px solid rgba(239,68,68,0.2)',
                                    '& .MuiAlert-icon': { color: '#dc2626' },
                                }}>
                                    {error}
                                </Alert>
                            )}

                            <Button
                                type="submit" id="login-submit-btn"
                                fullWidth variant="contained" disabled={loading}
                                sx={{
                                    py: 1.6, mb: 1,
                                    background: 'linear-gradient(90deg, #2563eb 0%, #6366f1 100%)',
                                    fontSize: 15, fontWeight: 700,
                                    boxShadow: '0 4px 20px rgba(37,99,235,0.25)',
                                    '&:hover': {
                                        background: 'linear-gradient(90deg, #1d4ed8 0%, #4f46e5 100%)',
                                        boxShadow: '0 6px 28px rgba(37,99,235,0.38)',
                                        transform: 'translateY(-1px)',
                                    },
                                    '&:disabled': { opacity: 0.7 },
                                    transition: 'all 0.2s ease',
                                }}
                            >
                                {loading
                                    ? <CircularProgress size={22} sx={{ color: 'rgba(255,255,255,0.9)' }} />
                                    : 'Sign In'}
                            </Button>
                        </Box>
                    </Paper>
                </Box>
            </Box>

            <style>{`
                @keyframes logo-pulse {
                    0%, 100% { box-shadow: 0 0 40px rgba(37,99,235,0.30), 0 0 80px rgba(37,99,235,0.10); }
                    50%       { box-shadow: 0 0 60px rgba(37,99,235,0.45), 0 0 120px rgba(99,102,241,0.18); }
                }
            `}</style>
        </ThemeProvider>
    )
}
