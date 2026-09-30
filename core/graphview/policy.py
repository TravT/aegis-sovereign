"""What the graph viewer may show. Allow-lists, never deny-lists: an entity type or relation kind
that is not named here (including any type added to the entity graph later) stays out of the viewer.

The entity graph also holds personal Paperless data (monetary amounts, CNPJ/CPF, dates, documents)
and noise links (for example ADR -> alarm), and many Huawei entities have no document link, so the
corpus cannot be used as the filter: the entity type and the relation kind are.
"""

# entity_type -> shown as a node of the entity layer
ENTITY_TYPES = frozenset({
    "telecom_alarm",
    "mml_command",
    "telecom_kpi",
    "telecom_feature",
    "product_release",
})

# relation kinds between allowed entities that describe real Huawei relationships
ENTITY_RELATIONS = frozenset({
    "DIAGNOSED_BY_MML",
    "REMEDIATED_BY_MML",
    "CONFIGURED_BY_MML",
    "MEASURED_BY_COUNTER",
    "CANONICAL_ALARM_SPEC",
    "DEFINES_ALARM",
    "IMPLEMENTS_FEATURE",
})
