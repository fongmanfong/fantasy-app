from .auth import router as auth_router
from .leagues import router as leagues_router
from .teams import router as teams_router
from .agent import router as agent_router

__all__ = ["auth_router", "leagues_router", "teams_router", "agent_router"]
