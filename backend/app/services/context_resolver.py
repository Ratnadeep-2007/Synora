from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import re
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_state import ProjectState
from app.schemas.context import ContextCandidate, ContextResolutionResult
from app.services.llm import LLMClient, get_default_llm_client

logger = logging.getLogger(__name__)

UNKNOWN_CONTEXT_ID = "system_unknown_context"
UNKNOWN_CONTEXT_NAME = "Unknown Context"
UNKNOWN_CONTEXT_DESCRIPTION = (
    "System-managed quarantine workspace for source information that cannot yet "
    "be assigned to an existing project with sufficient confidence."