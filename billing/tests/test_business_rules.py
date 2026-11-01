from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from billing.models import Invoice, LedgerEntry, PaymentAttempt

API = "/api/v1"


class BillingTestBase(TestCase):
    def setUp(self):
        self.c = APIClient()

    def make_plan(self, price="1000.00", **extra):
        r = self.c.post(f"{API}/plans/", {"name": "Pro", "price": price, **extra}, format="json")
        return r

    def make_customer(self, email="a@example.com"):
        return self.c.post(f"{API}/customers/", {"name": "Acme", "email": email}, format="json")

    def make_subscription(self, customer_id, plan_id):
        return self.c.post(
            f"{API}/subscriptions/", {"customer_id": customer_id, "plan_id": plan_id}, format="json"
        )

    def make_invoice(self, price="1000.00"):
        plan = self.make_plan(price).json()
        cust = self.make_customer().json()
        sub = self.make_subscription(cust["id"], plan["id"]).json()
        inv = self.c.post(f"{API}/invoices/generate/", {"subscription_id": sub["id"]}, format="json")
        return plan, cust, sub, inv.json()

    def pay(self, invoice_id, amount, status="success", ref="ref-1", currency="INR", **extra):
        return self.c.post(
            f"{API}/payments/",
            {"invoice_id": invoice_id, "amount": amount, "currency": currency,
             "status": status, "provider_reference": ref, **extra},
            format="json",
        )


class PlanAndCustomerRules(BillingTestBase):
    def test_plan_price_must_be_greater_than_zero(self):
        self.assertEqual(self.make_plan("0").status_code, 400)
        self.assertEqual(self.make_plan("-5").status_code, 400)
        self.assertEqual(self.make_plan("10.00").status_code, 201)

    def test_customer_email_must_be_unique(self):
        self.assertEqual(self.make_customer("dup@example.com").status_code, 201)
        r = self.make_customer("DUP@example.com")
        self.assertEqual(r.status_code, 409)


class SubscriptionRules(BillingTestBase):
    def test_cannot_subscribe_to_inactive_plan(self):
        plan = self.make_plan().json()
        from billing.models import Plan
        Plan.objects.filter(pk=plan["id"]).update(is_active=False)
        cust = self.make_customer().json()
        r = self.make_subscription(cust["id"], plan["id"])
        self.assertEqual(r.status_code, 422)

    def test_no_duplicate_active_subscription_same_plan(self):
        plan = self.make_plan().json()
        cust = self.make_customer().json()
        self.assertEqual(self.make_subscription(cust["id"], plan["id"]).status_code, 201)
        self.assertEqual(self.make_subscription(cust["id"], plan["id"]).status_code, 409)

    def test_can_resubscribe_after_cancel(self):
        plan = self.make_plan().json()
        cust = self.make_customer().json()
        sub = self.make_subscription(cust["id"], plan["id"]).json()
        self.assertEqual(self.c.post(f"{API}/subscriptions/{sub['id']}/cancel/").status_code, 200)
        self.assertEqual(self.make_subscription(cust["id"], plan["id"]).status_code, 201)


class InvoiceRules(BillingTestBase):
    def test_invoice_amount_is_snapshot_of_plan_price(self):
        plan, _, sub, inv = self.make_invoice("1500.00")
        self.assertEqual(Decimal(inv["amount_due"]), Decimal("1500.00"))
        self.assertEqual(inv["status"], "issued")
        # Plan price changes later: existing invoice must not change.
        from billing.models import Plan
        Plan.objects.filter(pk=plan["id"]).update(price=Decimal("9999.00"))
        again = self.c.get(f"{API}/invoices/{inv['id']}/").json()
        self.assertEqual(Decimal(again["amount_due"]), Decimal("1500.00"))

    def test_cannot_invoice_cancelled_subscription(self):
        _, _, sub, _ = self.make_invoice()
        self.c.post(f"{API}/subscriptions/{sub['id']}/cancel/")
        r = self.c.post(
            f"{API}/invoices/generate/",
            {"subscription_id": sub["id"], "period_start": "2030-01-01"}, format="json",
        )
        self.assertEqual(r.status_code, 422)

    def test_duplicate_period_invoice_rejected(self):
        _, _, sub, inv = self.make_invoice()
        r = self.c.post(
            f"{API}/invoices/generate/",
            {"subscription_id": sub["id"],
             "period_start": inv["period_start"], "period_end": inv["period_end"]},
            format="json",
        )
        self.assertEqual(r.status_code, 409)

    def test_invoice_generation_writes_ledger_entry(self):
        _, cust, _, inv = self.make_invoice()
        entries = LedgerEntry.objects.filter(invoice_id=inv["id"])
        self.assertEqual(entries.count(), 1)
        e = entries.first()
        self.assertEqual(e.entry_type, "invoice_created")
        self.assertEqual(e.reference_id, f"INV-{inv['id']}")


class PaymentRules(BillingTestBase):
    def test_partial_then_full_payment_status_transitions(self):
        _, _, _, inv = self.make_invoice("1000.00")
        r1 = self.pay(inv["id"], "400.00", ref="p1")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.json()["invoice"]["status"], "partially_paid")
        r2 = self.pay(inv["id"], "600.00", ref="p2")
        self.assertEqual(r2.json()["invoice"]["status"], "paid")
        self.assertEqual(Decimal(r2.json()["invoice"]["amount_paid"]), Decimal("1000.00"))

    def test_successful_payment_cannot_exceed_remaining(self):
        _, _, _, inv = self.make_invoice("1000.00")
        self.pay(inv["id"], "700.00", ref="p1")
        r = self.pay(inv["id"], "300.01", ref="p2")
        self.assertEqual(r.status_code, 422)
        inv_db = Invoice.objects.get(pk=inv["id"])
        self.assertEqual(inv_db.amount_paid, Decimal("700.00"))
        self.assertEqual(PaymentAttempt.objects.filter(invoice_id=inv["id"]).count(), 1)

    def test_failed_payment_does_not_increase_amount_paid(self):
        _, _, _, inv = self.make_invoice("1000.00")
        r = self.pay(inv["id"], "500.00", status="failed", ref="f1", failure_reason="card_declined")
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(Decimal(body["invoice"]["amount_paid"]), Decimal("0.00"))
        self.assertEqual(body["invoice"]["status"], "issued")
        self.assertEqual(body["payment_attempt"]["failure_reason"], "card_declined")

    def test_payment_ledger_entries_are_traceable(self):
        _, cust, _, inv = self.make_invoice("1000.00")
        self.pay(inv["id"], "1000.00", ref="ok1")
        self.pay(inv["id"], "10.00", status="failed", ref="bad1")  # rejected: invoice paid
        ledger = self.c.get(f"{API}/customers/{cust['id']}/ledger/").json()
        self.assertEqual([e["entry_type"] for e in ledger], ["invoice_created", "payment_success"])
        attempt = PaymentAttempt.objects.get(provider_reference="ok1")
        self.assertEqual(ledger[1]["reference_id"], f"PAY-{attempt.id}")

    def test_duplicate_provider_reference_rejected(self):
        _, _, _, inv = self.make_invoice("1000.00")
        self.pay(inv["id"], "100.00", ref="same")
        self.assertEqual(self.pay(inv["id"], "100.00", ref="same").status_code, 409)

    def test_currency_mismatch_rejected(self):
        _, _, _, inv = self.make_invoice("1000.00")
        self.assertEqual(self.pay(inv["id"], "100.00", currency="USD").status_code, 422)


class LedgerAppendOnly(BillingTestBase):
    def test_ledger_entries_cannot_be_updated_or_deleted(self):
        _, _, _, inv = self.make_invoice()
        entry = LedgerEntry.objects.first()
        entry.amount = Decimal("1.00")
        with self.assertRaises(TypeError):
            entry.save()
        with self.assertRaises(TypeError):
            entry.delete()
        with self.assertRaises(TypeError):
            LedgerEntry.objects.all().update(amount=Decimal("1.00"))
        with self.assertRaises(TypeError):
            LedgerEntry.objects.all().delete()
