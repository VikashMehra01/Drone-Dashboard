from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.config import settings
from app.services.telegram_service import broadcast_alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

class AlertPayload(BaseModel):
    title: str
    message: str
    level: str = "critical"
    drone_name: str = "Unknown Drone"
    zone: Optional[str] = "Unknown Zone"
    latitude: Optional[float] = None
    longitude: Optional[float] = None

def verify_api_key(x_api_key: str = Header(...)):
    """
    Dependency to verify the API key matches the local secret.
    This restricts who can trigger automated Telegram broadcasts.
    """
    if x_api_key != settings.API_KEY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return x_api_key

@router.post("/broadcast")
async def broadcast_notification(payload: AlertPayload, key: str = Header(default=None)):
    """
    Endpoint triggered by the Frontend React application when the 
    sliding window density alert condition is met.
    Requires localhost/internal shared secret to prevent spam.
    """
    # Optional explicitly call out dependency (or you can use Depends(verify_api_key))
    if key != settings.API_KEY_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

    # Format the message for telegram
    emoji = "🚨" if payload.level.lower() == "critical" else "ℹ️"
    
    maps_link = ""
    if payload.latitude and payload.longitude:
        maps_link = f"\n🗺️ *Map:* [View on Google Maps](https://maps.google.com/?q={payload.latitude},{payload.longitude})"

    formatted_msg = (
        f"{emoji} *{payload.title}*\n\n"
        f"🚁 *Drone:* {payload.drone_name}\n"
        f"📍 *Zone:* {payload.zone}\n"
        f"📝 *Details:* {payload.message}{maps_link}\n"
    )

    success = await broadcast_alert(formatted_msg)
    
    if not success:
        # We don't want to crash the frontend flow, so just return accepted
        return {"status": "error", "message": "Failed to push to telegram."}

    return {"status": "success", "message": "Broadcasted."}
