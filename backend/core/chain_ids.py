"""Stable design-order alphabetic chain labels shared by export and playback."""


def alphabetic_chain_id(index: int) -> str:
    """Encode a zero-based strand index as A..Z, AA..ZZ, AAA, and onward."""
    if index < 0:
        raise ValueError("chain index must be nonnegative")
    value = index + 1
    letters = []
    while value:
        value, digit = divmod(value - 1, 26)
        letters.append(chr(ord("A") + digit))
    return "".join(reversed(letters))


def alphabetic_chain_index(chain_id: str) -> int:
    """Decode an uppercase alphabetic chain label to its zero-based index."""
    if not chain_id or any(not "A" <= char <= "Z" for char in chain_id):
        raise ValueError("chain ID must contain uppercase A-Z letters")
    value = 0
    for char in chain_id:
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1
