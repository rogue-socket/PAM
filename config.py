import os
from pathlib import Path

# Paths
DB_PATH = Path(os.getenv("PAM_DB_PATH", "pam.db"))
LOG_PATH = Path(os.getenv("PAM_LOG_PATH", "pam_log.jsonl"))

# Retrieval
TOP_K = int(os.getenv("PAM_TOP_K", "10"))
FTS_CANDIDATE_LIMIT = int(os.getenv("PAM_FTS_LIMIT", "50"))
VEC_CANDIDATE_LIMIT = int(os.getenv("PAM_VEC_LIMIT", "50"))
# BGE cosines for unrelated text typically land 0.3-0.5; for related, 0.5-0.8.
# 0.5 is an arbitrary placeholder to filter weak matches; sweep in A.2.
VEC_SIMILARITY_FLOOR = float(os.getenv("PAM_VEC_FLOOR", "0.5"))
ENTITY_BOOST_SCORE = 0.2
EDGE_WEIGHT_EXPANSION_THRESHOLD = 0.3
# Bonus added to a node's effective rank-key when it's a relationship-mode
# anchor (endpoint of a ranked edge or support path). Small enough that a
# clearly higher-scoring non-anchor node still beats it; large enough that
# anchors with moderate scores stay surfaced for relationship-mode queries.
RELATIONSHIP_PRIORITY_BONUS = float(os.getenv("PAM_RELATIONSHIP_PRIORITY_BONUS", "0.1"))

# Ranking weights. Pre-hybrid was {text=0.45, recency=0.30, importance=0.25};
# Phase A.1 splits text→{text=0.30, vec=0.25} (arbitrary placeholders, sweep
# in A.2). Sum of the four weights here is 1.10; entity_bonus is additive.
WEIGHT_TEXT_RELEVANCE = float(os.getenv("PAM_W_TEXT", "0.30"))
WEIGHT_VEC_SIMILARITY = float(os.getenv("PAM_W_VEC", "0.25"))
WEIGHT_RECENCY = float(os.getenv("PAM_W_RECENCY", "0.30"))
WEIGHT_IMPORTANCE = float(os.getenv("PAM_W_IMPORTANCE", "0.25"))

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

# Per-call-site model defaults. Ingestion uses haiku (cheap, summary/entity
# extraction); query parsing uses sonnet (smarter intent parse); chat answer
# uses sonnet via the Copilot CLI, which expects the dot-form ID.
LLM_INGESTION_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
LLM_QUERY_PARSER_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
LLM_CLAUDE_CODE_MODEL = os.getenv("CLAUDE_CODE_MODEL", "claude-haiku-4-5")
CHAT_ANSWER_MODEL = os.getenv("PAM_CHAT_ANSWER_MODEL", "claude-sonnet-4.5")