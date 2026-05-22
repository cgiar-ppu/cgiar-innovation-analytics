"""
Session business logic — pure functions extracted from route handlers.
"""


def generate_session_title(content: str) -> str:
    """Generate a short title from user message content.

    Applies prefix stripping, first-sentence extraction, truncation, and
    capitalization.  This is a pure function with no DB or HTTP dependency.

    Args:
        content: The raw text of the first user message (already stripped).

    Returns:
        A human-friendly title string (max 70 characters).
    """
    title = content

    # Strip common conversational prefixes so the title starts with the
    # meaningful part of the request.
    for prefix in [
        "I want to ",
        "I need to ",
        "Can you ",
        "Please ",
        "Help me ",
        "I'd like to ",
        "I would like to ",
        "Could you ",
    ]:
        if title.lower().startswith(prefix.lower()):
            title = title[len(prefix):]
            break

    # Take first sentence (up to 80 chars) if a sentence boundary exists.
    for sep in [". ", "? ", "! ", "\n"]:
        idx = title.find(sep)
        if idx != -1 and idx < 80:
            title = title[: idx + 1]
            break

    # Truncate long titles with an ellipsis.
    if len(title) > 70:
        title = title[:67] + "..."

    # Capitalize the first letter.
    if title:
        title = title[0].upper() + title[1:]

    return title
