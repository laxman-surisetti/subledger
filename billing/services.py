"""Service layer: all business rules and workflows. Services receive repositories
through the constructor (dependency injection) and never import the ORM directly."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import IntegrityError, transaction

from .exceptions import BusinessRuleViolation, ConflictError, NotFoundError
from .models import Invoice, LedgerEntry, PaymentAttempt, Plan, Subscription


class PlanService:
    def __init__(self, plan_repo):
        self.plan_repo = plan_repo

    def create_plan(self, name, price, currency=None, billing_interval="monthly"):
        price = Decimal(price)
        if price <= 0:  # Rule: plan price > 0
            raise BusinessRuleViolation("Plan price must be greater than 0")
        return self.plan_repo.create(
            name=name,
            price=price,
            currency=(currency or settings.DEFAULT_CURRENCY).upper(),
            billing_interval=billing_interval,
        )

    def list_plans(self):
        return self.plan_repo.list()


class CustomerService:
    def __init__(self, customer_repo):
        self.customer_repo = customer_repo

    def create_customer(self, name, email):
        email = email.strip().lower()
        if self.customer_repo.get_by_email(email):  # Rule: unique email
            raise ConflictError("A customer with this email already exists")
        try:
            return self.customer_repo.create(name=name, email=email)
        except IntegrityError:  # race-condition fallback from DB unique index
            raise ConflictError("A customer with this email already exists")

    def get_customer(self, customer_id):
        customer = self.customer_repo.get(customer_id)
        if not customer:
            raise NotFoundError(f"Customer {customer_id} not found")
        return customer

    def list_customers(self):
        return self.customer_repo.list()


class LedgerService:
    """Single writer of ledger entries; keeps entry formats and reference_ids consistent."""

    def __init__(self, ledger_repo):
        self.ledger_repo = ledger_repo

    def record_invoice_created(self, invoice: Invoice) -> LedgerEntry:
        return self.ledger_repo.create(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            entry_type=LedgerEntry.EntryType.INVOICE_CREATED,
            direction=LedgerEntry.Direction.DEBIT,
            amount=invoice.amount_due,
            currency=invoice.currency,
            reference_id=f"INV-{invoice.id}",
            description=f"Invoice {invoice.id} issued for {invoice.period_start}..{invoice.period_end}",
        )

    def record_payment(self, invoice: Invoice, attempt: PaymentAttempt) -> LedgerEntry:
        success = attempt.status == PaymentAttempt.Status.SUCCESS
        return self.ledger_repo.create(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            entry_type=(
                LedgerEntry.EntryType.PAYMENT_SUCCESS
                if success
                else LedgerEntry.EntryType.PAYMENT_FAILURE
            ),
            direction=(
                LedgerEntry.Direction.CREDIT if success else LedgerEntry.Direction.INFO
            ),
            amount=attempt.amount,
            currency=attempt.currency,
            reference_id=f"PAY-{attempt.id}",
            description=(
                f"Payment {attempt.provider_reference} succeeded"
                if success
                else f"Payment {attempt.provider_reference} failed: {attempt.failure_reason}"
            ),
        )

    def customer_ledger(self, customer_id):
        return self.ledger_repo.list_for_customer(customer_id)

    def invoice_ledger(self, invoice_id):
        return self.ledger_repo.list_for_invoice(invoice_id)


class SubscriptionService:
    def __init__(self, subscription_repo, customer_repo, plan_repo):
        self.subscription_repo = subscription_repo
        self.customer_repo = customer_repo
        self.plan_repo = plan_repo

    @transaction.atomic
    def create_subscription(self, customer_id, plan_id, start_date: Optional[date] = None):
        customer = self.customer_repo.get(customer_id)
        if not customer:
            raise NotFoundError(f"Customer {customer_id} not found")
        plan = self.plan_repo.get(plan_id)
        if not plan:
            raise NotFoundError(f"Plan {plan_id} not found")
        if not plan.is_active:  # Rule: no subscription for inactive plan
            raise BusinessRuleViolation("Cannot subscribe to an inactive plan")
        if self.subscription_repo.has_active(customer_id, plan_id):  # Rule: no duplicates
            raise ConflictError("Customer already has an active subscription to this plan")
        try:
            with transaction.atomic():
                return self.subscription_repo.create(
                    customer_id=customer_id,
                    plan_id=plan_id,
                    status=Subscription.Status.ACTIVE,
                    start_date=start_date or date.today(),
                )
        except IntegrityError:
            raise ConflictError("Customer already has an active subscription to this plan")

    def get_subscription(self, subscription_id):
        sub = self.subscription_repo.get(subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription {subscription_id} not found")
        return sub

    def list_for_customer(self, customer_id):
        if not self.customer_repo.get(customer_id):
            raise NotFoundError(f"Customer {customer_id} not found")
        return self.subscription_repo.list_for_customer(customer_id)

    @transaction.atomic
    def cancel_subscription(self, subscription_id):
        sub = self.subscription_repo.get_for_update(subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription {subscription_id} not found")
        if sub.status == Subscription.Status.CANCELLED:
            raise ConflictError("Subscription is already cancelled")
        sub.status = Subscription.Status.CANCELLED
        sub.end_date = date.today()
        return self.subscription_repo.save(sub)


class InvoiceService:
    def __init__(self, subscription_repo, plan_repo, invoice_repo, ledger_service):
        self.subscription_repo = subscription_repo
        self.plan_repo = plan_repo
        self.invoice_repo = invoice_repo
        self.ledger_service = ledger_service

    @staticmethod
    def _period_end(start: date, interval: str) -> date:
        """End is exclusive-of-next-period: [start, start + interval - 1 day]."""
        if interval == Plan.Interval.YEARLY:
            return start + relativedelta(years=1) - timedelta(days=1)
        return start + relativedelta(months=1) - timedelta(days=1)

    @transaction.atomic
    def generate_invoice(
        self,
        subscription_id: int,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> Invoice:
        sub = self.subscription_repo.get_for_update(subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription {subscription_id} not found")
        if sub.status != Subscription.Status.ACTIVE:
            raise BusinessRuleViolation("Cannot invoice a non-active subscription")

        plan = sub.plan
        start = period_start or date.today()
        end = period_end or self._period_end(start, plan.billing_interval)
        if end < start:
            raise BusinessRuleViolation("period_end must not be before period_start")

        if self.invoice_repo.exists_for_period(sub.id, start, end):
            raise ConflictError("An invoice already exists for this billing period")

        # Rule: amount_due is a snapshot of the plan price at generation time.
        invoice = self.invoice_repo.create(
            subscription_id=sub.id,
            customer_id=sub.customer_id,
            amount_due=plan.price,
            amount_paid=Decimal("0.00"),
            currency=plan.currency,
            status=Invoice.Status.ISSUED,
            period_start=start,
            period_end=end,
            due_date=start + timedelta(days=settings.INVOICE_DUE_DAYS),
        )
        self.ledger_service.record_invoice_created(invoice)
        return invoice

    def get_invoice(self, invoice_id) -> Invoice:
        invoice = self.invoice_repo.get(invoice_id)
        if not invoice:
            raise NotFoundError(f"Invoice {invoice_id} not found")
        return invoice


class PaymentService:
    def __init__(self, invoice_repo, payment_attempt_repo, ledger_service):
        self.invoice_repo = invoice_repo
        self.payment_attempt_repo = payment_attempt_repo
        self.ledger_service = ledger_service

    @transaction.atomic
    def record_payment(
        self,
        invoice_id: int,
        amount,
        currency: str,
        status: str,
        provider_reference: str,
        failure_reason: str = "",
    ):
        amount = Decimal(amount)
        if amount <= 0:
            raise BusinessRuleViolation("Payment amount must be greater than 0")
        if status not in PaymentAttempt.Status.values:
            raise BusinessRuleViolation(f"status must be one of {PaymentAttempt.Status.values}")

        invoice = self.invoice_repo.get_for_update(invoice_id)  # row lock
        if not invoice:
            raise NotFoundError(f"Invoice {invoice_id} not found")
        if invoice.status in (Invoice.Status.PAID, Invoice.Status.VOID):
            raise ConflictError(f"Invoice is already {invoice.status}; no further payments accepted")
        if currency.upper() != invoice.currency:
            raise BusinessRuleViolation("Payment currency does not match invoice currency")
        if self.payment_attempt_repo.get_by_provider_reference(provider_reference):
            raise ConflictError("A payment with this provider_reference was already recorded")

        success = status == PaymentAttempt.Status.SUCCESS
        if success and amount > invoice.remaining:  # Rule: no overpayment
            raise BusinessRuleViolation(
                f"Payment {amount} exceeds remaining unpaid amount {invoice.remaining}"
            )

        attempt = self.payment_attempt_repo.create(
            invoice_id=invoice.id,
            amount=amount,
            currency=invoice.currency,
            status=status,
            provider_reference=provider_reference,
            failure_reason="" if success else (failure_reason or "unspecified"),
        )

        if success:  # Rule: only success changes amount_paid / status
            invoice.amount_paid += amount
            invoice.status = (
                Invoice.Status.PAID
                if invoice.amount_paid == invoice.amount_due
                else Invoice.Status.PARTIALLY_PAID
            )
            self.invoice_repo.save(invoice)

        self.ledger_service.record_payment(invoice, attempt)
        return attempt, invoice
