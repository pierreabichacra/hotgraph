"""Parser registry.

Importing this package imports each parser module, which is what populates the
registry via the @register(...) decorator.
"""

from .base import Event, ParseContext, get_parser, register, registry  # noqa: F401

from . import tracker  # noqa: F401,E402
from . import generic  # noqa: F401,E402

__all__ = ["Event", "ParseContext", "register", "get_parser", "registry"]
