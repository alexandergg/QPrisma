"""
Tests for QPrisma evaluation ablation configs, download helpers, and indexing helpers.

Covers:
- AblationConfig definitions and get_ablation_config()
- QPrismaAdapter ablation wiring
- Download script helpers (_parse_video_mme_choices, _map_duration_tier)
- Indexing script helpers (_find_video_file, _format_size)
- Config file validation
"""

import json
import tempfile
from pathlib import Path

import pytest

from evaluation.ablation import ABLATION_CONFIGS, AblationConfig, get_ablation_config


# =============================================================================
# AblationConfig Tests
# =============================================================================


class TestAblationConfig:
    def test_all_configs_defined(self):
        expected = {
            "full", "noagent", "flat", "vectoronly",
            "norerank", "visualonly", "audioonly", "fixedtokens",
        }
        assert set(ABLATION_CONFIGS.keys()) == expected

    def test_full_config_has_no_overrides(self):
        cfg = get_ablation_config("full")
        assert cfg.bypass_agent is False
        assert cfg.search_weights is None
        assert cfg.expansion_hops is None
        assert cfg.use_reranking is None
        assert cfg.include_visual is True
        assert cfg.include_audio is True
        assert cfg.include_entities is True
        assert cfg.max_context_tokens is None

    def test_noagent_bypasses_loop(self):
        cfg = get_ablation_config("noagent")
        assert cfg.bypass_agent is True

    def test_flat_uses_vector_only_weights(self):
        cfg = get_ablation_config("flat")
        assert cfg.search_weights["vector"] == 1.0
        assert cfg.search_weights["fulltext"] == 0.0
        assert cfg.search_weights["graph"] == 0.0
        assert cfg.search_weights["temporal"] == 0.0
        assert cfg.expansion_hops == 0

    def test_vectoronly_disables_reranking(self):
        cfg = get_ablation_config("vectoronly")
        assert cfg.use_reranking is False
        assert cfg.expansion_hops == 0
        assert cfg.search_weights["vector"] == 1.0

    def test_norerank_only_disables_reranking(self):
        cfg = get_ablation_config("norerank")
        assert cfg.use_reranking is False
        # Everything else should be default
        assert cfg.search_weights is None
        assert cfg.expansion_hops is None
        assert cfg.include_visual is True
        assert cfg.include_audio is True

    def test_visualonly_excludes_audio(self):
        cfg = get_ablation_config("visualonly")
        assert cfg.include_visual is True
        assert cfg.include_audio is False
        assert cfg.include_entities is True

    def test_audioonly_excludes_visual(self):
        cfg = get_ablation_config("audioonly")
        assert cfg.include_visual is False
        assert cfg.include_audio is True
        assert cfg.include_entities is False

    def test_fixedtokens_has_budget(self):
        cfg = get_ablation_config("fixedtokens")
        assert cfg.max_context_tokens == 50000

    def test_unknown_config_raises(self):
        with pytest.raises(ValueError, match="Unknown ablation config"):
            get_ablation_config("nonexistent")

    def test_configs_are_frozen(self):
        cfg = get_ablation_config("full")
        with pytest.raises(AttributeError):
            cfg.bypass_agent = True

    def test_search_weights_sum_to_one(self):
        """Verify that configs with custom weights sum to 1.0."""
        for name, cfg in ABLATION_CONFIGS.items():
            if cfg.search_weights is not None:
                total = sum(cfg.search_weights.values())
                assert total == pytest.approx(1.0), f"{name} weights sum to {total}"


# =============================================================================
# QPrismaAdapter Ablation Tests
# =============================================================================


class TestQPrismaAdapterAblation:
    def test_adapter_loads_correct_config(self):
        from evaluation.adapters.qprisma_adapter import QPrismaAdapter

        adapter = QPrismaAdapter(config_name="norerank")
        assert adapter.ablation.name == "norerank"
        assert adapter.ablation.use_reranking is False

    def test_adapter_name_format(self):
        from evaluation.adapters.qprisma_adapter import QPrismaAdapter

        adapter = QPrismaAdapter(config_name="visualonly")
        assert adapter.name == "qprisma-visualonly"
        assert "Visual Only" in adapter.display_name

    def test_adapter_invalid_config_raises(self):
        from evaluation.adapters.qprisma_adapter import QPrismaAdapter

        with pytest.raises(ValueError):
            QPrismaAdapter(config_name="nonexistent")

    def test_needs_search_patch_for_modality(self):
        from evaluation.adapters.qprisma_adapter import QPrismaAdapter

        adapter = QPrismaAdapter(config_name="audioonly")
        assert adapter._needs_search_patch() is True

    def test_no_search_patch_for_full(self):
        from evaluation.adapters.qprisma_adapter import QPrismaAdapter

        adapter = QPrismaAdapter(config_name="full")
        assert adapter._needs_search_patch() is False

    def test_no_search_patch_for_noagent(self):
        from evaluation.adapters.qprisma_adapter import QPrismaAdapter

        adapter = QPrismaAdapter(config_name="noagent")
        # noagent only bypasses agent, no search patches needed
        assert adapter._needs_search_patch() is False


# =============================================================================
# Download Script Helper Tests
# =============================================================================


class TestDownloadHelpers:
    def test_parse_choices_options_field(self):
        from evaluation.scripts.download_benchmarks import _parse_video_mme_choices

        row = {"options": ["A. cat", "B. dog", "C. bird", "D. fish"]}
        choices = _parse_video_mme_choices(row)
        assert len(choices) == 4
        assert "A. cat" in choices[0]

    def test_parse_choices_separate_fields(self):
        from evaluation.scripts.download_benchmarks import _parse_video_mme_choices

        row = {"option_A": "cat", "option_B": "dog", "option_C": "bird", "option_D": "fish"}
        choices = _parse_video_mme_choices(row)
        assert len(choices) == 4
        assert choices[0] == "cat"

    def test_parse_choices_candidates_field(self):
        from evaluation.scripts.download_benchmarks import _parse_video_mme_choices

        row = {"candidates": ["cat", "dog", "bird"]}
        choices = _parse_video_mme_choices(row)
        assert len(choices) == 3

    def test_parse_choices_empty(self):
        from evaluation.scripts.download_benchmarks import _parse_video_mme_choices

        assert _parse_video_mme_choices({}) == []

    def test_map_duration_tier_short(self):
        from evaluation.scripts.download_benchmarks import _map_duration_tier

        assert _map_duration_tier("short") == "short"
        assert _map_duration_tier("Short") == "short"

    def test_map_duration_tier_medium(self):
        from evaluation.scripts.download_benchmarks import _map_duration_tier

        assert _map_duration_tier("medium") == "medium"

    def test_map_duration_tier_long(self):
        from evaluation.scripts.download_benchmarks import _map_duration_tier

        assert _map_duration_tier("long") == "long"

    def test_map_duration_tier_unknown(self):
        from evaluation.scripts.download_benchmarks import _map_duration_tier

        assert _map_duration_tier("unknown") == "medium"

    def test_estimate_tier_from_seconds(self):
        from evaluation.scripts.download_benchmarks import _estimate_tier_from_seconds

        assert _estimate_tier_from_seconds(30) == "short"
        assert _estimate_tier_from_seconds(300) == "medium"
        assert _estimate_tier_from_seconds(1800) == "long"
        assert _estimate_tier_from_seconds(5000) == "very_long"
        assert _estimate_tier_from_seconds(None) == "medium"


# =============================================================================
# Indexing Script Helper Tests
# =============================================================================


class TestIndexingHelpers:
    def test_find_video_file_direct(self):
        from evaluation.scripts.index_videos import _find_video_file

        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "v1.mp4"
            video.write_bytes(b"fake")

            result = _find_video_file(Path(tmpdir), "v1")
            assert result == video

    def test_find_video_file_subdirectory(self):
        from evaluation.scripts.index_videos import _find_video_file

        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "short"
            subdir.mkdir()
            video = subdir / "v1.mp4"
            video.write_bytes(b"fake")

            result = _find_video_file(Path(tmpdir), "v1")
            assert result == video

    def test_find_video_file_not_found(self):
        from evaluation.scripts.index_videos import _find_video_file

        with tempfile.TemporaryDirectory() as tmpdir:
            result = _find_video_file(Path(tmpdir), "nonexistent")
            assert result is None

    def test_find_video_file_mkv(self):
        from evaluation.scripts.index_videos import _find_video_file

        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "v1.mkv"
            video.write_bytes(b"fake")

            result = _find_video_file(Path(tmpdir), "v1")
            assert result == video

    def test_format_size(self):
        from evaluation.scripts.index_videos import _format_size

        assert "B" in _format_size(500)
        assert "KB" in _format_size(5000)
        assert "MB" in _format_size(5_000_000)
        assert "GB" in _format_size(5_000_000_000)


# =============================================================================
# Config File Validation Tests
# =============================================================================


class TestConfigFiles:
    def _load_config(self, name):
        from evaluation.models.eval_schemas import EvalConfig

        config_path = (
            Path(__file__).parent.parent / "evaluation" / "configs" / f"{name}.json"
        )
        assert config_path.exists(), f"Config not found: {config_path}"
        return EvalConfig.model_validate_json(config_path.read_text())

    def test_quick_test_config(self):
        config = self._load_config("quick_test")
        assert len(config.benchmarks) == 1
        assert len(config.methods) == 2
        assert config.num_runs == 1
        assert config.use_batch_api is False

    def test_video_mme_full_config(self):
        config = self._load_config("video_mme_full")
        assert len(config.methods) == 5
        assert config.num_runs == 5
        assert config.use_batch_api is True
        assert config.use_position_debiasing is True

    def test_ablation_study_config(self):
        config = self._load_config("ablation_study")
        method_names = [m.name for m in config.methods]
        assert "qprisma-full" in method_names
        assert "qprisma-noagent" in method_names
        assert "qprisma-flat" in method_names
        assert "qprisma-vectoronly" in method_names
        assert "qprisma-norerank" in method_names
        assert "qprisma-visualonly" in method_names
        assert "qprisma-audioonly" in method_names
        assert "qprisma-fixedtokens" in method_names
        assert "naive-rag" in method_names
        assert len(config.methods) == 9

    def test_mlvu_full_config(self):
        config = self._load_config("mlvu_full")
        assert config.benchmarks[0].name == "mlvu"
        assert len(config.methods) == 4

    def test_all_configs_have_baseline(self):
        for name in ["quick_test", "video_mme_full", "ablation_study", "mlvu_full"]:
            config = self._load_config(name)
            method_names = [m.name for m in config.methods]
            assert config.baseline_method in method_names, (
                f"Baseline '{config.baseline_method}' not in methods for {name}"
            )
