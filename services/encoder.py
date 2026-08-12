"""
Base62 Encoder

Converts auto-incremented integer IDs into compact, URL-safe short codes
using a base62 alphabet (0-9, a-z, A-Z).

Examples:
    encode_base62(1)      → "1"
    encode_base62(62)     → "10"
    encode_base62(12345)  → "3d7"
"""

import string

ALPHABET = string.digits + string.ascii_letters  # 0-9 + a-z + A-Z
BASE = len(ALPHABET)  # 62


def encode_base62(num: int) -> str:
    """
    Convert a positive integer to a base62-encoded string.

    Args:
        num: A non-negative integer (typically a database auto-increment ID).

    Returns:
        A compact alphanumeric string representation.
    """
    if num == 0:
        return ALPHABET[0]

    encoded = []
    while num > 0:
        num, remainder = divmod(num, BASE)
        encoded.append(ALPHABET[remainder])

    return "".join(reversed(encoded))


def decode_base62(code: str) -> int:
    """
    Convert a base62-encoded string back to an integer.

    Args:
        code: A base62-encoded string.

    Returns:
        The original integer value.

    Raises:
        ValueError: If the string contains characters outside the base62 alphabet.
    """
    num = 0
    for char in code:
        index = ALPHABET.find(char)
        if index == -1:
            raise ValueError(f"Invalid base62 character: '{char}'")
        num = num * BASE + index
    return num
