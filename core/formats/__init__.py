"""Real-world structured enterprise & homelab format parsers for Aegis Sovereign Knowledge Appliance."""

from .openxml_parser import (
    OpenXmlAlarmRecord,
    OpenXmlCounterRecord,
    OpenXmlDocSection,
    OpenXmlReleaseDocParser,
    OpenXmlReleaseManifest,
)
from .real_world_parsers import (
    EmailMessageRecord,
    MboxEmailParser,
    NfeInvoiceRecord,
    NfeItemSpec,
    NfeMedSpec,
    NfeRastroSpec,
    NfeXmlParser,
    TabularCsvParser,
    TabularRecordChunk,
    XmlSecurityError,
)

__all__ = [
    "XmlSecurityError",
    "NfeRastroSpec",
    "NfeMedSpec",
    "NfeItemSpec",
    "NfeInvoiceRecord",
    "NfeXmlParser",
    "EmailMessageRecord",
    "MboxEmailParser",
    "TabularRecordChunk",
    "TabularCsvParser",
    "OpenXmlAlarmRecord",
    "OpenXmlCounterRecord",
    "OpenXmlDocSection",
    "OpenXmlReleaseManifest",
    "OpenXmlReleaseDocParser",
]
