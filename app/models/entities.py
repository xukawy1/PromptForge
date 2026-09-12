from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Source:
    title: str
    url: Optional[str] = None
    source_type: str = "manual"
    author: Optional[str] = None
    id: Optional[int] = None

@dataclass
class Prompt:
    prompt_text: str
    title: str = ""
    negative_prompt: Optional[str] = None
    prompt_type: str = "image"
    target_model: Optional[str] = None
    id: Optional[int] = None

@dataclass
class PromptComponent:
    canonical_name: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    category_id: Optional[int] = None
    description: Optional[str] = None
    confidence: float = 0.0
    usage_count: int = 0
    is_favorite: bool = False
    id: Optional[int] = None

@dataclass
class Category:
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    sort_order: int = 0
    id: Optional[int] = None

@dataclass
class Model:
    name: str
    provider: str
    model_type: str
    model_identifier: Optional[str] = None
    local_path: Optional[str] = None
    endpoint: Optional[str] = None
    id: Optional[int] = None
