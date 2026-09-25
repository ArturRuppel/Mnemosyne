"""Interactive explorer plugin: bundle serving and export copying.

Explorers are reached from the experiment catalog and report tables (see
``eln.generators.explorers.explorer_links``), so the plugin adds no nav entry.
"""

from pathlib import Path

from eln.generators.explorers import generate_explorers
from eln.plugins import Plugin, StaticMount


plugin = Plugin(
    name="explorers",
    generate=generate_explorers,
    static_mount=StaticMount("explorers", lambda root: Path(root) / "explorers"),
)
