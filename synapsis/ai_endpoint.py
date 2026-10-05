"""Which OpenAI-compatible endpoint the app's OpenAI features (voice guide, dictation, TTS, images) talk to.

Since 2026-10-05 the OpenAI organisation that owned our keys is closed; models are served through
Microsoft Azure OpenAI instead. Everything is configuration:

- ``IA_OPENAI_ENDPOINT``: resource base URL. Default ``https://syn-ia.openai.azure.com`` (Azure, the
  Innovation Analytics resource). Set ``https://api.openai.com`` only to talk to OpenAI directly.
- ``OPENAI_API_KEY``: the key for that endpoint (the variable name is kept so the existing GitHub
  secret -> SSM ``/cgiar-ia-<stage>/openai-api-key`` -> container lane stays unchanged; on Azure it
  holds the Azure resource key).

Azure authenticates with an ``api-key`` header and serves the OpenAI "v1" API under ``/openai/v1``;
OpenAI uses ``Authorization: Bearer`` under ``/v1``. Never log the key.
"""
import os
from urllib.parse import urlparse

DEFAULT_ENDPOINT = 'https://syn-ia.openai.azure.com'
AZURE_HOST_SUFFIXES = ('.openai.azure.com', '.cognitiveservices.azure.com', '.services.ai.azure.com')
# Data-plane API version that still answers GET /openai/deployments/<name> (200 deployed / 404 not).
AZURE_DEPLOYMENT_API_VERSION = '2022-12-01'
AZURE_AUDIO_API_VERSION = '2025-03-01-preview'


def endpoint() -> str:
    return (os.getenv('IA_OPENAI_ENDPOINT') or DEFAULT_ENDPOINT).strip().rstrip('/')


def is_azure() -> bool:
    host = (urlparse(endpoint()).hostname or '').lower()
    return host.endswith(AZURE_HOST_SUFFIXES)


def provider_label() -> str:
    return 'Microsoft Azure OpenAI' if is_azure() else 'OpenAI'


def api_key() -> str:
    return os.getenv('OPENAI_API_KEY', '')


def auth_headers(key: str | None = None) -> dict:
    key = api_key() if key is None else key
    return {'api-key': key} if is_azure() else {'Authorization': 'Bearer ' + key}


def v1(path: str) -> str:
    """URL of an OpenAI v1 API path (``realtime/calls``, ``live/sessions`` ...) on the configured endpoint."""
    return endpoint() + ('/openai/v1/' if is_azure() else '/v1/') + path.lstrip('/')


def azure_deployment_url(name: str) -> str:
    from urllib.parse import quote
    return f'{endpoint()}/openai/deployments/{quote(name, safe="")}?api-version={AZURE_DEPLOYMENT_API_VERSION}'


def azure_transcription_url(deployment: str) -> str:
    from urllib.parse import quote
    return f'{endpoint()}/openai/deployments/{quote(deployment, safe="")}/audio/transcriptions?api-version={AZURE_AUDIO_API_VERSION}'
