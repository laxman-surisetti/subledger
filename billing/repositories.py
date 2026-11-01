"""Repository layer: the ONLY place that touches the Django ORM.
No business rules here; just queries and persistence."""
from typing import Optional

from .models import (
    Customer,
    Invoice,
    LedgerEntry,
    PaymentAttempt,
    Plan,
    Subscription,
)


class PlanRepository:
    def create(self, **fields) -> Plan:
        return Plan.objects.create(**fields)

    def get(self, plan_id: int) -> Optional[Plan]:
        return Plan.objects.filter(pk=plan_id).first()

    def list(self):
        return Plan.objects.order_by("id")


class CustomerRepository:
    def create(self, **fields) -> Customer:
        return Customer.objects.create(**fields)

    def get(self, customer_id: int) -> Optional[Customer]:
        return Customer.objects.filter(pk=customer_id).first()

    def get_by_email(self, email: str) -> Optional[Customer]:
        return Customer.objects.filter(email__iexact=email).first()

    def list(self):
        return Customer.objects.order_by("id")


class SubscriptionRepository:
    def create(self, **fields) -> Subscription:
        return Subscription.objects.create(**fields)

    def get(self, subscription_id: int) -> Optional[Subscription]:
        return (
            Subscription.objects.select_related("plan", "customer")
            .filter(pk=subscription_id)
            .first()
        )

    def get_for_update(self, subscription_id: int) -> Optional[Subscription]:
        return (
            Subscription.objects.select_for_update(of=("self",))
            .select_related("plan", "customer")
            .filter(pk=subscription_id)
            .first()
        )

    def has_active(self, customer_id: int, plan_id: int) -> bool:
        return Subscription.objects.filter(
            customer_id=customer_id, plan_id=plan_id, status=Subscription.Status.ACTIVE
        ).exists()

    def list_for_customer(self, customer_id: int):
        return Subscription.objects.filter(customer_id=customer_id).order_by("id")

    def save(self, subscription: Subscription) -> Subscription:
        subscription.save()
        return subscription


class InvoiceRepository:
    def create(self, **fields) -> Invoice:
        return Invoice.objects.create(**fields)

    def get(self, invoice_id: int) -> Optional[Invoice]:
        return Invoice.objects.filter(pk=invoice_id).first()

    def get_for_update(self, invoice_id: int) -> Optional[Invoice]:
        """Row lock so concurrent payments on one invoice are serialised."""
        return Invoice.objects.select_for_update().filter(pk=invoice_id).first()

    def exists_for_period(self, subscription_id: int, start, end) -> bool:
        return Invoice.objects.filter(
            subscription_id=subscription_id, period_start=start, period_end=end
        ).exists()

    def save(self, invoice: Invoice) -> Invoice:
        invoice.save()
        return invoice


class PaymentAttemptRepository:
    def create(self, **fields) -> PaymentAttempt:
        return PaymentAttempt.objects.create(**fields)

    def get_by_provider_reference(self, ref: str) -> Optional[PaymentAttempt]:
        return PaymentAttempt.objects.filter(provider_reference=ref).first()

    def list_for_invoice(self, invoice_id: int):
        return PaymentAttempt.objects.filter(invoice_id=invoice_id).order_by("id")


class LedgerRepository:
    """Append-only: exposes create + reads, deliberately no update/delete."""

    def create(self, **fields) -> LedgerEntry:
        return LedgerEntry.objects.create(**fields)

    def list_for_customer(self, customer_id: int):
        return LedgerEntry.objects.filter(customer_id=customer_id).order_by("id")

    def list_for_invoice(self, invoice_id: int):
        return LedgerEntry.objects.filter(invoice_id=invoice_id).order_by("id")
