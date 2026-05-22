"""
TTS MCP tools -- allow the orchestrator agent to control voice settings
programmatically (e.g. pick different voices for different characters).
"""

from typing import Any

from claude_agent_sdk import tool
from synapsis.config import logger
from synapsis.utils.responses import error_response, success_response


# ---------------------------------------------------------------------------
# tts_set_voice
# ---------------------------------------------------------------------------

@tool(
    "tts_set_voice",
    "Set the text-to-speech voice and optionally update speaking style "
    "instructions and speed. Use this to give different characters different "
    "voices (e.g. 'onyx' for a deep villain, 'nova' for a bright narrator). "
    "Available voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, "
    "sage, shimmer, verse, marin, cedar.",
    {
        "voice": str,
        "instructions": str,
        "speed": float,
    },
)
async def tts_set_voice(args: dict[str, Any]) -> dict[str, Any]:
    """Set the TTS voice and optionally update instructions and speed."""
    from synapsis.routes.tts import _tts_settings, VOICES

    voice = args.get("voice", "")
    instructions = args.get("instructions", "")
    speed = args.get("speed", 1.0)

    if not voice:
        return error_response("Error: 'voice' is required.")

    valid_ids = {v["id"] for v in VOICES}
    if voice not in valid_ids:
        return error_response(
            f"Error: Unknown voice '{voice}'. "
            f"Available: {', '.join(sorted(valid_ids))}"
        )

    _tts_settings["voice"] = voice
    if instructions:
        _tts_settings["instructions"] = instructions
    if speed != 1.0:
        _tts_settings["speed"] = max(0.25, min(4.0, speed))

    logger.info(
        "TTS voice set via MCP: voice=%s instructions=%s speed=%.1f",
        voice, _tts_settings["instructions"][:50], _tts_settings["speed"],
    )

    msg = (
        f"TTS voice set to '{voice}'"
        + (f" with instructions: \"{instructions}\"" if instructions else "")
        + (f" at speed {speed}x" if speed != 1.0 else "")
        + f"\n\nCurrent settings: voice={_tts_settings['voice']}, "
        f"model={_tts_settings['model']}, speed={_tts_settings['speed']}"
    )
    return success_response(msg)


# ---------------------------------------------------------------------------
# tts_get_voices
# ---------------------------------------------------------------------------

@tool(
    "tts_get_voices",
    "List all available text-to-speech voices with descriptions and show "
    "the current voice settings. Use this to see what voices are available "
    "before calling tts_set_voice.",
    {},
)
async def tts_get_voices(args: dict[str, Any]) -> dict[str, Any]:
    """List all available TTS voices and the current voice settings."""
    from synapsis.routes.tts import _tts_settings, VOICES

    lines = ["Available TTS voices:\n"]
    for v in VOICES:
        marker = " <- current" if v["id"] == _tts_settings["voice"] else ""
        lines.append(f"  * {v['id']} ({v['name']}): {v['description']}{marker}")

    lines.append(f"\nCurrent settings:")
    lines.append(f"  Voice: {_tts_settings['voice']}")
    lines.append(f"  Model: {_tts_settings['model']}")
    lines.append(f"  Instructions: {_tts_settings['instructions'] or '(none)'}")
    lines.append(f"  Speed: {_tts_settings['speed']}x")

    return success_response("\n".join(lines))
