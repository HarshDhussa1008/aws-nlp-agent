"""
Policy Engine for Intent Gate

Evaluates extracted intents against configured policies to determine
if operations should be allowed, denied, or require additional approval.
"""

import re
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass
from ..llm.intent_schema import ExtractedIntent, OperationType, AWSResource, ResourceFilter
from .policy_schema import (
    Policy,
    PolicyStatement,
    PolicyEffect,
    ResourcePattern,
    PolicyCondition,
    ConditionOperator
)

logger = logging.getLogger(__name__)


@dataclass
class PolicyEvaluationResult:
    """Result of policy evaluation"""
    effect: PolicyEffect  # Final effect after evaluating all policies
    matched_statements: List[PolicyStatement]  # Statements that matched
    reasoning: str  # Explanation of the decision
    requires_approval: bool = False  # If approval is needed
    
    def is_allowed(self) -> bool:
        """Check if operation is allowed"""
        return self.effect == PolicyEffect.ALLOW
    
    def is_denied(self) -> bool:
        """Check if operation is denied"""
        return self.effect == PolicyEffect.DENY


class PolicyEngine:
    """
    Evaluates intents against policies to enforce access control.
    
    Evaluation logic:
    1. Collect all matching statements
    2. Apply precedence: DENY > ALLOW > REQUIRE_APPROVAL
    3. Default: ALLOW if no matching statements
    """
    
    def __init__(self, policies: Optional[List[Policy]] = None):
        """
        Initialize policy engine with policies
        
        Args:
            policies: List of policies to enforce (empty list means allow all)
        """
        self.policies = policies or []
    
    def add_policy(self, policy: Policy):
        """Add a policy to the engine"""
        self.policies.append(policy)
        logger.info(f"Added policy: {policy.name}")
    
    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy by name"""
        original_len = len(self.policies)
        self.policies = [p for p in self.policies if p.name != policy_name]
        removed = len(self.policies) < original_len
        if removed:
            logger.info(f"Removed policy: {policy_name}")
        return removed
    
    def evaluate(self, intent: ExtractedIntent) -> PolicyEvaluationResult:
        """
        Evaluate an intent against all configured policies
        
        Args:
            intent: The extracted intent to evaluate
            
        Returns:
            PolicyEvaluationResult with final decision
        """
        logger.info(f"🔍 Evaluating intent against {len(self.policies)} policies")
        
        # If no policies configured, allow by default
        if not self.policies:
            return PolicyEvaluationResult(
                effect=PolicyEffect.ALLOW,
                matched_statements=[],
                reasoning="No policies configured - allowing by default"
            )
        
        # Collect all matching statements
        deny_statements = []
        allow_statements = []
        approval_statements = []
        
        for policy in self.policies:
            for statement in policy.statements:
                if self._statement_matches_intent(statement, intent):
                    logger.debug(f"Statement matched: {statement.sid} ({statement.effect.value})")
                    
                    if statement.effect == PolicyEffect.DENY:
                        deny_statements.append(statement)
                    elif statement.effect == PolicyEffect.ALLOW:
                        allow_statements.append(statement)
                    elif statement.effect == PolicyEffect.REQUIRE_APPROVAL:
                        approval_statements.append(statement)
        
        # Apply precedence: DENY > ALLOW > REQUIRE_APPROVAL
        
        # 1. Check for explicit denies (highest priority)
        if deny_statements:
            return PolicyEvaluationResult(
                effect=PolicyEffect.DENY,
                matched_statements=deny_statements,
                reasoning=self._build_deny_reasoning(deny_statements)
            )
        
        # 2. Check for explicit allows
        if allow_statements:
            # If there are approval requirements, honor them
            if approval_statements:
                return PolicyEvaluationResult(
                    effect=PolicyEffect.REQUIRE_APPROVAL,
                    matched_statements=approval_statements,
                    reasoning=self._build_approval_reasoning(approval_statements),
                    requires_approval=True
                )
            
            return PolicyEvaluationResult(
                effect=PolicyEffect.ALLOW,
                matched_statements=allow_statements,
                reasoning=self._build_allow_reasoning(allow_statements)
            )
        
        # 3. Check for approval requirements
        if approval_statements:
            return PolicyEvaluationResult(
                effect=PolicyEffect.REQUIRE_APPROVAL,
                matched_statements=approval_statements,
                reasoning=self._build_approval_reasoning(approval_statements),
                requires_approval=True
            )
        
        # 4. No matching statements - deny by default (secure by default)
        return PolicyEvaluationResult(
            effect=PolicyEffect.DENY,
            matched_statements=[],
            reasoning="No matching policy statements found - denying by default for security"
        )
    
    def _statement_matches_intent(
        self,
        statement: PolicyStatement,
        intent: ExtractedIntent
    ) -> bool:
        """
        Check if a policy statement matches an intent
        
        Matching criteria:
        1. Operation matches
        2. Resource matches
        3. All conditions match
        """
        # 1. Check operation match
        if intent.operation not in statement.operations:
            return False
        
        # 2. Check resource match
        if not any(self._resource_matches(pattern, intent.primary_resource) 
                   for pattern in statement.resources):
            return False
        
        # 3. Check all conditions
        if not all(self._condition_matches(condition, intent) 
                   for condition in statement.conditions):
            return False
        
        return True
    
    def _resource_matches(
        self,
        pattern: ResourcePattern,
        resource: AWSResource
    ) -> bool:
        """Check if a resource pattern matches an AWS resource"""
        
        # Check service match
        if pattern.service and pattern.service != "*":
            if pattern.service != resource.service:
                return False
        
        # Check resource type match
        if pattern.resource_type and pattern.resource_type != "*":
            if pattern.resource_type != resource.resource_type:
                return False
        
        # Check resource ID match
        if pattern.resource_ids:
            # If pattern has specific IDs, resource must match at least one
            if not resource.resource_ids:
                return False
            
            # Check if any resource ID matches any pattern
            for resource_id in resource.resource_ids:
                for pattern_id in pattern.resource_ids:
                    if self._id_matches_pattern(resource_id, pattern_id):
                        return True
            return False
        
        return True
    
    def _id_matches_pattern(self, resource_id: str, pattern: str) -> bool:
        """Check if a resource ID matches a pattern (supports wildcards)"""
        # Exact match
        if resource_id == pattern:
            return True
        
        # Wildcard pattern (convert to regex)
        if '*' in pattern or '?' in pattern:
            regex_pattern = pattern.replace('*', '.*').replace('?', '.')
            return bool(re.match(f'^{regex_pattern}$', resource_id))
        
        return False
    
    def _condition_matches(
        self,
        condition: PolicyCondition,
        intent: ExtractedIntent
    ) -> bool:
        """Check if a condition matches an intent"""
        
        # Extract the actual value from intent based on condition key
        actual_value = self._extract_condition_value(condition.key, intent)
        
        if actual_value is None:
            # If the value doesn't exist in intent, condition doesn't match
            # Exception: NOT_EQUALS and NOT_IN can match on missing values
            return condition.operator in [
                ConditionOperator.NOT_EQUALS,
                ConditionOperator.NOT_IN
            ]
        
        # Evaluate based on operator
        return self._evaluate_condition_operator(
            condition.operator,
            actual_value,
            condition.value
        )
    
    def _extract_condition_value(
        self,
        key: str,
        intent: ExtractedIntent
    ) -> Optional[any]:
        """Extract value from intent based on condition key"""
        
        # Region condition
        if key == "region":
            return intent.regions
        
        # Resource ID condition
        if key == "resource_id":
            return intent.primary_resource.resource_ids
        
        # Service condition
        if key == "service":
            return intent.primary_service
        
        # Resource type condition
        if key == "resource_type":
            return intent.primary_resource.resource_type
        
        # Tag condition (format: tag:TagName)
        if key.startswith("tag:"):
            tag_name = key[4:]  # Remove "tag:" prefix
            # Search in resource filters
            for filter_item in intent.primary_resource.filters:
                if filter_item.filter_type == "tag" and filter_item.key == tag_name:
                    return filter_item.value
            return None
        
        # Filter condition (format: filter:name, filter:state, etc.)
        if key.startswith("filter:"):
            filter_type = key[7:]  # Remove "filter:" prefix
            for filter_item in intent.primary_resource.filters:
                if filter_item.filter_type == filter_type:
                    return filter_item.value
            return None
        
        return None
    
    def _evaluate_condition_operator(
        self,
        operator: ConditionOperator,
        actual: any,
        expected: any
    ) -> bool:
        """Evaluate a condition operator"""
        
        # Handle list values (e.g., regions, resource_ids)
        if isinstance(actual, list):
            # For list comparisons, check if ANY item matches
            if operator == ConditionOperator.IN:
                return any(item in expected for item in actual)
            elif operator == ConditionOperator.NOT_IN:
                return all(item not in expected for item in actual)
            else:
                # For other operators, check if ANY item matches
                return any(
                    self._evaluate_condition_operator(operator, item, expected)
                    for item in actual
                )
        
        # String comparisons
        actual_str = str(actual).lower()
        expected_str = str(expected).lower() if isinstance(expected, str) else expected
        
        if operator == ConditionOperator.EQUALS:
            return actual_str == expected_str
        
        elif operator == ConditionOperator.NOT_EQUALS:
            return actual_str != expected_str
        
        elif operator == ConditionOperator.IN:
            return actual_str in [str(v).lower() for v in expected]
        
        elif operator == ConditionOperator.NOT_IN:
            return actual_str not in [str(v).lower() for v in expected]
        
        elif operator == ConditionOperator.STARTS_WITH:
            return actual_str.startswith(expected_str)
        
        elif operator == ConditionOperator.ENDS_WITH:
            return actual_str.endswith(expected_str)
        
        elif operator == ConditionOperator.CONTAINS:
            return expected_str in actual_str
        
        elif operator == ConditionOperator.NOT_CONTAINS:
            return expected_str not in actual_str
        
        elif operator == ConditionOperator.MATCHES:
            return bool(re.match(expected_str, actual_str))
        
        return False
    
    def _build_deny_reasoning(self, statements: List[PolicyStatement]) -> str:
        """Build reasoning message for deny decision"""
        if len(statements) == 1:
            stmt = statements[0]
            base = f"Policy '{stmt.sid}' denies this operation"
            if stmt.description:
                base += f": {stmt.description}"
            return base
        
        return f"Operation denied by {len(statements)} policy statement(s)"
    
    def _build_allow_reasoning(self, statements: List[PolicyStatement]) -> str:
        """Build reasoning message for allow decision"""
        if len(statements) == 1:
            stmt = statements[0]
            base = f"Policy '{stmt.sid}' allows this operation"
            if stmt.description:
                base += f": {stmt.description}"
            return base
        
        return f"Operation allowed by {len(statements)} policy statement(s)"
    
    def _build_approval_reasoning(self, statements: List[PolicyStatement]) -> str:
        """Build reasoning message for approval requirement"""
        if len(statements) == 1:
            stmt = statements[0]
            base = f"Policy '{stmt.sid}' requires approval for this operation"
            if stmt.description:
                base += f": {stmt.description}"
            return base
        
        return f"Operation requires approval per {len(statements)} policy statement(s)"


class PolicyEngineWithDefaults:
    """
    Policy engine with sensible default policies for AWS operations
    """
    
    def __init__(self, custom_policies: Optional[List[Policy]] = None):
        """
        Initialize with default policies + custom policies
        
        Args:
            custom_policies: Additional custom policies to add
        """
        self.engine = PolicyEngine()
        
        # Add default policies
        self._add_default_policies()
        
        # Add custom policies
        if custom_policies:
            for policy in custom_policies:
                self.engine.add_policy(policy)
    
    def _add_default_policies(self):
        """Add sensible default policies"""
        from policy_schema import PolicyBuilder, OperationType
        
        # Default: Allow all read operations
        default_read_policy = (
            PolicyBuilder("default-allow-reads")
            .with_description("Default: Allow all read operations")
            .statement("allow-all-reads")
            .allow()
            .read_operations()
            .all_resources()
            .end_statement()
            .build()
        )
        self.engine.add_policy(default_read_policy)
    
    def evaluate(self, intent: ExtractedIntent) -> PolicyEvaluationResult:
        """Evaluate intent with default + custom policies"""
        return self.engine.evaluate(intent)
    
    def add_policy(self, policy: Policy):
        """Add a custom policy"""
        self.engine.add_policy(policy)
    
    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy by name"""
        return self.engine.remove_policy(policy_name)


if __name__ == "__main__":
    # Example usage
    from policy_schema import PolicyBuilder, PolicyTemplates
    import datetime
    
    # Create a sample intent
    sample_intent = ExtractedIntent(
        query_type="simple",
        operation=OperationType.DELETE,
        confidence="high",
        primary_service="ec2",
        primary_resource=AWSResource(
            service="ec2",
            resource_type="instance",
            resource_ids=["i-production-001"],
            filters=[
                ResourceFilter(
                    filter_type="tag",
                    key="Environment",
                    value="production",
                    operator="equals"
                )
            ]
        ),
        action="terminate",
        regions=["us-east-1"],
        original_query="terminate production instance",
        normalized_query="terminate production instance",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    
    # Create policy engine with production protection
    engine = PolicyEngine()
    engine.add_policy(PolicyTemplates.deny_production_modifications())
    
    # Evaluate
    result = engine.evaluate(sample_intent)
    
    print(f"\n🔍 Policy Evaluation Result:")
    print(f"Effect: {result.effect.value}")
    print(f"Reasoning: {result.reasoning}")
    print(f"Matched Statements: {len(result.matched_statements)}")
    print(f"Is Allowed: {result.is_allowed()}")
    print(f"Is Denied: {result.is_denied()}")