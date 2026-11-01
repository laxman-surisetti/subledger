"""Route layer: HTTP in/out only. Validate with schemas, delegate to services."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import schemas
from .container import build_services

svc = build_services()


class PlanListCreateView(APIView):
    def post(self, request):
        data = schemas.PlanCreateSchema(data=request.data)
        data.is_valid(raise_exception=True)
        plan = svc.plans.create_plan(**data.validated_data)
        return Response(schemas.PlanSchema(plan).data, status=status.HTTP_201_CREATED)

    def get(self, request):
        return Response(schemas.PlanSchema(svc.plans.list_plans(), many=True).data)


class CustomerListCreateView(APIView):
    def post(self, request):
        data = schemas.CustomerCreateSchema(data=request.data)
        data.is_valid(raise_exception=True)
        customer = svc.customers.create_customer(**data.validated_data)
        return Response(schemas.CustomerSchema(customer).data, status=status.HTTP_201_CREATED)

    def get(self, request):
        return Response(schemas.CustomerSchema(svc.customers.list_customers(), many=True).data)


class CustomerDetailView(APIView):
    def get(self, request, customer_id):
        return Response(schemas.CustomerSchema(svc.customers.get_customer(customer_id)).data)


class SubscriptionCreateView(APIView):
    def post(self, request):
        data = schemas.SubscriptionCreateSchema(data=request.data)
        data.is_valid(raise_exception=True)
        sub = svc.subscriptions.create_subscription(**data.validated_data)
        return Response(schemas.SubscriptionSchema(sub).data, status=status.HTTP_201_CREATED)


class SubscriptionDetailView(APIView):
    def get(self, request, subscription_id):
        sub = svc.subscriptions.get_subscription(subscription_id)
        return Response(schemas.SubscriptionSchema(sub).data)


class SubscriptionCancelView(APIView):
    def post(self, request, subscription_id):
        sub = svc.subscriptions.cancel_subscription(subscription_id)
        return Response(schemas.SubscriptionSchema(sub).data)


class CustomerSubscriptionsView(APIView):
    def get(self, request, customer_id):
        subs = svc.subscriptions.list_for_customer(customer_id)
        return Response(schemas.SubscriptionSchema(subs, many=True).data)


class InvoiceGenerateView(APIView):
    def post(self, request):
        data = schemas.InvoiceGenerateSchema(data=request.data)
        data.is_valid(raise_exception=True)
        invoice = svc.invoices.generate_invoice(**data.validated_data)
        return Response(schemas.InvoiceSchema(invoice).data, status=status.HTTP_201_CREATED)


class InvoiceDetailView(APIView):
    def get(self, request, invoice_id):
        return Response(schemas.InvoiceSchema(svc.invoices.get_invoice(invoice_id)).data)


class InvoiceLedgerView(APIView):
    def get(self, request, invoice_id):
        svc.invoices.get_invoice(invoice_id)  # 404 if missing
        entries = svc.ledger.invoice_ledger(invoice_id)
        return Response(schemas.LedgerEntrySchema(entries, many=True).data)


class PaymentCreateView(APIView):
    def post(self, request):
        data = schemas.PaymentCreateSchema(data=request.data)
        data.is_valid(raise_exception=True)
        attempt, invoice = svc.payments.record_payment(**data.validated_data)
        return Response(
            {
                "payment_attempt": schemas.PaymentAttemptSchema(attempt).data,
                "invoice": schemas.InvoiceSchema(invoice).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerLedgerView(APIView):
    def get(self, request, customer_id):
        svc.customers.get_customer(customer_id)  # 404 if missing
        entries = svc.ledger.customer_ledger(customer_id)
        return Response(schemas.LedgerEntrySchema(entries, many=True).data)
