# Search Knowledge Graph

Query and explore the Neo4j Knowledge Graph for video content.

## Usage
```
/search-knowledge-graph <query> [--media <media_id>] [--type semantic|cypher|hybrid]
```

## Search Types

### 1. Semantic Search (Vector-based)
Uses embeddings to find similar content.

```python
from services.knowledge_graph import get_knowledge_graph_service

kg = get_knowledge_graph_service()

# Search by natural language
results = await kg.semantic_search(
    query="person speaking at podium",
    media_id="abc123",  # Optional: filter by video
    top_k=10,
    min_score=0.7,
)

for r in results:
    print(f"{r['timestamp']}s: {r['description']} (score: {r['score']:.2f})")
```

### 2. Cypher Query (Direct Graph)
Query the graph directly with Cypher.

```cypher
// Find all entities in a video
MATCH (v:Video {id: $media_id})-[:HAS_FRAME]->(f:Frame)-[:CONTAINS]->(e:Entity)
RETURN DISTINCT e.name, e.type, count(f) as appearances
ORDER BY appearances DESC

// Find frames with specific content
MATCH (v:Video {id: $media_id})-[:HAS_FRAME]->(f:Frame)
WHERE f.description CONTAINS 'person'
RETURN f.timestamp, f.description
ORDER BY f.timestamp

// Find related entities
MATCH (e1:Entity {name: $entity_name})-[r]-(e2:Entity)
RETURN e1.name, type(r), e2.name

// Timeline of activities
MATCH (v:Video {id: $media_id})-[:HAS_FRAME]->(f:Frame)-[:CONTAINS]->(a:Activity)
RETURN f.timestamp, a.description
ORDER BY f.timestamp

// Find speakers in transcript
MATCH (v:Video {id: $media_id})-[:HAS_SEGMENT]->(s:TranscriptSegment)
WHERE s.speaker IS NOT NULL
RETURN s.speaker, s.start_time, s.text
ORDER BY s.start_time
```

### 3. Hybrid Search
Combines semantic and graph queries.

```python
# Hybrid search with entity expansion
results = await kg.hybrid_search(
    query="CEO presenting quarterly results",
    media_id="abc123",
    expand_entities=True,  # Include related entities
    expand_hops=2,         # Relationship depth
)
```

## API Endpoints

### Search Video Content
```bash
curl -X POST "http://localhost:8000/graph/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "person at podium",
    "media_id": "abc123",
    "top_k": 10,
    "include_context": true
  }'
```

### Get Video Hierarchy
```bash
curl "http://localhost:8000/graph/hierarchy/abc123" \
  -H "Authorization: Bearer $TOKEN"

# Response
{
  "video": {"id": "abc123", "title": "Keynote"},
  "chapters": [
    {"start": 0, "title": "Introduction"},
    {"start": 120, "title": "Demo"}
  ],
  "entities": [
    {"name": "John Smith", "type": "Person", "mentions": 5}
  ]
}
```

### Execute Cypher Query
```bash
curl -X POST "http://localhost:8000/graph/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "cypher": "MATCH (v:Video)-[:HAS_FRAME]->(f:Frame) WHERE v.id = $media_id RETURN count(f)",
    "params": {"media_id": "abc123"}
  }'
```

## Graph Schema

### Nodes
```cypher
// Video node
(:Video {
  id: string,
  title: string,
  duration: float,
  created_at: datetime
})

// Frame node
(:Frame {
  id: string,
  timestamp: float,
  description: string,
  embedding: list[float]  // Vector embedding
})

// Entity node
(:Entity {
  id: string,
  name: string,
  type: "Person" | "Object" | "Location" | "Organization",
  embedding: list[float]
})

// Transcript segment
(:TranscriptSegment {
  id: string,
  start_time: float,
  end_time: float,
  text: string,
  speaker: string | null,
  embedding: list[float]
})

// Activity/Action
(:Activity {
  id: string,
  description: string,
  start_time: float,
  end_time: float
})
```

### Relationships
```cypher
(Video)-[:HAS_FRAME]->(Frame)
(Video)-[:HAS_SEGMENT]->(TranscriptSegment)
(Frame)-[:CONTAINS]->(Entity)
(Frame)-[:SHOWS_ACTIVITY]->(Activity)
(Frame)-[:NEXT]->(Frame)
(Entity)-[:APPEARS_WITH]->(Entity)
(Entity)-[:PERFORMS]->(Activity)
(TranscriptSegment)-[:MENTIONS]->(Entity)
```

## Programmatic Usage

### Search Service
```python
from services.knowledge_graph import get_knowledge_graph_service
from services.embedding_service import get_embedding_service

async def search_video_content(media_id: str, query: str):
    kg = get_knowledge_graph_service()
    embedding_service = get_embedding_service()

    # Generate query embedding
    query_embedding = await embedding_service.embed_text(query)

    # Vector search
    results = await kg.vector_search(
        index_name="frame_embeddings",
        embedding=query_embedding,
        top_k=10,
        filters={"video_id": media_id},
    )

    return results
```

### Entity Extraction
```python
async def find_entities(media_id: str, entity_type: str = None):
    kg = get_knowledge_graph_service()

    cypher = """
    MATCH (v:Video {id: $media_id})-[:HAS_FRAME]->(f:Frame)-[:CONTAINS]->(e:Entity)
    WHERE $entity_type IS NULL OR e.type = $entity_type
    RETURN e.name, e.type, collect(DISTINCT f.timestamp) as timestamps
    ORDER BY size(timestamps) DESC
    """

    return await kg.execute_query(cypher, {
        "media_id": media_id,
        "entity_type": entity_type,
    })
```

### Timeline Generation
```python
async def generate_timeline(media_id: str):
    kg = get_knowledge_graph_service()

    cypher = """
    MATCH (v:Video {id: $media_id})-[:HAS_FRAME]->(f:Frame)
    OPTIONAL MATCH (f)-[:SHOWS_ACTIVITY]->(a:Activity)
    OPTIONAL MATCH (f)-[:CONTAINS]->(e:Entity)
    RETURN f.timestamp, f.description,
           collect(DISTINCT a.description) as activities,
           collect(DISTINCT e.name) as entities
    ORDER BY f.timestamp
    """

    return await kg.execute_query(cypher, {"media_id": media_id})
```

## Index Management

### Create Vector Index
```cypher
// Frame embeddings index
CALL db.index.vector.createNodeIndex(
  'frame_embeddings',
  'Frame',
  'embedding',
  1536,  // Dimension for text-embedding-3-large
  'cosine'
)

// Entity embeddings index
CALL db.index.vector.createNodeIndex(
  'entity_embeddings',
  'Entity',
  'embedding',
  1536,
  'cosine'
)

// Transcript embeddings index
CALL db.index.vector.createNodeIndex(
  'transcript_embeddings',
  'TranscriptSegment',
  'embedding',
  1536,
  'cosine'
)
```

### Check Index Status
```cypher
SHOW INDEXES
WHERE type = 'VECTOR'
```

## Performance Tips

1. **Use indexes for frequent queries**
   ```cypher
   CREATE INDEX video_id FOR (v:Video) ON (v.id)
   CREATE INDEX frame_timestamp FOR (f:Frame) ON (f.timestamp)
   ```

2. **Limit vector search results**
   ```python
   results = await kg.vector_search(..., top_k=10)  # Not 1000
   ```

3. **Use APOC for complex aggregations**
   ```cypher
   CALL apoc.agg.statistics(scores) YIELD mean, stdev
   ```

4. **Profile slow queries**
   ```cypher
   PROFILE MATCH (v:Video)-[:HAS_FRAME]->(f) RETURN count(f)
   ```

## Checklist
- [ ] Query type selected (semantic/cypher/hybrid)
- [ ] media_id provided if filtering by video
- [ ] Results limited to reasonable count
- [ ] Vector index exists for semantic search
- [ ] Query parameters properly escaped
