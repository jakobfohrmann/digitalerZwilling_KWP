"""Sanierungstiefe-Definitionen."""

from typing import Dict, Set

SANIERUNG_DEPTHS: Dict[str, Set[str]] = {
    'vollsaniert': {'dach', 'geschossdecke', 'wand', 'keller', 'fenster', 'tuer'},
    'teilsaniert': {'dach', 'wand', 'fenster'},
    'huelle':      {'dach', 'geschossdecke', 'wand', 'keller', 'fenster', 'tuer'},
    'fenster':     {'fenster'},
    'dach':        {'dach'},
    'wand':        {'wand'},
    'keller':      {'keller'},
    'tuer':        {'tuer'},
}

SANIERUNG_PARTS = ['dach', 'geschossdecke', 'wand', 'keller', 'fenster', 'tuer']
