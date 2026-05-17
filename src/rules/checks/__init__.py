"""Importing this package self-registers every check via its register() call.

Add a new check to a new module here, then add its module name to the list
below. The engine never imports check modules directly.
"""

from src.rules.checks import lopsided_trade  # noqa: F401
from src.rules.checks import pick_trade_window  # noqa: F401
from src.rules.checks import roster_size  # noqa: F401
from src.rules.checks import trade_deadline  # noqa: F401
