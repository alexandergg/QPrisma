"""Video-MME benchmark adapter.

See :mod:`evaluation_foundry.benchmarks` for the cross-benchmark contract.

Public submodules:

* :mod:`evaluation_foundry.benchmarks.video_mme.ingest` — replays the production
  upload path for a configurable subset of Video-MME videos and writes a
  :class:`evaluation_foundry.benchmarks.BenchmarkManifest`.
* :mod:`evaluation_foundry.benchmarks.video_mme.emit_foundry_data` — walks the
  manifest + the upstream questions parquet and emits the JSONL consumed by
  ``microsoft/ai-agent-evals``.
"""
