"""Model providers: how the semantic layer gets model answers (FND-007, FND-009).

ADR-0007 sets the egress switches; ADR-0009 sets the shape. A provider takes
a batch of requests (``submit``) and later hands back what came in
(``collect``): each answer is ``ok`` (validated), ``invalid`` (with the
reason) or ``pending``. That shape fits both a paid API and the file-batch
provider a Claude Code session fills on the owner's PC.
"""
