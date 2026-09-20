"""Sandbox gateway related tests."""
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from zeitlabs_payments.models import Cart, CatalogueItem, Invoice
from zeitlabs_payments.providers.sandbox.processor import SandboxProcessor

User = get_user_model()

SANDBOX_ON = {'sandbox_gateway': True, 'valid_currency': 'SAR', 'invoice_prefix': 'TEST'}


@pytest.mark.django_db
@pytest.mark.usefixtures('base_data')
class TestSandboxGateway(TestCase):
    """Tests for SandboxProcessor and SandboxReturnView."""

    def setUp(self):
        """Create a processing cart for the learner."""
        self.user = User.objects.get(id=3)
        self.item = CatalogueItem.objects.get(sku='custom-sku-1')
        self.cart = Cart.objects.create(user=self.user, status=Cart.Status.PROCESSING)
        self.cart.items.create(catalogue_item=self.item, original_price=self.item.price, final_price=self.item.price)
        self.url = reverse('zeitlabs_payments:sandbox-return')
        self.reference = f'1-{self.cart.id}'

    def test_disabled_by_default(self):
        """The processor is off and the return view answers 404 unless the setting is on."""
        assert SandboxProcessor.is_enabled() is False
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'merchant_reference': self.reference, 'outcome': 'success'})
        assert response.status_code == 404
        self.cart.refresh_from_db()
        assert self.cart.status == Cart.Status.PROCESSING

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_get_transaction_parameters(self):
        """The gateway page gets the return URL and a CSRF token."""
        assert SandboxProcessor.is_enabled() is True
        request = RequestFactory().get('/')
        request.site = Mock(id=1)
        request.user = self.user
        params = SandboxProcessor().get_transaction_parameters(self.cart, request)
        assert params['return_url'] == self.url
        assert params['order_reference'] == self.reference
        assert params['csrfmiddlewaretoken']

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_requires_login(self):
        """Anonymous users are redirected to login."""
        response = self.client.post(self.url, {'merchant_reference': self.reference, 'outcome': 'success'})
        assert response.status_code == 302

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_invalid_reference(self):
        """Malformed or unknown references are rejected."""
        self.client.force_login(self.user)
        for reference in ('nonsense', '1-999999'):
            response = self.client.post(self.url, {'merchant_reference': reference, 'outcome': 'success'})
            assert response.status_code == 400

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_other_user_cart(self):
        """A user cannot pay another user's cart."""
        self.client.force_login(User.objects.get(id=4))
        response = self.client.post(self.url, {'merchant_reference': self.reference, 'outcome': 'success'})
        assert response.status_code == 400

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_decline(self):
        """Declining cancels the cart."""
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'merchant_reference': self.reference, 'outcome': 'decline'})
        assert response.status_code == 200
        self.cart.refresh_from_db()
        assert self.cart.status == Cart.Status.CANCELLED

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_success(self):
        """Approving pays the cart and redirects to the invoice."""
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'merchant_reference': self.reference, 'outcome': 'success'})
        invoice = Invoice.objects.get(cart=self.cart)
        assert response.status_code == 302
        assert response.url == reverse('zeitlabs_payments:invoice', args=[invoice.invoice_number])
        self.cart.refresh_from_db()
        assert self.cart.status == Cart.Status.PAID

    @override_settings(ZEITLABS_PAYMENTS_SETTINGS=SANDBOX_ON)
    def test_success_without_invoice(self):
        """A failed payment record update renders the error page."""
        self.client.force_login(self.user)
        with patch.object(SandboxProcessor, 'process_payment_and_update_records', return_value=None):
            response = self.client.post(self.url, {'merchant_reference': self.reference, 'outcome': 'success'})
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'zeitlabs_payments/payment_error.html')
