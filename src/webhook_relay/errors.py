"""Domain exceptions shared across layers (mapped to HTTP responses at the edge)."""

from __future__ import annotations


class WebhookRelayError(Exception):
    """Base class for every domain error."""


class SignatureError(WebhookRelayError):
    """The request signature is missing, malformed, expired or does not match."""


class DestinationError(WebhookRelayError):
    """The CRM destination rejected the request (non-retryable, e.g. 4xx)."""


class DestinationUnavailableError(DestinationError):
    """The CRM destination is unavailable after retries (5xx, 429, transport errors)."""


class MediaError(WebhookRelayError):
    """Base class for media download problems."""


class MediaTooLargeError(MediaError):
    """The media exceeds the configured size limit."""


class UnsupportedMediaTypeError(MediaError):
    """The media content type is not in the allow-list."""


class MediaDownloadError(MediaError):
    """The media could not be downloaded (HTTP error, timeout, expired link)."""


class StorageError(WebhookRelayError):
    """The blob storage failed to persist or read an object."""
