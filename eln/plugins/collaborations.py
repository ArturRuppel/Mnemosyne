"""Collaborations — documents that name their collaborators.

A document under ``ROOT/documents`` whose front matter has a
``**Collaborators:** Name, Name`` line is shown here, as tiles with one page per
collaboration, instead of on the Documents page. The files stay in
``documents/``, so the Documents plugin's static mount already serves their media.
"""

from eln.generators.collaborations import generate_collaborations
from eln.plugins import NavLink, Plugin


plugin = Plugin(
    name="collaborations",
    nav=NavLink("Collaborations", "collaborations.html"),
    generate=generate_collaborations,
)
