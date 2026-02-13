# architecture_diagram.py — QPrisma Professional Architecture
# Generates a Well-Architected Azure solution diagram with multi-region layout,
# CI/CD pipeline, VNet segmentation, KEDA autoscaling, and Managed Identity flows.

from diagrams import Cluster, Diagram, Edge
from diagrams.azure.compute import ContainerApps
from diagrams.azure.containers import ContainerRegistries
from diagrams.azure.database import DatabaseForPostgresqlServers, CacheForRedis
from diagrams.azure.storage import StorageAccounts
from diagrams.azure.ml import CognitiveServices
from diagrams.azure.security import KeyVaults
from diagrams.azure.analytics import LogAnalyticsWorkspaces
from diagrams.azure.devops import Pipelines
from diagrams.azure.network import VirtualNetworks
from diagrams.onprem.client import User
from diagrams.onprem.vcs import Github
from diagrams.onprem.container import Docker
from diagrams.onprem.database import Neo4J

# ── Azure Brand Color Palette ──────────────────────────────────────
AZURE_BLUE     = "#0078D4"   # Primary Azure blue
AZURE_DARK     = "#003F72"   # Dark blue  (data-plane edges)
AI_GREEN       = "#107C10"   # AI / inference calls
CICD_PURPLE    = "#5C2D91"   # CI/CD pipeline
SECURITY_AMBER = "#D83B01"   # Security / identity
OBS_GRAY       = "#767676"   # Observability telemetry
INTERNAL_GRAY  = "#505050"   # Internal service-to-service
KEDA_TEAL      = "#008272"   # Autoscaling indicators

# ── Graph Layout Attributes ────────────────────────────────────────
graph_attr = {
    "splines":    "ortho",
    "fontsize":   "14",
    "bgcolor":    "white",
    "pad":        "0.8",
    "nodesep":    "1.0",
    "ranksep":    "1.2",
    "fontname":   "Segoe UI,Helvetica,Arial,sans-serif",
    "labeljust":  "l",
    "compound":   "true",
}

node_attr = {
    "fontsize": "11",
    "fontname": "Segoe UI,Helvetica,Arial,sans-serif",
}

edge_attr = {
    "fontsize": "10",
    "fontname": "Segoe UI,Helvetica,Arial,sans-serif",
}

# ── Cluster style helpers ──────────────────────────────────────────
REGION_STYLE = {
    "bgcolor":     "#F3F6FA",
    "pencolor":    AZURE_BLUE,
    "penwidth":    "2.0",
    "style":       "rounded",
    "fontsize":    "13",
    "fontcolor":   AZURE_DARK,
    "labeljust":   "l",
}

VNET_STYLE = {
    "bgcolor":     "#EAF1FB",
    "pencolor":    "#4A90D9",
    "penwidth":    "1.5",
    "style":       "dashed",
    "fontsize":    "12",
    "fontcolor":   AZURE_DARK,
}

COMPUTE_STYLE = {
    "bgcolor":     "#E8F5E9",
    "pencolor":    "#388E3C",
    "penwidth":    "1.0",
    "style":       "rounded",
    "fontsize":    "11",
    "fontcolor":   "#1B5E20",
}

DATA_STYLE = {
    "bgcolor":     "#FFF3E0",
    "pencolor":    "#E65100",
    "penwidth":    "1.0",
    "style":       "rounded",
    "fontsize":    "11",
    "fontcolor":   "#BF360C",
}

AI_STYLE = {
    "bgcolor":     "#E8F5E9",
    "pencolor":    AI_GREEN,
    "penwidth":    "1.5",
    "style":       "rounded",
    "fontsize":    "12",
    "fontcolor":   "#0B6623",
}

SECURITY_STYLE = {
    "bgcolor":     "#FFF8E1",
    "pencolor":    SECURITY_AMBER,
    "penwidth":    "1.0",
    "style":       "rounded",
    "fontsize":    "11",
    "fontcolor":   "#BF360C",
}

OBS_STYLE = {
    "bgcolor":     "#F5F5F5",
    "pencolor":    OBS_GRAY,
    "penwidth":    "1.0",
    "style":       "rounded",
    "fontsize":    "11",
    "fontcolor":   "#424242",
}

CICD_STYLE = {
    "bgcolor":     "#F3E5F5",
    "pencolor":    CICD_PURPLE,
    "penwidth":    "1.5",
    "style":       "rounded",
    "fontsize":    "12",
    "fontcolor":   "#4A148C",
}


# ====================================================================
# DIAGRAM
# ====================================================================
with Diagram(
    "QPrisma — Well-Architected Azure Solution",
    show=False,
    direction="TB",
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
    filename="docs/assets/qprisma_architecture",
):

    # ── External Actors ────────────────────────────────────────────
    user = User("Client / Browser")

    # ── CI/CD Pipeline ─────────────────────────────────────────────
    with Cluster("GitHub Actions CI/CD", graph_attr=CICD_STYLE):
        gh_actions = Github("GitHub\nActions")
        ci_pipeline = Pipelines("CI Pipeline\n(lint / test)")
        build_push = Docker("Build & Push\n(Docker images)")

        gh_actions >> Edge(color=CICD_PURPLE, style="bold") >> ci_pipeline
        ci_pipeline >> Edge(color=CICD_PURPLE, style="bold", label="main") >> build_push

    # ================================================================
    #  WEST EUROPE — Primary Compute Region
    # ================================================================
    with Cluster("Azure  ·  West Europe  (Primary)", graph_attr=REGION_STYLE):

        # ── Security & Governance ──────────────────────────────────
        with Cluster("Security & Governance", graph_attr=SECURITY_STYLE):
            kv  = KeyVaults("Key Vault\nRBAC · Managed ID")
            acr = ContainerRegistries("Container Registry\n(ACR Basic)")

        # ── Observability ──────────────────────────────────────────
        with Cluster("Observability", graph_attr=OBS_STYLE):
            logs = LogAnalyticsWorkspaces("Log Analytics\n(30-day retention)")

        # ── Virtual Network ────────────────────────────────────────
        with Cluster("Virtual Network  10.0.0.0/16", graph_attr=VNET_STYLE):

            vnet_icon = VirtualNetworks("Managed\nVNet")

            # ── Container Apps Environment (Compute) ───────────────
            with Cluster("Container Apps Environment", graph_attr=COMPUTE_STYLE):
                frontend = ContainerApps("Frontend\nNext.js 16\n0.25C / 0.5Gi\n1-2 replicas")
                backend  = ContainerApps("Backend API\nFastAPI · Python 3.11\n0.5C / 1Gi\n1-2 replicas")
                worker   = ContainerApps("Async Worker\nCelery · KEDA\n1C / 2Gi\n1-3 replicas")

                # Internal traffic
                frontend >> Edge(label="REST API", color=INTERNAL_GRAY) >> backend
                backend  >> Edge(label="Task Queue", color=INTERNAL_GRAY) >> worker

            # ── Data Persistence Layer ─────────────────────────────
            with Cluster("Data Persistence  (VNet-Integrated)", graph_attr=DATA_STYLE):
                redis   = CacheForRedis("Redis Enterprise\nBalanced B0 · TLS 1.2+\nCache / Broker / Checkpoints")
                neo4j   = Neo4J("Neo4j 5 Community\nKnowledge Graph\nAzure File Share · APOC")
                storage = StorageAccounts("Blob Storage\nStandard LRS · Hot\nMedia Assets")

    # ================================================================
    #  SWEDEN CENTRAL — AI Region
    # ================================================================
    with Cluster("Azure  ·  Sweden Central  (AI)", graph_attr={**REGION_STYLE, "bgcolor": "#EDF7ED"}):

        with Cluster("Azure AI Foundry", graph_attr=AI_STYLE):
            ai_foundry = CognitiveServices("AI Foundry\n5 Model Deployments")

    # ================================================================
    #  NORTH EUROPE — Database Region
    # ================================================================
    with Cluster("Azure  ·  North Europe  (Database)", graph_attr={**REGION_STYLE, "bgcolor": "#FFF8E1"}):

        postgres = DatabaseForPostgresqlServers("PostgreSQL Flex v16\nStandard B1ms · 32GB\n7-day backup · SSL")

    # ================================================================
    #  CONNECTIONS
    # ================================================================

    # ── User Ingress ───────────────────────────────────────────────
    user >> Edge(
        label="HTTPS / 443",
        color=AZURE_BLUE,
        penwidth="2.5",
        style="bold",
    ) >> frontend

    # ── CI/CD → ACR ────────────────────────────────────────────────
    build_push >> Edge(
        label="Push Images\n(OIDC Auth)",
        color=CICD_PURPLE,
        style="dashed",
    ) >> acr

    acr >> Edge(
        label="Image Pull",
        color=CICD_PURPLE,
        style="dotted",
    ) >> backend

    # ── Backend → Data Services ────────────────────────────────────
    backend >> Edge(color=AZURE_DARK, label="Queries\n(SSL)") >> postgres
    backend >> Edge(color=AZURE_DARK, label="Cache/Queue") >> redis
    backend >> Edge(color=AZURE_DARK, label="Bolt/TCP\n7687") >> neo4j
    backend >> Edge(color=AZURE_DARK, label="Media I/O") >> storage

    # ── Backend → AI ───────────────────────────────────────────────
    backend >> Edge(
        label="Inference\nGPT-4o · GPT-5.2",
        color=AI_GREEN,
        style="dashed",
        penwidth="1.5",
    ) >> ai_foundry

    # ── Worker → Data Services ─────────────────────────────────────
    worker >> Edge(color=AZURE_DARK, style="bold", label="KEDA Scale\nQueue Depth > 5") >> redis
    worker >> Edge(color=AZURE_DARK) >> postgres
    worker >> Edge(color=AZURE_DARK) >> neo4j
    worker >> Edge(color=AZURE_DARK) >> storage

    # ── Worker → AI ────────────────────────────────────────────────
    worker >> Edge(
        label="Batch API\nWhisper · Embeddings",
        color=AI_GREEN,
        style="dashed",
        penwidth="1.5",
    ) >> ai_foundry

    # ── Managed Identity → Key Vault ──────────────────────────────
    backend >> Edge(
        label="Managed Identity",
        color=SECURITY_AMBER,
        style="dotted",
        penwidth="1.2",
    ) >> kv

    worker >> Edge(
        color=SECURITY_AMBER,
        style="dotted",
        penwidth="1.2",
    ) >> kv

    # ── Observability (all apps → Log Analytics) ──────────────────
    [frontend, backend, worker] >> Edge(
        label="Telemetry",
        color=OBS_GRAY,
        style="dotted",
    ) >> logs
