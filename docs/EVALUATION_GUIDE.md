# Azure AI Foundry Evaluation Guide

QPrisma uses **Azure AI Foundry** to measure how well the hosted video agent answers questions, selects tools, grounds evidence, handles safety scenarios, and exposes debugging artifacts when something goes wrong.

This guide shows how the current workflow works, what Azure AI Foundry surfaces during evaluation, and how the cluster-analysis artifacts help diagnose failure patterns beyond a single score.

## What QPrisma measures

QPrisma evaluates the hosted agent from multiple angles:

| Area | What it measures | Where it comes from |
|---|---|---|
| Quality evaluation | Answer clarity, coherence, relevance, and task adherence | `microsoft/ai-agent-evals@v3-beta` against `quality-eval.json` |
| Agent evaluation | Tool selection, tool-call accuracy, tool-output use, task completion, and intent resolution | `microsoft/ai-agent-evals@v3-beta` against `agent-eval.json` |
| Safety evaluation | Safety and adversarial behavior coverage | `microsoft/ai-agent-evals@v3-beta` against `safety-eval.json` |
| Optional red teaming | Direct-attack and jailbreak resilience | `python -m evaluation_foundry.redteam_eval` |
| Artifact analysis | Run details, conversations, responses, and cluster-analysis exports | Azure AI Foundry portal + downloaded CSV artifacts |

## External prerequisites

Before running the evaluation flow, QPrisma needs:

- A deployed Azure AI Foundry project and hosted agent (`qprisma-video-agent`)
- `FOUNDRY_PROJECT_ENDPOINT` configured in repository variables
- Evaluation media IDs and an evaluation user identity (`EVAL_MEDIA_ID_1`, `EVAL_MEDIA_ID_2`, `EVAL_USER_ID`)
- Azure OIDC access from GitHub Actions for the evaluation workflow

## End-to-end workflow

The evaluation workflow lives in [`.github/workflows/evaluate-agent.yml`](../.github/workflows/evaluate-agent.yml) and currently runs as a manual `workflow_dispatch`.

1. **Generate evaluation data**: `backend/evaluation_foundry/generate_eval_data.py` produces quality, agent, and safety datasets from environment-backed media and user context.
2. **Resolve the agent version**: `scripts/resolve_agent_version.py` finds the current deployed agent version unless the workflow input overrides it.
3. **Run parallel evaluation jobs**: Azure AI Foundry runs separate quality, agent, and safety evaluation jobs by using `microsoft/ai-agent-evals@v3-beta`.
4. **Persist portal artifacts**: The Foundry portal captures run status, raw results, conversations, response payloads, and cluster-analysis exports.
5. **Optionally run AI Red Teaming**: The workflow can launch `evaluation_foundry.redteam_eval` when `run-redteam=true` so higher-cost security probing stays explicit.

## Why Azure AI Foundry is useful here

Azure AI Foundry does more than return aggregate scores. It gives QPrisma a repeatable evaluation loop:

- **Version-aware runs** tied to the exact hosted-agent revision under test
- **Separate evaluation lanes** for quality, tool behavior, and safety
- **Portal-native debugging surfaces** for logs, conversations, and raw responses
- **AI-clustered failure analysis** that groups recurring issues and proposes corrective directions
- **Downloadable artifacts** that can be summarized in project documentation or compared across runs

## Portal walkthrough

### 1. Start from the hosted agent and its evaluation surfaces

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/agent-overview-entrypoint.png">
        <img src="./assets/evaluation/agent-overview-entrypoint.png" alt="Azure AI Foundry QPrisma hosted agent entrypoint" width="100%">
      </a>
      <br>
      <strong>Hosted agent entrypoint</strong><br>
      The QPrisma hosted agent is the anchor for evaluation. From here, Azure AI Foundry exposes publishing, playground, traces, monitor, and evaluation entry points around the same deployed agent.
    </td>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/agent-overview-evaluation-tab.png">
        <img src="./assets/evaluation/agent-overview-evaluation-tab.png" alt="Azure AI Foundry hosted agent page with evaluation tab selected" width="100%">
      </a>
      <br>
      <strong>Evaluation tab on the agent</strong><br>
      The evaluation surface sits directly on the agent experience, which makes it easier to move from deployment into measurement without losing the hosted-agent context.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/agent-overview-traces-monitor-evaluation.png">
        <img src="./assets/evaluation/agent-overview-traces-monitor-evaluation.png" alt="Azure AI Foundry hosted agent page with traces, monitor, and evaluation navigation visible" width="100%">
      </a>
      <br>
      <strong>Traces, monitor, and evaluation together</strong><br>
      QPrisma benefits from having traces, monitoring, and evaluations close together because evaluation failures can be correlated with concrete runtime behavior instead of treated as isolated scores.
    </td>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/agent-overview-monitor-tab.png">
        <img src="./assets/evaluation/agent-overview-monitor-tab.png" alt="Azure AI Foundry monitor surface for the QPrisma hosted agent" width="100%">
      </a>
      <br>
      <strong>Monitor surface</strong><br>
      The monitor view complements evaluation runs by showing the operational surface around the same agent, which is useful when quality issues and runtime behavior need to be reviewed together.
    </td>
  </tr>
</table>

### 2. Review evaluation runs and results

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/evaluation-run-details-overview.png">
        <img src="./assets/evaluation/evaluation-run-details-overview.png" alt="Azure AI Foundry evaluation details page for a QPrisma agent evaluation run" width="100%">
      </a>
      <br>
      <strong>Run overview</strong><br>
      The evaluation details page gives QPrisma a durable record of who created the run, when it was created, and how to inspect the raw evaluation payload.
    </td>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/evaluation-run-details-properties.png">
        <img src="./assets/evaluation/evaluation-run-details-properties.png" alt="Azure AI Foundry evaluation run properties for QPrisma" width="100%">
      </a>
      <br>
      <strong>Run properties</strong><br>
      Foundry keeps enough run metadata to understand which evaluation configuration produced the outcome, which is useful for comparing runs after prompt, tool, or agent changes.
    </td>
  </tr>
  <tr>
    <td colspan="2" valign="top">
      <a href="./assets/evaluation/evaluation-run-details-results.png">
        <img src="./assets/evaluation/evaluation-run-details-results.png" alt="Azure AI Foundry evaluation run results for a completed QPrisma run" width="100%">
      </a>
      <br>
      <strong>Completed results view</strong><br>
      A completed run surfaces results, logs, and user-level details. This is where QPrisma can validate whether a hosted-agent revision improved the target behavior or regressed it.
    </td>
  </tr>
</table>

### 3. Inspect conversations and raw response artifacts

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/conversation-completed-run.png">
        <img src="./assets/evaluation/conversation-completed-run.png" alt="Azure AI Foundry completed evaluation conversation for QPrisma" width="100%">
      </a>
      <br>
      <strong>Completed evaluation conversation</strong><br>
      Conversation-level artifacts are useful for tracing what the evaluator actually observed, especially when a run score does not immediately explain the user-visible failure.
    </td>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/conversation-response-details-overview.png">
        <img src="./assets/evaluation/conversation-response-details-overview.png" alt="Azure AI Foundry response details overview for a QPrisma evaluation conversation" width="100%">
      </a>
      <br>
      <strong>Response payload inspection</strong><br>
      Raw response details make it possible to inspect the actual content stored for evaluation, which helps when a failure is caused by malformed or incomplete answers.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/conversation-response-details-mid.png">
        <img src="./assets/evaluation/conversation-response-details-mid.png" alt="Azure AI Foundry response details for a QPrisma evaluation sample" width="100%">
      </a>
      <br>
      <strong>Response detail drill-down</strong><br>
      These deeper response views help verify whether the final assistant content, tool traces, and stored response objects match the expected evaluation shape.
    </td>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/conversation-response-details-late.png">
        <img src="./assets/evaluation/conversation-response-details-late.png" alt="Azure AI Foundry detailed response artifact view for QPrisma" width="100%">
      </a>
      <br>
      <strong>Artifact-level debugging</strong><br>
      This artifact-oriented view is especially important for debugging response-shape issues and final-answer serialization problems that do not show up as obvious prompt failures.
    </td>
  </tr>
</table>

### 4. Foundry project surfaces around the evaluation flow

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/foundry-data-datasets-navigation.png">
        <img src="./assets/evaluation/foundry-data-datasets-navigation.png" alt="Azure AI Foundry data and datasets navigation relevant to evaluation assets" width="100%">
      </a>
      <br>
      <strong>Data and datasets surface</strong><br>
      The data area is relevant because QPrisma evaluation inputs originate from generated datasets, and Foundry keeps those dataset-oriented surfaces close to evaluation workflows.
    </td>
    <td width="50%" valign="top">
      <a href="./assets/evaluation/foundry-agents-home.png">
        <img src="./assets/evaluation/foundry-agents-home.png" alt="Azure AI Foundry agents home page" width="100%">
      </a>
      <br>
      <strong>Agents home</strong><br>
      Foundry keeps agent authoring and evaluation within the same product space, which lowers the friction between building a hosted agent and measuring whether it behaves correctly.
    </td>
  </tr>
</table>

## Cluster analysis as an Azure AI Foundry artifact

One of the most useful Azure AI Foundry outputs for QPrisma is the **cluster analysis** view. Instead of leaving teams with a long list of failing rows, Foundry groups similar failures together, labels the clusters, and adds AI suggestions about how to improve the agent.

<p align="center">
  <a href="./assets/evaluation/evaluation-cluster-analysis-tooling.png">
    <img src="./assets/evaluation/evaluation-cluster-analysis-tooling.png" alt="Azure AI Foundry cluster analysis for QPrisma hosted agent evaluation" width="100%">
  </a>
  <br>
  <em>The cluster-analysis view groups failures, shows AI-generated suggestions, and lets QPrisma focus on recurring failure modes instead of isolated examples.</em>
</p>

### Downloadable artifact summaries

- [Agent evaluation cluster CSV](./assets/evaluation/cluster-insights-agent-eval.csv)
- [Quality evaluation cluster CSV](./assets/evaluation/cluster-insights-quality-eval.csv)

The two CSV artifacts tell different stories:

| Artifact | Evaluator family | Rows | Dominant clusters | What it tells QPrisma |
|---|---|---:|---|---|
| `cluster-insights-agent-eval.csv` | `task_completion`, `tool_selection`, `tool_output_utilization`, `tool_call_accuracy`, `tool_call_success`, `intent_resolution` | 63 | `incorrect_tool_call` (49.2%), `misunderstood_tool_info` (25.4%), `hallucinated_response` (23.8%) | The largest problems are tool-routing and tool-use issues rather than purely stylistic answer quality. |
| `cluster-insights-quality-eval.csv` | `fluency`, `relevance`, `coherence`, `task_adherence` | 6 | `inadequate_final_answer` (33.3%), `poor_grammar_clarity` (33.3%), `action_plan_issues` (16.7%), `misunderstood_tool_info` (16.7%) | The smaller quality-oriented artifact points to answer construction issues after the agent has already chosen a path. |

### What Azure AI Foundry surfaced in these runs

| Signal | Evidence from the artifacts | Why it matters |
|---|---|---|
| Specialized video-tool gaps | `missing_specialized_video_tool` appears in 25.4% of the agent-eval rows | QPrisma should prefer domain-specific video tools when a question clearly targets video structure, chapters, or cross-video reasoning. |
| Unsupported tool fabrication | `unsupported_tool_fabrication` appears in 22.2% of the agent-eval rows | Foundry is catching cases where the agent invents or implies tools instead of grounding itself in the actual tool contract. |
| Missing summary and overview behavior | `missing_summary_and_overview_tools` appears in 12.7% of the agent-eval rows | Library- and portfolio-level queries need clear summary-tool routing rather than many disconnected per-video calls. |
| Final-answer quality regressions | The quality artifact is dominated by `inadequate_final_answer` and `poor_grammar_clarity` | Even when tool routing is acceptable, QPrisma still needs strong answer shaping, coherence, and aggregation quality. |
| Actionable AI suggestions | The cluster-analysis UI suggests directions such as <em>Use the Right Tool</em>, <em>Use Exact Tool Output</em>, <em>Enforce Evidence Grounding</em>, and <em>Use Specialized Tools</em> | The portal shortens the loop from "a run failed" to "here is the class of improvement to make next." |

## Why this matters for a video hosted agent

QPrisma is not a generic chat agent. It needs to:

- Navigate **media-scoped context** correctly
- Choose the **right video or cross-video tool** for the question
- Preserve **grounded timestamps and evidence**
- Produce a **final answer that is readable, on-topic, and complete**

Azure AI Foundry helps because it measures those concerns through a combination of evaluator scores, raw conversations, response artifacts, and clustered issue patterns. That makes the evaluation process useful not only for release confidence, but also for day-to-day debugging when a hosted-agent change shifts tool use or answer quality.
