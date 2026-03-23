from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from ..database.connection import get_db
from ..services.agent_service import AgentService

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    league_id: int


class RecommendationRequest(BaseModel):
    league_id: int


@router.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        svc = AgentService(db)
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        response = svc.chat(messages, req.league_id)
        return {"response": response}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@router.post("/recommendations")
def get_recommendations(req: RecommendationRequest, db: Session = Depends(get_db)):
    try:
        svc = AgentService(db)
        response = svc.generate_recommendations(req.league_id)
        return {"recommendations": response}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
