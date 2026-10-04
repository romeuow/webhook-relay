"""CRM destination adapters."""

from webhook_relay.destination.base import CRMDestination
from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.destination.http import HttpCRMDestination
from webhook_relay.destination.retry import RetryPolicy

__all__ = ["CRMDestination", "FakeCRMDestination", "HttpCRMDestination", "RetryPolicy"]
