"""
Ablation configuration for QPrisma evaluation.

Defines how each ablation variant modifies QPrisma's behavior for controlled
experiments. Each config specifies overrides for search parameters, modality
filtering, agent behavior, and token budgets.

Ablation Configs:
- full: Complete pipeline (no overrides)
- noagent: Single-shot RAG (bypass ReAct loop)
- flat: Flat embeddings (vector-only scoring, no graph/temporal signals)
- vectoronly: Vector similarity only (no reranking, no expansion)
- norerank: Disable LLM re-ranking
- visualonly: Visual frames only (no audio)
- audioonly: Transcript only (no visual frames)
- fixedtokens: Fixed token budget per frame
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AblationConfig:
    """Configuration overrides for an ablation experiment.

    Each field controls a specific aspect of QPrisma's pipeline.
    None values mean "use the default".
    """

    name: str

    # Agent behavior
    bypass_agent: bool = False  # If True, skip ReAct loop (single-shot RAG)
    max_tool_iterations: int | None = None  # Override MAX_TOOL_ITERATIONS

    # Search weights (must sum to 1.0 if provided)
    search_weights: dict[str, float] | None = None

    # Search parameters
    expansion_hops: int | None = None  # Override expansion_hops
    use_reranking: bool | None = None  # Override use_reranking
    search_limit: int | None = None  # Override result limit

    # Modality filtering
    include_visual: bool = True  # Include FRAME/SCENE nodes
    include_audio: bool = True  # Include AUDIO_SEGMENT nodes
    include_entities: bool = True  # Include ENTITY nodes

    # Token budget
    max_context_tokens: int | None = None  # Override MAX_CONTEXT_TOKENS


# =============================================================================
# Predefined Ablation Configs
# =============================================================================

ABLATION_CONFIGS: dict[str, AblationConfig] = {
    "full": AblationConfig(
        name="full",
    ),
    "noagent": AblationConfig(
        name="noagent",
        bypass_agent=True,
    ),
    "flat": AblationConfig(
        name="flat",
        search_weights={
            "vector": 1.0,
            "fulltext": 0.0,
            "graph": 0.0,
            "temporal": 0.0,
        },
        expansion_hops=0,
    ),
    "vectoronly": AblationConfig(
        name="vectoronly",
        search_weights={
            "vector": 1.0,
            "fulltext": 0.0,
            "graph": 0.0,
            "temporal": 0.0,
        },
        expansion_hops=0,
        use_reranking=False,
    ),
    "norerank": AblationConfig(
        name="norerank",
        use_reranking=False,
    ),
    "visualonly": AblationConfig(
        name="visualonly",
        include_audio=False,
    ),
    "audioonly": AblationConfig(
        name="audioonly",
        include_visual=False,
        include_entities=False,
    ),
    "fixedtokens": AblationConfig(
        name="fixedtokens",
        max_context_tokens=50000,  # Half the default 100k budget
    ),
}


def get_ablation_config(name: str) -> AblationConfig:
    """Get an ablation config by name.

    Args:
        name: Config name (one of the ABLATION_CONFIGS keys).

    Returns:
        AblationConfig instance.

    Raises:
        ValueError: If name is not recognized.
    """
    if name not in ABLATION_CONFIGS:
        valid = ", ".join(sorted(ABLATION_CONFIGS.keys()))
        raise ValueError(f"Unknown ablation config: {name}. Valid configs: {valid}")
    return ABLATION_CONFIGS[name]
