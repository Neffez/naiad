from fastapi import APIRouter, Depends

from naiad import __version__
from naiad.dependencies import get_ha_client
from naiad.ha_client import HAClient

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health(ha: HAClient = Depends(get_ha_client)) -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ha_connected": ha.is_connected,
    }
