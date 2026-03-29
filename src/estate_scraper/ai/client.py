from __future__ import annotations

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential


def get_client(api_key: str) -> anthropic.Anthropic:
    """Create an Anthropic client."""
    return anthropic.Anthropic(api_key=api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=16))
def call_claude(
    client: anthropic.Anthropic,
    system: str,
    user_content: str | list,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
) -> str:
    """Make a Claude API call with retry logic. Returns the text response."""
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return message.content[0].text
