"""
Client creation with retry logic.

Provides ``create_client_with_retry`` which wraps ClaudeSDKClient connection
attempts with configurable retries and a fresh-session fallback when resuming
fails.
"""

import asyncio

from claude_agent_sdk import ClaudeSDKClient

from synapsis.config import logger


async def create_client_with_retry(
    options,
    max_retries: int = 2,
    retry_delay: float = 1.0,
    resume_session_id=None,
):
    """Create and connect a ClaudeSDKClient with retry logic.

    Tries to connect ``max_retries`` times with ``retry_delay`` seconds between
    attempts.  If all retries fail **and** ``resume_session_id`` was set on
    ``options``, falls back to a fresh session (options.resume = None).

    Args:
        options:            A ClaudeAgentOptions instance (or compatible) to
                            pass to ClaudeSDKClient.
        max_retries:        Number of connection attempts before giving up.
        retry_delay:        Seconds to sleep between attempts.
        resume_session_id:  The resume session ID currently set on options
                            (used to decide whether a fresh-session fallback
                            is viable).

    Returns:
        A connected ClaudeSDKClient ready to receive queries.

    Raises:
        Exception: The last connection error if all attempts (including the
                   optional fresh-session fallback) fail.
    """
    last_err: Exception | None = None

    for attempt in range(1, max_retries + 1):
        client = ClaudeSDKClient(options=options)
        try:
            await client.connect()
            return client
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Client connect attempt %d/%d failed: %s",
                attempt, max_retries, exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

    # All retries exhausted -- try a fresh session if we were resuming
    if resume_session_id and hasattr(options, "resume"):
        logger.warning(
            "All %d retries failed with resume=%s -- falling back to fresh session",
            max_retries, resume_session_id,
        )
        options.resume = None
        client = ClaudeSDKClient(options=options)
        await client.connect()
        return client

    # No fallback possible -- re-raise the last error
    raise last_err  # type: ignore[misc]
