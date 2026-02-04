# 3. Use Neo4j for Knowledge Graph

Date: 2024-02-04

## Status

Accepted

## Context

QPrisma processes video content that contains complex relationships (People in Scenes, Objects in Timeframes, Audio referencing Visuals). A standard relational database or a pure vector database is insufficient for capturing the structured connections between these entities.

## Decision

We will use **Neo4j** with its GraphRAG capabilities.

## Consequences

### Positive
- **Structure**: Can model complex video hierarchies (Video -> Scene -> Shot -> Frame -> Entity).
- **Hybrid Search**: Supports both semantic search (Vector Index) and keyword/relationship search.
- **Visual**: Graph visualization helps users understand connections in multimedia data.
- **GraphRAG**: Enhances LLM context with structured relationship data, reducing hallucinations.

### Negative
- **Complexity**: Introduces a new query language (Cypher) and database paradigm.
- **Resources**: JVM-based, heavier memory footprint than PostgreSQL.
