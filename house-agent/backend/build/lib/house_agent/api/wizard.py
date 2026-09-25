from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..agent.claude_agent import AgentError
from ..agent.suggest import SuggestIn, SuggestOut, suggest_regions
from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/api/wizard", tags=["wizard"])


@router.post("/regions", response_model=SuggestOut)
def regions(body: SuggestIn, user: User = Depends(get_current_user)):
    try:
        return suggest_regions(body)
    except AgentError as e:
        raise HTTPException(503, str(e)) from e
