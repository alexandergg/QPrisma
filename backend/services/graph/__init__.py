"""
Graph domain mixins for GraphNodeRepository.

Each mixin encapsulates a cohesive set of Cypher operations for a single
domain (videos, frames, entities, …).  They are composed into the main
:class:`~services.graph_node_repository.GraphNodeRepository` via multiple
inheritance.
"""
