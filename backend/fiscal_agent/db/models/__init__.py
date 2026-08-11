"""Model registry — importing this module registers every table on ``Base.metadata``.

Required by Alembic autogenerate (``target_metadata`` must see all models).
"""

from fiscal_agent.db.models.business import (
    BillingEvent,
    Client,
    Conversation,
    GeneratedPdf,
    Invoice,
    Message,
    Payment,
    ReportRun,
    TokenBalance,
    TokenPackage,
    TokenTransaction,
)
from fiscal_agent.db.models.core import (
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
    'ApiKey',
    'App',
    'BillingEvent',
    'Client',
    'Conversation',
    'GeneratedPdf',
    'Invoice',
    'Message',
    'Payment',
    'Plan',
    'PlanPrice',
    'ReportRun',
    'Subscription',
    'Tenant',
    'TenantMember',
    'TokenBalance',
    'TokenPackage',
    'TokenTransaction',
    'User',
]