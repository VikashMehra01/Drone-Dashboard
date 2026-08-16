import { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null)          // { username, role }
    const [token, setToken] = useState(null)
    const [loading, setLoading] = useState(true)

    // Restore session from localStorage on mount and verify it
    useEffect(() => {
        const verifySession = async () => {
            const storedToken = localStorage.getItem('sw_token')
            const storedUser = localStorage.getItem('sw_user')
            
            if (storedToken && storedUser) {
                try {
                    // Temporarily set them
                    setToken(storedToken)
                    setUser(JSON.parse(storedUser))
                    
                    // Verify token with backend
                    const res = await fetch('http://localhost:8000/api/auth/me', {
                        headers: { 'Authorization': `Bearer ${storedToken}` }
                    })
                    
                    if (!res.ok) {
                        throw new Error('Token invalid or expired')
                    }
                } catch {
                    setToken(null)
                    setUser(null)
                    localStorage.removeItem('sw_token')
                    localStorage.removeItem('sw_user')
                }
            }
            setLoading(false)
        }
        
        verifySession()
    }, [])

    const login = (tokenStr, userObj) => {
        setToken(tokenStr)
        setUser(userObj)
        localStorage.setItem('sw_token', tokenStr)
        localStorage.setItem('sw_user', JSON.stringify(userObj))
    }

    const logout = () => {
        setToken(null)
        setUser(null)
        localStorage.removeItem('sw_token')
        localStorage.removeItem('sw_user')
    }

    const authFetch = (url, options = {}) => {
        return fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
                ...(options.headers || {}),
            },
        })
    }

    return (
        <AuthContext.Provider value={{ user, token, login, logout, authFetch, loading }}>
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth() {
    const ctx = useContext(AuthContext)
    if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
    return ctx
}
