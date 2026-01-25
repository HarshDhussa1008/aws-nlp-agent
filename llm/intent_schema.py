from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field
from enum import Enum

class OperationType(str, Enum):
    """High-level operation categories"""
    READ = "read"           # describe, list, get, show
    WRITE = "write"         # create, update, modify
    DELETE = "delete"       # delete, terminate, remove
    ANALYZE = "analyze"     # analyze, report, find issues

class ConfidenceLevel(str, Enum):
    HIGH = "high"       # >90% confident
    MEDIUM = "medium"   # 70-90% confident
    LOW = "low"         # <70% confident - needs clarification

class ResourceFilter(BaseModel):
    """Filters for resource selection"""
    filter_type: str = Field(description="tag, state, name, id, etc")
    key: str = Field(description="Filter key")
    value: str|int|List = Field(description="Filter value")
    operator: str = Field(default="equals", description="equals, contains, starts_with, etc")

class AWSResource(BaseModel):
    """Identified AWS resource"""
    service: str = Field(description="AWS service name, e.g., ec2, s3, rds")
    resource_type: Optional[str] = Field(description="instance, volume, bucket, etc")
    resource_ids: List[str] = Field(default_factory=list, description="Specific resource IDs if mentioned")
    filters: List[ResourceFilter] = Field(default_factory=list)
    
class SubIntent(BaseModel):
    """For multi-step operations, each step is a sub-intent"""
    step_number: int
    operation: OperationType
    resource: AWSResource
    description: str
    depends_on: Optional[List[int]] = Field(default=None, description="Step numbers this depends on")

class ExtractedIntent(BaseModel):
    """The complete structured intent"""
    
    # Classification
    query_type: Literal["simple", "complex", "multi_step", "ambiguous", "error"]
    operation: OperationType
    confidence: ConfidenceLevel
    
    # Core Intent
    primary_service: str = Field(description="Main AWS service")
    primary_resource: AWSResource
    action: str = Field(description="Specific action to perform")
    
    # Context
    regions: List[str] = Field(default_factory=list, description="Target regions")
    accounts: List[str] = Field(default_factory=list, description="Target accounts")
    
    # Multi-step handling
    is_multi_step: bool = Field(default=False)
    sub_intents: List[SubIntent] = Field(default_factory=list)
    
    # Output preferences
    output_format: Optional[str] = Field(default="table", description="table, json, summary")
    sorting: Optional[Dict[str, str|None]] = Field(default=None, description="Sort preferences")
    limit: Optional[int] = Field(default=None, description="Result limit")
    
    # Disambiguation
    ambiguities: List[str] = Field(default_factory=list, description="Things that need clarification")
    clarifying_questions: List[str] = Field(default_factory=list)
    
    # Raw data
    original_query: str
    normalized_query: str = Field(description="Cleaned/standardized version")
    extracted_entities: Dict = Field(default_factory=dict)
    
    # Metadata
    timestamp: str
    processing_time_ms: Optional[float] = None