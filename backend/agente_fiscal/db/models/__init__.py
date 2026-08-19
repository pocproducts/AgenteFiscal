"""Model registry — importing this module registers every table on ``Base.metadata``.

Required by Alembic autogenerate (``target_metadata`` must see all models).
"""

from agente_fiscal.db.models.business import (
    AgentSession,
    BillingEvent,
    BrowserSession,
    Client,
    Conversation,
    GeneratedPdf,
    Invoice,
    Message,
    Payment,
    Profile,
    ReportRun,
    TokenBalance,
    TokenPackage,
    TokenTransaction,
)
from agente_fiscal.db.models.core import (
    ApiKey,
    App,
    Plan,
    PlanPrice,
    Subscription,
    Tenant,
    TenantMember,
    User,
)

__all__ = [
    'AgentSession',
    'ApiKey',
    'App',
    'BillingEvent',
    'BrowserSession',
    'Client',
    'Conversation',
    'GeneratedPdf',
    'Invoice',
    'Message',
    'Payment',
    'Plan',
    'PlanPrice',
    'Profile',
    'ReportRun',
    'Subscription',
    'Tenant',
    'TenantMember',
    'TokenBalance',
    'TokenPackage',
    'TokenTransaction',
    'User',
]