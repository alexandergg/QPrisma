"""
Test Search Quality Script
===========================

Diagnóstico de calidad de búsqueda para QPrisma.
Permite probar diferentes queries y ver qué resultados devuelve el sistema.

Uso:
    uv run python scripts/test_search_quality.py
    uv run python scripts/test_search_quality.py --video-id <VIDEO_ID>
    uv run python scripts/test_search_quality.py --query "buscar algo"
"""

import argparse
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.knowledge_graph import get_knowledge_graph_service


def list_videos():
    """Lista todos los videos indexados."""
    graph = get_knowledge_graph_service()
    graph.connect()

    query = """
    MATCH (v:Video)
    OPTIONAL MATCH (v)-[:CONTAINS]->(f:Frame)
    OPTIONAL MATCH (v)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
    WITH v, count(DISTINCT f) as frames, count(DISTINCT a) as audio_segs
    RETURN v.video_id as video_id, v.title as title,
           v.duration_seconds as duration, frames, audio_segs
    ORDER BY v.created_at DESC
    LIMIT 10
    """

    with graph.get_session() as session:
        result = session.run(query)
        videos = list(result)

    print("\n=== VIDEOS INDEXADOS ===")
    for v in videos:
        duration = v['duration'] or 0
        mins = int(duration // 60)
        secs = int(duration % 60)
        print(f"  [{v['video_id'][:8]}...] {v['title']}")
        print(f"      Duration: {mins}m {secs}s | Frames: {v['frames']} | Audio: {v['audio_segs']}")

    return videos


def get_video_stats(video_id: str):
    """Obtiene estadísticas detalladas de un video."""
    graph = get_knowledge_graph_service()
    if not graph.is_connected:
        graph.connect()

    # Stats with multiple relationship types
    query = """
    MATCH (v:Video)
    WHERE v.video_id = $video_id OR v.id = $video_id
    OPTIONAL MATCH (v)-[:CONTAINS]->(f:Frame)
    OPTIONAL MATCH (v)-[:HAS_TRANSCRIPT]->(a1:AudioSegment)
    OPTIONAL MATCH (a2:AudioSegment {video_id: $video_id})
    OPTIONAL MATCH (v)-[:CONTAINS]->(e:Entity)
    RETURN
        v.title as title,
        v.duration_seconds as duration,
        count(DISTINCT f) as frames,
        count(DISTINCT a1) as audio_via_rel,
        count(DISTINCT a2) as audio_via_prop,
        count(DISTINCT e) as entities
    """

    with graph.get_session() as session:
        result = session.run(query, video_id=video_id)
        record = result.single()

    if not record:
        print(f"\n❌ Video no encontrado: {video_id}")
        return None

    print(f"\n=== STATS: {record['title']} ===")
    duration = record['duration'] or 0
    print(f"  Duration: {int(duration//60)}m {int(duration%60)}s ({duration:.0f}s)")
    print(f"  Frames indexados: {record['frames']}")
    print(f"  Audio segments (via HAS_TRANSCRIPT): {record['audio_via_rel']}")
    print(f"  Audio segments (via video_id prop): {record['audio_via_prop']}")
    print(f"  Entities: {record['entities']}")

    # Calculate coverage
    if duration > 0 and record['frames'] > 0:
        avg_interval = duration / record['frames']
        print(f"  Frame coverage: 1 frame every {avg_interval:.1f}s")

    return record


def search_in_frames(video_id: str, search_term: str, limit: int = 10):
    """Busca un término directamente en las descripciones de frames."""
    graph = get_knowledge_graph_service()
    if not graph.is_connected:
        graph.connect()

    # Case-insensitive search
    query = """
    MATCH (f:Frame)
    WHERE f.video_id = $video_id
      AND toLower(f.description) CONTAINS toLower($search_term)
    RETURN f.timestamp as timestamp, f.description as description
    ORDER BY f.timestamp
    LIMIT $limit
    """

    with graph.get_session() as session:
        result = session.run(query, video_id=video_id, search_term=search_term, limit=limit)
        frames = list(result)

    print(f"\n=== FRAMES containing '{search_term}' ===")
    if frames:
        for f in frames:
            ts = f['timestamp'] or 0
            mins = int(ts // 60)
            secs = int(ts % 60)
            desc = (f['description'] or '')[:200]
            print(f"  [{mins}:{secs:02d}]: {desc}...")
    else:
        print("  ❌ No matches in frame descriptions")

    return frames


def search_in_transcripts(video_id: str, search_term: str, limit: int = 10):
    """Busca un término en las transcripciones de audio."""
    graph = get_knowledge_graph_service()
    if not graph.is_connected:
        graph.connect()

    # Try via relationship first
    query_rel = """
    MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
    WHERE (v.video_id = $video_id OR v.id = $video_id)
      AND toLower(a.text) CONTAINS toLower($search_term)
    RETURN a.start_time as start_time, a.end_time as end_time, a.text as text
    ORDER BY a.start_time
    LIMIT $limit
    """

    # Fallback: via property
    query_prop = """
    MATCH (a:AudioSegment)
    WHERE a.video_id = $video_id
      AND toLower(a.text) CONTAINS toLower($search_term)
    RETURN a.start_time as start_time, a.end_time as end_time, a.text as text
    ORDER BY a.start_time
    LIMIT $limit
    """

    segments = []
    with graph.get_session() as session:
        result = session.run(query_rel, video_id=video_id, search_term=search_term, limit=limit)
        segments = list(result)

        if not segments:
            result = session.run(query_prop, video_id=video_id, search_term=search_term, limit=limit)
            segments = list(result)

    print(f"\n=== TRANSCRIPTS containing '{search_term}' ===")
    if segments:
        for s in segments:
            start = s['start_time'] or 0
            end = s['end_time'] or 0
            start_mins = int(start // 60)
            start_secs = int(start % 60)
            end_mins = int(end // 60)
            end_secs = int(end % 60)
            text = (s['text'] or '')[:150]
            print(f"  [{start_mins}:{start_secs:02d} - {end_mins}:{end_secs:02d}]: {text}...")
    else:
        print("  ❌ No matches in transcripts")

    return segments


def fulltext_search(video_id: str, search_term: str, limit: int = 10):
    """Búsqueda fulltext usando índices de Neo4j."""
    graph = get_knowledge_graph_service()
    if not graph.is_connected:
        graph.connect()

    results = []

    # Search in frames
    try:
        query_frames = """
        CALL db.index.fulltext.queryNodes('frame_search', $search_term)
        YIELD node, score
        WHERE node.video_id = $video_id
        RETURN 'FRAME' as type, node.timestamp as time, node.description as content, score
        ORDER BY score DESC
        LIMIT $limit
        """
        with graph.get_session() as session:
            result = session.run(query_frames, video_id=video_id, search_term=search_term, limit=limit)
            results.extend(list(result))
    except Exception as e:
        print(f"  (Frame fulltext search failed: {e})")

    # Search in audio
    try:
        query_audio = """
        CALL db.index.fulltext.queryNodes('audio_search', $search_term)
        YIELD node, score
        WHERE node.video_id = $video_id
        RETURN 'AUDIO' as type, node.start_time as time, node.text as content, score
        ORDER BY score DESC
        LIMIT $limit
        """
        with graph.get_session() as session:
            result = session.run(query_audio, video_id=video_id, search_term=search_term, limit=limit)
            results.extend(list(result))
    except Exception as e:
        print(f"  (Audio fulltext search failed: {e})")

    # Sort by score
    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n=== FULLTEXT SEARCH: '{search_term}' ===")
    if results:
        for r in results[:limit]:
            ts = r['time'] or 0
            mins = int(ts // 60)
            secs = int(ts % 60)
            content = (r['content'] or '')[:120]
            print(f"  [{r['type']}] [{mins}:{secs:02d}] (score={r['score']:.2f}): {content}...")
    else:
        print("  ❌ No fulltext matches")

    return results


def sample_content(video_id: str, num_samples: int = 5):
    """Muestra samples de frames y transcripts."""
    graph = get_knowledge_graph_service()
    if not graph.is_connected:
        graph.connect()

    # Sample frames
    query_frames = """
    MATCH (f:Frame)
    WHERE f.video_id = $video_id AND f.description IS NOT NULL
    RETURN f.timestamp as ts, f.description as desc
    ORDER BY f.timestamp
    """

    with graph.get_session() as session:
        result = session.run(query_frames, video_id=video_id)
        all_frames = list(result)

    print(f"\n=== SAMPLE FRAMES ({len(all_frames)} total) ===")
    if all_frames:
        step = max(1, len(all_frames) // num_samples)
        for f in all_frames[::step][:num_samples]:
            ts = f['ts'] or 0
            mins = int(ts // 60)
            secs = int(ts % 60)
            desc = (f['desc'] or '')[:250]
            print(f"\n  [{mins}:{secs:02d}]: {desc}...")
    else:
        print("  ❌ No frames")

    # Sample audio
    query_audio = """
    MATCH (a:AudioSegment)
    WHERE a.video_id = $video_id AND a.text IS NOT NULL
    RETURN a.start_time as start, a.text as text
    ORDER BY a.start_time
    """

    with graph.get_session() as session:
        result = session.run(query_audio, video_id=video_id)
        all_audio = list(result)

    print(f"\n=== SAMPLE TRANSCRIPTS ({len(all_audio)} total) ===")
    if all_audio:
        step = max(1, len(all_audio) // num_samples)
        for a in all_audio[::step][:num_samples]:
            ts = a['start'] or 0
            mins = int(ts // 60)
            secs = int(ts % 60)
            text = (a['text'] or '')[:200]
            print(f"\n  [{mins}:{secs:02d}]: {text}...")
    else:
        print("  ❌ No transcripts")


def run_test_queries(video_id: str, queries: list[str]):
    """Ejecuta una batería de queries de prueba."""
    print("\n" + "=" * 60)
    print("TESTING SEARCH QUERIES")
    print("=" * 60)

    for query in queries:
        print(f"\n{'='*60}")
        print(f"QUERY: '{query}'")
        print("=" * 60)

        search_in_frames(video_id, query, limit=5)
        search_in_transcripts(video_id, query, limit=5)
        fulltext_search(video_id, query, limit=5)


def main():
    parser = argparse.ArgumentParser(description="Test QPrisma search quality")
    parser.add_argument("--video-id", "-v", help="Specific video ID to test")
    parser.add_argument("--query", "-q", help="Specific query to test")
    parser.add_argument("--samples", "-s", type=int, default=3, help="Number of samples to show")
    args = parser.parse_args()

    print("=" * 60)
    print("QPrisma Search Quality Diagnostic")
    print("=" * 60)

    # List videos
    videos = list_videos()

    if not videos:
        print("\n❌ No videos found. Process a video first.")
        return

    # Select video
    if args.video_id:
        video_id = args.video_id
    else:
        video_id = videos[0]['video_id']

    print(f"\n📹 Testing video: {video_id[:16]}...")

    # Get stats
    stats = get_video_stats(video_id)
    if not stats:
        return

    # Sample content
    sample_content(video_id, args.samples)

    # Run queries
    if args.query:
        queries = [args.query]
    else:
        # Default test queries
        queries = [
            "Azure",
            "Microsoft",
            "Cobalt",
            "silicon",
            "chip",
            "AI",
            "cloud",
        ]

    run_test_queries(video_id, queries)

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
