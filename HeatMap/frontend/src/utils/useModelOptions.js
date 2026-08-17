import { useState, useEffect } from 'react'

// Used only if the backend can't be reached — keeps the Add/Edit Drone forms
// usable, but the real list always comes from GET /api/auth/models (sourced
// from cv_pipeline/stream_config.py's MODEL_PRESETS) so a new model becomes
// selectable here automatically once it's added there.
const FALLBACK_MODELS = [
    { key: 'sdnet', label: 'SDNet (crowd density)' },
    { key: 'yolo', label: 'YOLO (object detection)' },
]

/**
 * Fetches the list of available detection models for the Add/Edit Drone
 * "Detection Model" dropdown. `authFetch` is the AuthContext helper that
 * attaches the admin bearer token.
 */
export function useModelOptions(authFetch) {
    const [models, setModels] = useState(FALLBACK_MODELS)

    useEffect(() => {
        let cancelled = false
        authFetch('http://localhost:8000/api/auth/models')
            .then(res => (res.ok ? res.json() : Promise.reject()))
            .then(data => {
                if (!cancelled && Array.isArray(data) && data.length) setModels(data)
            })
            .catch(() => { /* keep the fallback list */ })
        return () => { cancelled = true }
    }, [authFetch])

    return models
}
