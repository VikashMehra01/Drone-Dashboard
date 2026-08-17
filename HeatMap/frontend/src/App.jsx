import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Navbar from './components/Navbar'
import ProtectedRoute from './components/ProtectedRoute'
import { NotificationProvider } from './context/NotificationContext'
import { SettingsProvider } from './context/SettingsContext'
import { AuthProvider } from './context/AuthContext'
import { DronesProvider } from './context/DronesContext'
import Dashboard from './pages/Dashboard'
import DroneFeed from './pages/DroneFeed'
import Analytics from './pages/Analytics'
import About from './pages/About'
import Login from './pages/Login'
import { useSettings } from './context/SettingsContext'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import { useMemo } from 'react'

function AppContent() {
  const { theme } = useSettings()

  const muiTheme = useMemo(
    () =>
      createTheme({
        palette: {
          mode: theme === 'dark' ? 'dark' : 'light',
          primary: {
            main: '#3b82f6',
          },
        },
        zIndex: {
          modal: 99999,
          popover: 99999,
          tooltip: 99999,
        },
        typography: {
          fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        },
        components: {
          MuiPaper: {
            styleOverrides: {
              root: {
                backgroundColor: 'var(--color-bg-card)',
                color: 'var(--color-text-primary)',
                backgroundImage: 'none',
              }
            }
          },
          MuiMenu: {
            styleOverrides: {
              paper: {
                backgroundColor: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }
            }
          },
          MuiMenuItem: {
            styleOverrides: {
              root: {
                color: 'var(--color-text-primary)',
                '&:hover': {
                  backgroundColor: 'var(--color-bg-card-hover)',
                },
                '&.Mui-selected': {
                  backgroundColor: 'var(--color-bg-card-hover)',
                  '&:hover': {
                    backgroundColor: 'var(--color-bg-card-hover)',
                  }
                }
              }
            }
          },
          MuiOutlinedInput: {
            styleOverrides: {
              root: {
                color: 'var(--color-text-primary)',
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: 'var(--color-border)',
                },
                '&:hover .MuiOutlinedInput-notchedOutline': {
                  borderColor: 'var(--color-border-light)',
                },
                '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                  borderColor: 'var(--color-accent-blue)',
                },
              }
            }
          },
          MuiSelect: {
            styleOverrides: {
              icon: {
                color: 'var(--color-text-secondary)',
              }
            }
          }
        }
      }),
    [theme]
  )

  return (
    <ThemeProvider theme={muiTheme}>
      <AuthProvider>
        <NotificationProvider>
          <Routes>
            {/* Public */}
            <Route path="/login" element={<Login />} />

            {/* Protected — full dashboard layout */}
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <DronesProvider>
                    <div className="app-layout">
                      <Sidebar />
                      <div className="main-content">
                        <Navbar />
                        <div className="page-content">
                          <Routes>
                            <Route path="/" element={<Dashboard />} />
                            <Route path="/feeds" element={<DroneFeed />} />
                            <Route path="/analytics" element={<Analytics />} />
                            <Route path="/about" element={<About />} />
                          </Routes>
                        </div>
                      </div>
                    </div>
                  </DronesProvider>
                </ProtectedRoute>
              }
            />
          </Routes>
        </NotificationProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}

function App() {
  return (
    <SettingsProvider>
      <AppContent />
    </SettingsProvider>
  )
}

export default App
