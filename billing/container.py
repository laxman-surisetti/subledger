"""Composition root: the one place where repositories are wired into services."""
from .repositories import (
    CustomerRepository,
    InvoiceRepository,
    LedgerRepository,
    PaymentAttemptRepository,
    PlanRepository,
    SubscriptionRepository,
)
from .services import (
    CustomerService,
    InvoiceService,
    LedgerService,
    PaymentService,
    PlanService,
    SubscriptionService,
)


def build_services():
    plan_repo = PlanRepository()
    customer_repo = CustomerRepository()
    subscription_repo = SubscriptionRepository()
    invoice_repo = InvoiceRepository()
    attempt_repo = PaymentAttemptRepository()
    ledger_service = LedgerService(LedgerRepository())

    class Services:
        plans = PlanService(plan_repo)
        customers = CustomerService(customer_repo)
        subscriptions = SubscriptionService(subscription_repo, customer_repo, plan_repo)
        invoices = InvoiceService(subscription_repo, plan_repo, invoice_repo, ledger_service)
        payments = PaymentService(invoice_repo, attempt_repo, ledger_service)
        ledger = ledger_service

    return Services
