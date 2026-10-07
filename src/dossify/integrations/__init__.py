"""Optional, bundled adapters for one specific service or institution.

They are plug and play and need nothing from the core: each imports its own library lazily, so the
rest of Dossify works without it, and each is switched on by a ``[providers.<name>]`` block.  When
the library is missing, the run says how to install it instead of failing quietly.
"""

from dossify.integrations.elteportal import ADAPTER as _ELTE

OPTIONAL_ADAPTERS = {"elteportal": _ELTE}
