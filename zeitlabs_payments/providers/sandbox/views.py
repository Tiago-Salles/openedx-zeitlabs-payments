"""Sandbox gateway views."""
import logging
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from zeitlabs_payments.exceptions import InvalidCartError
from zeitlabs_payments.helpers import get_currency
from zeitlabs_payments.models import AuditLog, Cart

from .processor import SandboxProcessor

logger = logging.getLogger(__name__)


@method_decorator(transaction.non_atomic_requests, name='dispatch')
class SandboxReturnView(LoginRequiredMixin, View):
    """
    Receives the outcome chosen on the fake gateway page and completes or cancels the cart.

    non_atomic_requests mirrors the real gateway views: AuditLog rows must survive a rollback.
    """

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Refuse every request unless the sandbox gateway is enabled, the URL is always registered."""
        if not SandboxProcessor.is_enabled():
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Any) -> HttpResponse:
        """Handle the fake gateway response."""
        data = request.POST.dict()
        processor = SandboxProcessor()
        reference = data.get('merchant_reference', '')
        try:
            site_id, cart_id = reference.split('-', 1)
            cart = processor.get_cart(cart_id)
        except (ValueError, InvalidCartError):
            logger.error(f'Sandbox gateway: invalid merchant_reference {reference!r}')
            return HttpResponseBadRequest('Invalid merchant reference.')

        if cart.user != request.user:
            return HttpResponseBadRequest('Cart does not belong to the current user.')

        if data.get('outcome') != 'success':
            cart.status = Cart.Status.CANCELLED
            cart.save(update_fields=['status'])
            AuditLog.log(
                action=AuditLog.AuditActions.CART_STATUS_UPDATED,
                cart=cart,
                gateway=processor.SLUG,
                context={'old_status': Cart.Status.PROCESSING, 'new_status': Cart.Status.CANCELLED,
                         'reason': 'declined on sandbox gateway'},
            )
            return render(request, 'zeitlabs_payments/payment_decline.html', {'merchant_reference': reference})

        invoice = processor.process_payment_and_update_records(
            cart=cart,
            data=data,
            request=request,
            transaction_id=f'SANDBOX-{cart.id}-{int(timezone.now().timestamp())}',
            transaction_status=processor.TRANSACTION_STATUS_SUCCESS,
            method=processor.METHOD,
            amount=str(cart.total),
            currency=get_currency(cart),
            reason='approved on sandbox gateway',
            site_id=int(site_id),
        )
        if not invoice:
            return render(request, 'zeitlabs_payments/payment_error.html', {'merchant_reference': reference})
        return redirect('zeitlabs_payments:invoice', invoice.invoice_number)
