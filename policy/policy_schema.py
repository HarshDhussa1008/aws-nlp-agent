"""
Policy Schema for Intent Gate Policy Engine

Provides flexible, IAM-like policies for controlling AWS operations
"""

from enum import Enum
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass, field
from ..llm.intent_schema import OperationType


class PolicyEffect(str, Enum):
    """Effect of a policy statement"""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"  # Forces confirmation even for reads


class ConditionOperator(str, Enum):
    """Operators for condition matching"""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"  # Regex match


@dataclass
class PolicyCondition:
    """Condition for policy evaluation"""
    key: str  # e.g., "region", "tag:Environment", "resource_id"
    operator: ConditionOperator
    value: Union[str, List[str]]
    
    def __post_init__(self):
        # Convert single value to list for IN/NOT_IN operators
        if self.operator in [ConditionOperator.IN, ConditionOperator.NOT_IN]:
            if not isinstance(self.value, list):
                self.value = [self.value]


@dataclass
class ResourcePattern:
    """Pattern for matching AWS resources"""
    service: Optional[str] = None  # e.g., "ec2", "*"
    resource_type: Optional[str] = None  # e.g., "instance", "*"
    resource_ids: List[str] = field(default_factory=list)  # Specific IDs or patterns
    
    def matches_all(self) -> bool:
        """Check if this pattern matches all resources"""
        return (
            (self.service == "*" or self.service is None) and
            (self.resource_type == "*" or self.resource_type is None) and
            len(self.resource_ids) == 0
        )


@dataclass
class PolicyStatement:
    """
    A single policy statement (similar to AWS IAM statement)
    
    Example:
        # Deny all delete operations on production resources
        PolicyStatement(
            effect=PolicyEffect.DENY,
            operations=[OperationType.DELETE],
            resources=[ResourcePattern(service="*")],
            conditions=[
                PolicyCondition(
                    key="tag:Environment",
                    operator=ConditionOperator.EQUALS,
                    value="production"
                )
            ]
        )
    """
    sid: str  # Statement ID
    effect: PolicyEffect
    operations: List[OperationType]  # Operations this applies to
    resources: List[ResourcePattern]  # Resources this applies to
    conditions: List[PolicyCondition] = field(default_factory=list)
    description: Optional[str] = None
    
    def applies_to_all_operations(self) -> bool:
        """Check if this statement applies to all operations"""
        return len(self.operations) == 4  # All operation types


@dataclass
class Policy:
    """
    A collection of policy statements
    
    Evaluation order:
    1. Explicit DENY statements (highest priority)
    2. Explicit ALLOW statements
    3. REQUIRE_APPROVAL statements
    4. Default behavior (if no matching statements)
    """
    name: str
    version: str = "1.0"
    statements: List[PolicyStatement] = field(default_factory=list)
    description: Optional[str] = None
    
    def add_statement(self, statement: PolicyStatement):
        """Add a statement to this policy"""
        self.statements.append(statement)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert policy to dictionary format"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "statements": [
                {
                    "sid": s.sid,
                    "effect": s.effect.value,
                    "operations": [op.value for op in s.operations],
                    "resources": [
                        {
                            "service": r.service,
                            "resource_type": r.resource_type,
                            "resource_ids": r.resource_ids
                        }
                        for r in s.resources
                    ],
                    "conditions": [
                        {
                            "key": c.key,
                            "operator": c.operator.value,
                            "value": c.value
                        }
                        for c in s.conditions
                    ],
                    "description": s.description
                }
                for s in self.statements
            ]
        }


# Policy Builder - Fluent API for easy policy construction
class PolicyBuilder:
    """Fluent API for building policies easily"""
    
    def __init__(self, name: str):
        self.policy = Policy(name=name)
        self._current_statement: Optional[PolicyStatement] = None
    
    def with_description(self, description: str) -> 'PolicyBuilder':
        """Add description to policy"""
        self.policy.description = description
        return self
    
    def statement(self, sid: str) -> 'PolicyBuilder':
        """Start a new statement"""
        self._current_statement = PolicyStatement(
            sid=sid,
            effect=PolicyEffect.ALLOW,  # Default
            operations=[],
            resources=[]
        )
        return self
    
    def effect(self, effect: PolicyEffect) -> 'PolicyBuilder':
        """Set effect for current statement"""
        if self._current_statement:
            self._current_statement.effect = effect
        return self
    
    def allow(self) -> 'PolicyBuilder':
        """Set effect to ALLOW"""
        return self.effect(PolicyEffect.ALLOW)
    
    def deny(self) -> 'PolicyBuilder':
        """Set effect to DENY"""
        return self.effect(PolicyEffect.DENY)
    
    def require_approval(self) -> 'PolicyBuilder':
        """Set effect to REQUIRE_APPROVAL"""
        return self.effect(PolicyEffect.REQUIRE_APPROVAL)
    
    def operations(self, *ops: OperationType) -> 'PolicyBuilder':
        """Add operations to current statement"""
        if self._current_statement:
            self._current_statement.operations.extend(ops)
        return self
    
    def all_operations(self) -> 'PolicyBuilder':
        """Apply to all operations"""
        return self.operations(
            OperationType.READ,
            OperationType.WRITE,
            OperationType.DELETE,
            OperationType.ANALYZE
        )
    
    def read_operations(self) -> 'PolicyBuilder':
        """Apply to read operations"""
        return self.operations(OperationType.READ)
    
    def write_operations(self) -> 'PolicyBuilder':
        """Apply to write operations"""
        return self.operations(OperationType.WRITE)
    
    def delete_operations(self) -> 'PolicyBuilder':
        """Apply to delete operations"""
        return self.operations(OperationType.DELETE)
    
    def resource(
        self,
        service: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_ids: Optional[List[str]] = None
    ) -> 'PolicyBuilder':
        """Add a resource pattern to current statement"""
        if self._current_statement:
            self._current_statement.resources.append(
                ResourcePattern(
                    service=service,
                    resource_type=resource_type,
                    resource_ids=resource_ids or []
                )
            )
        return self
    
    def all_resources(self) -> 'PolicyBuilder':
        """Apply to all resources"""
        return self.resource(service="*")
    
    def service(self, service: str) -> 'PolicyBuilder':
        """Apply to all resources in a service"""
        return self.resource(service=service, resource_type="*")
    
    def condition(
        self,
        key: str,
        operator: ConditionOperator,
        value: Union[str, List[str]]
    ) -> 'PolicyBuilder':
        """Add a condition to current statement"""
        if self._current_statement:
            self._current_statement.conditions.append(
                PolicyCondition(key=key, operator=operator, value=value)
            )
        return self
    
    def when_tag(self, tag_key: str, operator: ConditionOperator, value: Union[str, List[str]]) -> 'PolicyBuilder':
        """Add tag-based condition"""
        return self.condition(f"tag:{tag_key}", operator, value)
    
    def when_region(self, operator: ConditionOperator, value: Union[str, List[str]]) -> 'PolicyBuilder':
        """Add region-based condition"""
        return self.condition("region", operator, value)
    
    def when_resource_id(self, operator: ConditionOperator, value: Union[str, List[str]]) -> 'PolicyBuilder':
        """Add resource ID condition"""
        return self.condition("resource_id", operator, value)
    
    def description(self, desc: str) -> 'PolicyBuilder':
        """Add description to current statement"""
        if self._current_statement:
            self._current_statement.description = desc
        return self
    
    def end_statement(self) -> 'PolicyBuilder':
        """Finish current statement and add to policy"""
        if self._current_statement:
            self.policy.add_statement(self._current_statement)
            self._current_statement = None
        return self
    
    def build(self) -> Policy:
        """Build and return the policy"""
        # Add any pending statement
        if self._current_statement:
            self.end_statement()
        return self.policy


# Common Policy Templates
class PolicyTemplates:
    """Pre-built policy templates for common scenarios"""
    
    @staticmethod
    def read_only() -> Policy:
        """Allow only read operations"""
        return (
            PolicyBuilder("read-only-policy")
            .with_description("Allow only read operations, deny all modifications")
            .statement("allow-reads")
            .allow()
            .read_operations()
            .all_resources()
            .end_statement()
            .statement("deny-writes")
            .deny()
            .write_operations()
            .all_resources()
            .end_statement()
            .statement("deny-deletes")
            .deny()
            .delete_operations()
            .all_resources()
            .end_statement()
            .build()
        )
    
    @staticmethod
    def deny_production_modifications() -> Policy:
        """Deny all modifications to production resources"""
        return (
            PolicyBuilder("deny-production-mods")
            .with_description("Prevent modifications to production resources")
            .statement("deny-prod-write")
            .deny()
            .operations(OperationType.WRITE, OperationType.DELETE)
            .all_resources()
            .when_tag("Environment", ConditionOperator.IN, ["production", "prod", "prd"])
            .end_statement()
            .build()
        )
    
    @staticmethod
    def region_restrictions(allowed_regions: List[str]) -> Policy:
        """Restrict operations to specific regions"""
        return (
            PolicyBuilder("region-restrictions")
            .with_description(f"Allow operations only in: {', '.join(allowed_regions)}")
            .statement("deny-other-regions")
            .deny()
            .all_operations()
            .all_resources()
            .when_region(ConditionOperator.NOT_IN, allowed_regions)
            .end_statement()
            .build()
        )
    
    @staticmethod
    def service_restrictions(allowed_services: List[str]) -> Policy:
        """Restrict to specific AWS services"""
        policy = PolicyBuilder("service-restrictions").with_description(
            f"Allow access only to: {', '.join(allowed_services)}"
        )
        
        # Add allow statement for each service
        for service in allowed_services:
            policy.statement(f"allow-{service}").allow().all_operations().service(service).end_statement()
        
        return policy.build()
    
    @staticmethod
    def require_approval_for_critical() -> Policy:
        """Require approval for all operations on critical resources"""
        return (
            PolicyBuilder("critical-resource-approval")
            .with_description("Require approval for critical resources")
            .statement("approval-for-critical")
            .require_approval()
            .all_operations()
            .all_resources()
            .when_tag("Critical", ConditionOperator.EQUALS, "true")
            .end_statement()
            .build()
        )
    
    @staticmethod
    def specific_resource_deny(service: str, resource_ids: List[str]) -> Policy:
        """Deny operations on specific resource IDs"""
        return (
            PolicyBuilder("specific-resource-deny")
            .with_description(f"Deny operations on specific {service} resources")
            .statement("deny-specific-resources")
            .deny()
            .all_operations()
            .resource(service=service, resource_ids=resource_ids)
            .end_statement()
            .build()
        )