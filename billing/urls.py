from django.urls import path

from . import views

urlpatterns = [
    path("plans/", views.PlanListCreateView.as_view()),
    path("customers/", views.CustomerListCreateView.as_view()),
    path("customers/<int:customer_id>/", views.CustomerDetailView.as_view()),
    path("customers/<int:customer_id>/subscriptions/", views.CustomerSubscriptionsView.as_view()),
    path("customers/<int:customer_id>/ledger/", views.CustomerLedgerView.as_view()),
    path("subscriptions/", views.SubscriptionCreateView.as_view()),
    path("subscriptions/<int:subscription_id>/", views.SubscriptionDetailView.as_view()),
    path("subscriptions/<int:subscription_id>/cancel/", views.SubscriptionCancelView.as_view()),
    path("invoices/generate/", views.InvoiceGenerateView.as_view()),
    path("invoices/<int:invoice_id>/", views.InvoiceDetailView.as_view()),
    path("invoices/<int:invoice_id>/ledger/", views.InvoiceLedgerView.as_view()),
    path("payments/", views.PaymentCreateView.as_view()),
]
