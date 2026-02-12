---
description: Generate and execute Neo4j Cypher queries for the QPrisma Knowledge Graph
---

# Neo4j Query Helper

Generate and execute Neo4j Cypher queries for the QPrisma Knowledge Graph.

## Usage
```
/neo4j-query <description of what you want to query>
```

## Knowledge Graph Schema

### Node Types

```cypher
// Video node - root of video content
(:Video {
  media_id: string,      // Unique identifier
  title: string,         // Video title
  duration: float,       // Duration in seconds
  created_at: datetime,  // Upload timestamp
  user_id: string        // Owner
})

// Frame node - individual video frames
(:Frame {
  frame_id: string,      // Unique identifier
  media_id: string,      // Parent video
  timestamp: float,      // Position in seconds
  frame_number: int,     // Sequential number
  description: string,   // GPT-4o visual description
  embedding: list<float> // Vector embedding
})

// Scene node - grouped frames with similar content
(:Scene {
  scene_id: string,
  media_id: string,
  start_time: float,
  end_time: float,
  description: string,
  summary: string
})

// Entity node - detected objects, people, concepts
(:Entity {
  entity_id: string,
  name: string,          // Entity name
  type: string,          // person, object, location, concept
  description: string
})

// Transcript node - audio transcription segments
(:Transcript {
  segment_id: string,
  media_id: string,
  start_time: float,
  end_time: float,
  text: string,
  speaker: string,       // Optional speaker ID
  embedding: list<float>
})

// Chapter node - video chapters/sections
(:Chapter {
  chapter_id: string,
  media_id: string,
  title: string,
  start_time: float,
  end_time: float,
  summary: string
})
```

### Relationships

```cypher
// Video structure
(Video)-[:HAS_FRAME]->(Frame)
(Video)-[:HAS_SCENE]->(Scene)
(Video)-[:HAS_CHAPTER]->(Chapter)
(Video)-[:HAS_TRANSCRIPT]->(Transcript)

// Scene composition
(Scene)-[:CONTAINS_FRAME]->(Frame)
(Scene)-[:NEXT_SCENE]->(Scene)

// Entity relationships
(Frame)-[:CONTAINS_ENTITY]->(Entity)
(Scene)-[:FEATURES_ENTITY]->(Entity)
(Entity)-[:RELATED_TO {relation: string}]->(Entity)

// Temporal relationships
(Frame)-[:NEXT_FRAME]->(Frame)
(Transcript)-[:NEXT_SEGMENT]->(Transcript)

// Cross-references
(Frame)-[:DESCRIBED_BY]->(Transcript)
(Scene)-[:NARRATED_BY]->(Transcript)
```

## Common Query Patterns

### 1. Search by Content (Vector Similarity)

```cypher
// Search frames by semantic similarity
CALL db.index.vector.queryNodes('frame_embeddings', 10, $query_embedding)
YIELD node AS frame, score
WHERE frame.media_id = $media_id
RETURN frame.timestamp, frame.description, score
ORDER BY score DESC
```

### 2. Find Entity Occurrences

```cypher
// Find all frames containing a specific entity
MATCH (v:Video {media_id: $media_id})-[:HAS_FRAME]->(f:Frame)-[:CONTAINS_ENTITY]->(e:Entity)
WHERE e.name =~ $entity_pattern
RETURN f.timestamp, f.description, e.name, e.type
ORDER BY f.timestamp
```

### 3. Get Video Timeline with Entities

```cypher
// Get complete timeline with entities and transcripts
MATCH (v:Video {media_id: $media_id})
OPTIONAL MATCH (v)-[:HAS_SCENE]->(s:Scene)
OPTIONAL MATCH (s)-[:FEATURES_ENTITY]->(e:Entity)
OPTIONAL MATCH (s)-[:NARRATED_BY]->(t:Transcript)
RETURN s.start_time, s.end_time, s.summary,
       collect(DISTINCT e.name) AS entities,
       collect(DISTINCT t.text) AS narration
ORDER BY s.start_time
```

### 4. Find Related Content Across Videos

```cypher
// Find similar scenes across all videos
MATCH (e:Entity {name: $entity_name})<-[:FEATURES_ENTITY]-(s:Scene)<-[:HAS_SCENE]-(v:Video)
WHERE v.user_id = $user_id
RETURN v.title, v.media_id, s.start_time, s.summary
LIMIT 20
```

### 5. Chapter Navigation

```cypher
// Get chapters with entity highlights
MATCH (v:Video {media_id: $media_id})-[:HAS_CHAPTER]->(c:Chapter)
OPTIONAL MATCH (v)-[:HAS_SCENE]->(s:Scene)-[:FEATURES_ENTITY]->(e:Entity)
WHERE s.start_time >= c.start_time AND s.end_time <= c.end_time
RETURN c.title, c.start_time, c.end_time, c.summary,
       collect(DISTINCT e.name) AS key_entities
ORDER BY c.start_time
```

### 6. Transcript Search with Context

```cypher
// Search transcripts and get surrounding context
MATCH (v:Video {media_id: $media_id})-[:HAS_TRANSCRIPT]->(t:Transcript)
WHERE t.text CONTAINS $search_term
OPTIONAL MATCH (t)-[:NEXT_SEGMENT]->(next:Transcript)
OPTIONAL MATCH (prev:Transcript)-[:NEXT_SEGMENT]->(t)
RETURN prev.text AS before, t.text AS match, next.text AS after,
       t.start_time, t.end_time
ORDER BY t.start_time
```

### 7. Entity Relationship Graph

```cypher
// Get entity relationship network
MATCH (e1:Entity)-[r:RELATED_TO]-(e2:Entity)
WHERE e1.entity_id IN $entity_ids OR e2.entity_id IN $entity_ids
RETURN e1.name, r.relation, e2.name, e1.type, e2.type
```

### 8. Scene Transition Analysis

```cypher
// Analyze scene transitions
MATCH (v:Video {media_id: $media_id})-[:HAS_SCENE]->(s1:Scene)-[:NEXT_SCENE]->(s2:Scene)
RETURN s1.summary AS from_scene,
       s2.summary AS to_scene,
       s1.end_time AS transition_time,
       duration.between(time(s1.end_time), time(s2.start_time)) AS gap
```

## Python Integration

```python
from services.knowledge_graph import get_knowledge_graph_service

async def execute_query(media_id: str, query_type: str):
    kg = get_knowledge_graph_service()

    if query_type == "entities":
        query = """
        MATCH (v:Video {media_id: $media_id})-[:HAS_FRAME]->(f:Frame)
              -[:CONTAINS_ENTITY]->(e:Entity)
        RETURN DISTINCT e.name, e.type, count(f) AS occurrences
        ORDER BY occurrences DESC
        """
        return await kg.execute_query(query, {"media_id": media_id})

    # ... other query types
```

## Index Management

```cypher
// Create vector index for semantic search
CREATE VECTOR INDEX frame_embeddings IF NOT EXISTS
FOR (f:Frame)
ON (f.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 3072,
  `vector.similarity_function`: 'cosine'
}}

// Create full-text index for transcript search
CREATE FULLTEXT INDEX transcript_text IF NOT EXISTS
FOR (t:Transcript)
ON EACH [t.text]

// Create composite index for efficient lookups
CREATE INDEX frame_media_timestamp IF NOT EXISTS
FOR (f:Frame)
ON (f.media_id, f.timestamp)
```

## Checklist for New Queries
- [ ] Use parameterized queries (never string interpolation)
- [ ] Include media_id filter for user data isolation
- [ ] Add LIMIT clause for unbounded queries
- [ ] Use OPTIONAL MATCH for nullable relationships
- [ ] Return timestamps in consistent format
- [ ] Include ORDER BY for predictable results
