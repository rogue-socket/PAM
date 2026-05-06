import os
from pathlib import Path

# Paths
DB_PATH = Path(os.getenv("PAM_DB_PATH", "pam.db"))
LOG_PATH = Path(os.getenv("PAM_LOG_PATH", "pam_log.jsonl"))

# Retrieval
TOP_K = 10
FTS_CANDIDATE_LIMIT = 50
ENTITY_BOOST_SCORE = 0.2
EDGE_WEIGHT_EXPANSION_THRESHOLD = 0.3

# Ranking weights (must sum to 1.0 before entity_boost)
WEIGHT_TEXT_RELEVANCE = 0.45
WEIGHT_RECENCY = 0.30
WEIGHT_IMPORTANCE = 0.25

# Lifecycle
DECAY_LAMBDA = 0.005
ARCHIVE_THRESHOLD = 0.05

# Entity extraction
MAX_ENTITIES_PER_INGESTION = 5
ENTITY_CATEGORIES = ["person", "tool", "concept", "project", "place", "organization"]
ENTITY_FUZZY_MATCH_THRESHOLD = 85
ENTITY_FUZZY_MATCH_THRESHOLD_FTS = 70

# Session
SESSION_STALENESS_HOURS = 24

# Feedback
UPVOTE_DELTA = 0.1
DOWNVOTE_DELTA = -0.1
EDGE_UPVOTE_DELTA = 0.05
SUPERSEDE_IMPORTANCE_FACTOR = 0.5
IMPORTANCE_MAX = 1.0
IMPORTANCE_MIN = 0.0
IMPORTANCE_DEFAULT = 0.5

# LLM
# Provider is env-driven so the same install can run with an Anthropic key,
# an OpenAI key, or shell out to the Claude Code CLI when no API key is set.
# Valid values: "anthropic", "openai", "claude_code".
LLM_PROVIDER = os.getenv("PAM_LLM_PROVIDER", "anthropic")
LLM_TIMEOUT_SECONDS = int(os.getenv("PAM_LLM_TIMEOUT_SECONDS", "30"))