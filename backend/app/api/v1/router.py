from fastapi import APIRouter

from app.api.v1.endpoints import agents, ai_sessions, auth, conversations, customers, dashboard, dev_messaging, health, knowledge, products, tickets

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(tickets.router, prefix="/tickets", tags=["tickets"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(ai_sessions.router, prefix="/ai-sessions", tags=["ai-sessions"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(dev_messaging.router, prefix="/dev/messaging", tags=["dev-messaging"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
