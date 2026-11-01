# SubLedger

A simplified billing backend (plans, customers, subscriptions, invoices, payments and an append-only ledger) built with **Python 3, Django, Django REST Framework and PostgreSQL**.

Full HLD and LLD (ERD, service and repository tables, rule ownership, patterns, flows) are in **[DESIGN.md](DESIGN.md)**.

## Project layout

```
config/               settings (env-driven), root urls, wsgi
billing/
  models.py           tables + DB constraints
  repositories.py     the only ORM access
  services.py         business rules + transactions
  schemas.py          request/response validation & serialization
  views.py, urls.py   routes
  exceptions.py       domain errors   | exception_handler.py → HTTP mapping
  container.py        dependency wiring
  tests/              business-rule tests
Dockerfile, docker-compose.yml
```

## Setup

### Option 1: Docker (recommended)

```bash
docker compose up --build
# API on http://localhost:8000/api/v1/
```

Migrations run automatically on container start.

### Option 2: Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# start PostgreSQL (example)
docker run -d --name subledger-db -p 5432:5432 \
  -e POSTGRES_DB=subledger -e POSTGRES_USER=subledger -e POSTGRES_PASSWORD=subledger postgres:16

cp .env.example .env   # then: export $(grep -v '^#' .env | xargs)
python manage.py migrate
python manage.py runserver
```

### Run tests

```bash
python manage.py test billing            # against PostgreSQL
DB_ENGINE=sqlite python manage.py test billing   # quick run, no Postgres needed
```

16 tests cover the business rules.

## API list (base `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| POST / GET | `/plans/` | Create / list plans |
| POST / GET | `/customers/` | Create / list customers |
| GET | `/customers/{id}/` | Get a customer |
| GET | `/customers/{id}/subscriptions/` | Customer's subscriptions |
| GET | `/customers/{id}/ledger/` | Customer ledger |
| POST | `/subscriptions/` | Create subscription |
| GET | `/subscriptions/{id}/` | Get subscription |
| POST | `/subscriptions/{id}/cancel/` | Cancel subscription |
| POST | `/invoices/generate/` | Generate invoice for a subscription |
| GET | `/invoices/{id}/` | Get invoice |
| GET | `/invoices/{id}/ledger/` | Ledger entries for an invoice |
| POST | `/payments/` | Record a payment attempt (success or failed) |

## Example walkthrough

```bash
B=http://localhost:8000/api/v1
curl -s -X POST $B/plans/ -H 'Content-Type: application/json' \
  -d '{"name":"Pro","price":"1000.00","currency":"INR","billing_interval":"monthly"}'
curl -s -X POST $B/customers/ -H 'Content-Type: application/json' \
  -d '{"name":"Acme","email":"billing@acme.com"}'
curl -s -X POST $B/subscriptions/ -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"plan_id":1}'
curl -s -X POST $B/invoices/generate/ -H 'Content-Type: application/json' \
  -d '{"subscription_id":1}'
curl -s -X POST $B/payments/ -H 'Content-Type: application/json' \
  -d '{"invoice_id":1,"amount":"400.00","currency":"INR","status":"success","provider_reference":"pay_001"}'
# → invoice becomes partially_paid; pay the remaining 600.00 → paid
curl -s $B/customers/1/ledger/
```

Failed payment: send `"status":"failed"` with an optional `"failure_reason":"card_declined"`. `amount_paid` stays unchanged.

Errors look like `{"error": {"code": "business_rule_violation", "message": "..."}}` with 404 (not found), 409 (conflict) or 422 (rule violation).

## Business rules implemented

Plan price > 0; unique customer email; no subscription on an inactive plan; no duplicate active subscription for the same plan; invoice `amount_due` snapshots the plan price; successful payment cannot exceed the remaining amount; partial → `partially_paid`, full → `paid`; failed payments never change `amount_paid`; append-only ledger traceable by `reference_id`.

Beyond the brief: one invoice per subscription period, idempotent `provider_reference`, currency match on payments, and row-level locking on payment and invoice writes. Reasons are in DESIGN.md section B1.

## Assumptions

* Single currency per plan. A payment's currency must equal the invoice currency, and there is no FX.
* Billing period defaults to `today` through `today + 1 month/year - 1 day`, depending on the plan interval. It can be overridden with `period_start` and `period_end`.
* Due date = `period_start + INVOICE_DUE_DAYS` (default 7).
* Invoices are created directly as `issued`. The `draft` and `void` statuses exist but have no endpoints yet.
* `provider_reference` is unique per attempt, and a provider retry must send a new reference or be treated as a replay (409).
* A payment against an already `paid` invoice is rejected, whether it is a success or a failure.
* Cancelling a subscription is immediate and does not delete invoices.

## Limitations

* No authentication or authorisation, and no multi-tenancy.
* No pagination or filtering on list endpoints.
* No recurring or scheduled invoicing, proration, refunds, taxes or discounts.
* No real payment gateway integration. `/payments/` records outcomes reported to it.
* Customer balance is not exposed as a field; it can be derived from the ledger (`debit` minus `credit`).
* No Swagger or Postman collection included. Adding `drf-spectacular` would generate OpenAPI docs.
