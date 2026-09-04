"""Sample utility module."""

def helper(text: str) -> str:
    if not text:
        return ""
    return text.strip().upper()
