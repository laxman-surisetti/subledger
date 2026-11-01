"""Schema layer: request validation (shape/type only) and response serialization."""
from decimal import Decimal

from rest_framework import serializers

from .models import (
    Customer,
    Invoice,
    LedgerEntry,
    PaymentAttempt,
    Plan,
    Subscription,
)

MONEY = dict(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


# ---- Requests -------------------------------------------------------------
class PlanCreateSchema(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    price = serializers.DecimalField(**MONEY)
    currency = serializers.CharField(max_length=3, required=False)
    billing_interval = serializers.ChoiceField(
        choices=Plan.Interval.choices, default=Plan.Interval.MONTHLY
    )


class CustomerCreateSchema(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()


class SubscriptionCreateSchema(serializers.Serializer):
    customer_id = serializers.IntegerField()
    plan_id = serializers.IntegerField()
    start_date = serializers.DateField(required=False)


class InvoiceGenerateSchema(serializers.Serializer):
    subscription_id = serializers.IntegerField()
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)


class PaymentCreateSchema(serializers.Serializer):
    invoice_id = serializers.IntegerField()
    amount = serializers.DecimalField(**MONEY)
    currency = serializers.CharField(max_length=3)
    status = serializers.ChoiceField(choices=PaymentAttempt.Status.choices)
    provider_reference = serializers.CharField(max_length=100)
    failure_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


# ---- Responses ------------------------------------------------------------
class PlanSchema(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "name", "price", "currency", "billing_interval", "is_active", "created_at"]


class CustomerSchema(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "email", "created_at"]


class SubscriptionSchema(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ["id", "customer_id", "plan_id", "status", "start_date", "end_date", "created_at"]


class InvoiceSchema(serializers.ModelSerializer):
    remaining = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "subscription_id", "customer_id", "amount_due", "amount_paid", "remaining",
            "currency", "status", "period_start", "period_end", "due_date", "created_at",
        ]


class PaymentAttemptSchema(serializers.ModelSerializer):
    class Meta:
        model = PaymentAttempt
        fields = [
            "id", "invoice_id", "amount", "currency", "status",
            "provider_reference", "failure_reason", "created_at",
        ]


class LedgerEntrySchema(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = [
            "id", "customer_id", "invoice_id", "entry_type", "direction", "amount",
            "currency", "reference_id", "description", "created_at",
        ]
