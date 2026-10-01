"""seedsmith.plumbing — cross-adapter plumbing that belongs to no single adapter.

A package rather than another directory under `adapters/`, because the rule these modules obey is the
opposite of an adapter's: they must be reachable from every adapter without any adapter owning them.
An adapter that imported one of these would have created a dependency the wrong way.
"""