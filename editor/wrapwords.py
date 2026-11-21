"""Word-boundary decisions shared by measured text and fixed-row labels."""
from unicodedata import name, normalize


def can_mechanically_hyphenate(word):
    """Keep accented Latin syllables whole. ASCII and full-width Latin still qualify."""
    for char in normalize('NFKC', word):
        if not char.isascii() and name(char, '').startswith('LATIN '):
            return False
    return True
