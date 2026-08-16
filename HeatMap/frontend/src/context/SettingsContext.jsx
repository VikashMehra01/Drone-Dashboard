import { createContext, useContext, useState, useEffect } from 'react'

const SettingsContext = createContext()

export function SettingsProvider({ children }) {
    const [hideFleetLabels, setHideFleetLabels] = useState(() => {
        return localStorage.getItem('hideFleetLabels') === 'true'
    })
    const [dashboardTextSize, setDashboardTextSize] = useState(() => {
        return localStorage.getItem('dashboardTextSize') || 'medium'
    })
    const [showLivePanelInfo, setShowLivePanelInfo] = useState(() => {
        return localStorage.getItem('showLivePanelInfo') !== 'false'
    })
    const [theme, setTheme] = useState(() => {
        return localStorage.getItem('theme') || 'light'
    })

    useEffect(() => {
        localStorage.setItem('hideFleetLabels', hideFleetLabels)
        localStorage.setItem('dashboardTextSize', dashboardTextSize)
        localStorage.setItem('showLivePanelInfo', showLivePanelInfo)
        localStorage.setItem('theme', theme)

        let scale = 1;
        if (dashboardTextSize === 'very-small') scale = 0.75;
        if (dashboardTextSize === 'small') scale = 0.85;
        if (dashboardTextSize === 'large') scale = 1.25;
        if (dashboardTextSize === 'very-large') scale = 1.5;
        
        document.documentElement.style.setProperty('--text-scale', scale);

        if (theme === 'light') {
            document.body.classList.add('light-mode')
        } else {
            document.body.classList.remove('light-mode')
        }
    }, [hideFleetLabels, dashboardTextSize, showLivePanelInfo, theme])

    return (
        <SettingsContext.Provider value={{ 
            hideFleetLabels, setHideFleetLabels, 
            dashboardTextSize, setDashboardTextSize, 
            showLivePanelInfo, setShowLivePanelInfo,
            theme, setTheme
        }}>
            {children}
        </SettingsContext.Provider>
    )
}

export const useSettings = () => useContext(SettingsContext)
