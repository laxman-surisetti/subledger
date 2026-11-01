"""Models layer: table structure, DB-level constraints and tiny derived properties only.
No business workflows live here."""
from decimal import Decimal

from django.db import models
from django.db.models import Q


class Plan(models.Model):
    class Interval(models.TextChoices):
        MONTHLY = "monthly"
        YEARLY = "yearly"

    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    billing_interval = models.CharField(
        max_length=10, choices=Interval.choices, default=Interval.MONTHLY
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "plans"
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="plan_price_gt_0"),
        ]


class Customer(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customers"


class Subscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        CANCELLED = "cancelled"

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions"
        constraints = [
            # DB safety net for: one active subscription per customer per plan.
            models.UniqueConstraint(
                fields=["customer", "plan"],
                condition=Q(status="active"),
                name="uniq_active_subscription_per_customer_plan",
            ),
        ]


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        ISSUED = "issued"
        PARTIALLY_PAID = "partially_paid"
        PAID = "paid"
        VOID = "void"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="invoices"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="invoices"
    )
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ISSUED
    )
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "period_start", "period_end"],
                name="uniq_invoice_per_subscription_period",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=models.F("amount_due")),
                name="invoice_paid_within_due",
            ),
        ]

    @property
    def remaining(self) -> Decimal:
        return self.amount_due - self.amount_paid


class PaymentAttempt(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success"
        FAILED = "failed"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payment_attempts"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=10, choices=Status.choices)
    provider_reference = models.CharField(max_length=100, unique=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payment_attempts"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_gt_0"),
        ]


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("LedgerEntry is append-only: bulk update is not allowed")

    def delete(self):
        raise TypeError("LedgerEntry is append-only: delete is not allowed")


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        INVOICE_CREATED = "invoice_created"
        PAYMENT_SUCCESS = "payment_success"
        PAYMENT_FAILURE = "payment_failure"

    class Direction(models.TextChoices):
        DEBIT = "debit"  # increases what the customer owes
        CREDIT = "credit"  # reduces what the customer owes
        INFO = "info"  # informational, no balance impact

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    direction = models.CharField(max_length=6, choices=Direction.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    reference_id = models.CharField(max_length=64, db_index=True)
    description = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "ledger_entries"
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise TypeError("LedgerEntry is append-only: updates are not allowed")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("LedgerEntry is append-only: delete is not allowed")
