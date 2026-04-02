"""
Foundry Hosted Agent Entry Point
=================================

Starts the QPrisma Video Agent as an Azure AI Foundry Hosted Agent.
Uses the ``from_langgraph()`` adapter to expose the existing
``VideoAgentGraph`` via Foundry's managed HTTP server (port 8088).

Usage (local dev):
    python -m agent.hosted.main

Usage (container):
    The Dockerfile CMD runs this module directly.

Protocols supported:
    - Responses API (OpenAI-compatible POST /responses)
    - A2A Protocol v0.2.1 (Agent-to-Agent task lifecycle)
"""

import logging
import os
import re
import sys

# Ensure the backend directory is on the Python path so that
# all QPrisma modules (agent, services, core, models) are importable.
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from core.logging_config import setup_logging  # noqa: E402

setup_logging()
logger = logging.getLogger(__name__)


def create_hosted_app():
    """
    Build the Foundry hosting adapter around the QPrisma video agent graph.

    Returns the adapter application that Foundry's runtime will serve.
    """
    from langgraph.checkpoint.memory import MemorySaver

    from agent.graphs.video import create_video_agent_graph

    try:
        from azure.ai.agentserver.langgraph import from_langgraph
    except ImportError as exc:
        logger.error(
            "azure-ai-agentserver-langgraph is not installed. "
            "Install with: pip install 'azure-ai-agentserver-langgraph>=1.0.0b17'"
        )
        raise SystemExit(1) from exc

    # Use MemorySaver for within-turn state.
    # Foundry manages cross-turn conversation persistence.
    checkpointer = MemorySaver()

    logger.info("Creating QPrisma VideoAgentGraph for Foundry hosted mode")
    graph = create_video_agent_graph(checkpointer=checkpointer)

    logger.info("Wrapping graph with Foundry from_langgraph() adapter")
    from agent.hosted.state_converter import QPrismaStateConverter

    converter = QPrismaStateConverter(graph=graph)
    app = from_langgraph(graph, converter=converter)
    logger.info("Using QPrismaStateConverter for media_id/media_ids injection")

    return app


def _setup_telemetry() -> None:
    """Configure Azure Monitor tracing for the hosted agent container."""
    import os

    conn_str = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        logger.info("Application Insights: not configured (no connection string)")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

        os.environ.setdefault("OTEL_SERVICE_NAME", "qprisma-hosted-agent")
        os.environ.setdefault("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "false")
        os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")

        configure_azure_monitor(connection_string=conn_str)
        OpenAIInstrumentor().instrument()

        # Register span processor so gen_ai.conversation.id appears in Foundry traces
        try:
            from opentelemetry.trace import get_tracer_provider

            from agent.utils.observability import ConversationIdSpanProcessor

            provider = get_tracer_provider()
            if hasattr(provider, "add_span_processor"):
                provider.add_span_processor(ConversationIdSpanProcessor())
                logger.info("ConversationIdSpanProcessor: registered")
        except Exception as e:
            logger.warning("ConversationIdSpanProcessor: failed to register (%s)", e)

        logger.info("Application Insights: enabled (service=qprisma-hosted-agent)")
    except ImportError:
        logger.warning(
            "Application Insights: packages not installed "
            "(pip install azure-monitor-opentelemetry opentelemetry-instrumentation-openai-v2)"
        )
    except Exception as e:
        logger.warning("Application Insights: failed to initialize (%s)", e)


def _mask_uri(uri: str) -> str:
    """Mask credentials in a connection URI for safe logging."""
    return re.sub(r"://[^@]*@", "://***:***@", uri)


def _check_service_health() -> None:
    """Log connectivity status for backend services at startup.

    Non-blocking — logs warnings but never prevents the agent from starting.
    """
    from core.config import settings

    # --- Neo4j ---
    try:
        neo4j_uri = settings.neo4j.uri
        logger.info("Neo4j: configured uri=%s, user=%s", neo4j_uri, settings.neo4j.user)
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()
        if kg.is_connected:
            logger.info("Neo4j: connected ✓")
        else:
            logger.warning("Neo4j: connection FAILED at %s", neo4j_uri)
    except Exception as e:
        logger.warning("Neo4j: health check error — %s", e)

    # --- PostgreSQL ---
    try:
        pg_url = settings.postgres.database_url
        logger.info("PostgreSQL: configured url=%s", _mask_uri(pg_url))
        from services.database_service import get_database_service

        db = get_database_service()
        health = db.health_check()
        if health.get("status") == "healthy":
            logger.info("PostgreSQL: connected ✓")
        else:
            logger.warning("PostgreSQL: connection FAILED — %s", health.get("error", "unknown"))
    except Exception as e:
        logger.warning("PostgreSQL: health check error — %s", e)

    # --- Redis ---
    try:
        redis_url = settings.redis.url
        logger.info("Redis: configured url=%s", _mask_uri(redis_url))
    except Exception as e:
        logger.warning("Redis: config check error — %s", e)


def main():
    """Start the Foundry hosted agent server."""
    logger.info("Starting QPrisma Video Agent (Foundry Hosted Mode)")
    logger.info("Protocols: Responses API + A2A v0.2.1 | Port: 8088")

    # Initialize tracing before the graph/adapter so spans are captured
    _setup_telemetry()

    # Log backend service connectivity (non-blocking)
    _check_service_health()

    app = create_hosted_app()

    # from_langgraph().run() starts the HTTP server on localhost:8088
    # Foundry's sidecar proxy handles external routing and TLS.
    app.run()


if __name__ == "__main__":
    main()
