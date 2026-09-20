"""
Sandbox payment processor.

A fake gateway that renders a page with "Pay" and "Decline" buttons instead of redirecting to a real
payment provider. It exercises the full cart -> transaction -> invoice -> fulfillment flow and is meant
for development and demo environments only.
"""
from typing import Any, Optional

from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from zeitlabs_payments.helpers import get_settings
from zeitlabs_payments.models import Cart
from zeitlabs_payments.providers.base import BaseProcessor


class SandboxProcessor(BaseProcessor):
    """Fake gateway for local testing."""

    SLUG = 'sandbox'
    NAME = 'Sandbox gateway'
    CHECKOUT_TEXT = _('Pay with sandbox gateway (test only)')
    TEMPLATE_NAME = 'zeitlabs_payments/sandbox/gateway.html'
    METHOD = 'sandbox_card'

    @classmethod
    def is_enabled(cls) -> bool:
        """Only register when ZEITLABS_PAYMENTS_SETTINGS['sandbox_gateway'] is true. Never enable in production."""
        return bool(get_settings().sandbox_gateway)

    def get_transaction_parameters(
        self,
        cart: Cart,
        request: Optional[HttpRequest] = None,
        use_client_side_checkout: bool = False,
        **kwargs: Any
    ) -> dict:
        """Build the parameters rendered on the fake gateway page."""
        params = self.get_transaction_parameters_base(cart, request)
        params.update({
            'amount_display': cart.total,
            'return_url': reverse('zeitlabs_payments:sandbox-return'),
            'csrfmiddlewaretoken': get_token(request),
        })
        return params
