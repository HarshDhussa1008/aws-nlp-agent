import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
from ..llm.intent_schema import (
    ExtractedIntent,
    OperationType,
    ConfidenceLevel,
    AWSResource
)
import datetime
from .policy_engine import PolicyEngine, PolicyEvaluationResult
from .policy_schema import Policy, PolicyEffect, PolicyBuilder, OperationType, ConditionOperator, PolicyTemplates


logger = logging.getLogger(__name__)


class GateDecision(str, Enum):
    """Decision made by the intent gate"""
    PROCEED = "proceed"  # Intent is clear and safe, proceed to execution
    CLARIFY = "clarify"  # Need more information from user
    REJECT = "reject"    # Cannot or should not execute
    CONFIRM = "confirm"  # Need explicit confirmation before proceeding


@dataclass
class GateResult:
    """Result from the intent gate evaluation"""
    decision: GateDecision
    intent: ExtractedIntent
    reasoning: str
    clarifying_questions: List[str] = None
    warnings: List[str] = None
    required_confirmations: List[str] = None
    
    def __post_init__(self):
        if self.clarifying_questions is None:
            self.clarifying_questions = []
        if self.warnings is None:
            self.warnings = []
        if self.required_confirmations is None:
            self.required_confirmations = []


class IntentGate:
    """
    Validates extracted intents and decides whether to proceed with execution.
    
    The gate applies multiple validation layers:
    1. Confidence checks
    2. Completeness validation
    3. Safety checks
    4. Resource constraints
    5. Ambiguity resolution
    """
    
    def __init__(self, config: Optional[Dict] = None, policies: Optional[List[Policy]] = None, enable_policies: bool = True):
        """
        Initialize the intent gate with optional configuration.
        
        Args:
            config: Gate configuration (same as IntentGate)
            policies: List of policies to enforce
            enable_policies: Whether to enable policy enforcement
        """
        self.config = config or {}
        
        # Confidence thresholds
        self.min_confidence_proceed = self.config.get('min_confidence_proceed', ConfidenceLevel.MEDIUM)
        self.min_confidence_write = self.config.get('min_confidence_write', ConfidenceLevel.HIGH)
        
        # Safety settings
        self.require_confirmation_for_delete = self.config.get('require_confirmation_delete', True)
        self.require_confirmation_for_write = self.config.get('require_confirmation_write', False)
        self.max_resource_limit = self.config.get('max_resource_limit', 100)
        
        # Protected resources (require explicit confirmation)
        self.protected_patterns = self.config.get('protected_patterns', [
            'prod', 'production', 'master', 'main'
        ])
        
        # Dangerous operations that need extra validation
        self.high_risk_operations = {
            OperationType.DELETE: ['terminate', 'delete', 'remove', 'destroy'],
            OperationType.WRITE: ['stop', 'restart', 'reboot', 'modify']
        }
        
        default_policy = [
            PolicyTemplates.deny_production_modifications(),
            PolicyBuilder("default-policies")
            .statement("allow-reads")
            .allow()
            .read_operations()
            .all_resources()
            .end_statement()
            .statement("approval-for-writes")
            .require_approval()
            .write_operations()
            .all_resources()
            .end_statement()
            .statement('deny-delete')
            .deny()
            .delete_operations()
            .all_resources()
            .end_statement()
            .build()
        ]
        
        self.enable_policies = enable_policies
        self.policy_engine = PolicyEngine(policies if policies is not None else default_policy)
        
    def add_policy(self, policy: Policy):
        """Add a policy to the engine"""
        self.policy_engine.add_policy(policy)
    
    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy by name"""
        return self.policy_engine.remove_policy(policy_name)
    
    def evaluate(self, intent: ExtractedIntent) -> GateResult:
        """
        Main evaluation method that runs all gate checks.
        
        Args:
            intent: The extracted intent to evaluate
            
        Returns:
            GateResult with decision and supporting information
        """
        logger.info(f"🚦 Evaluating intent: {intent.operation.value} on {intent.primary_service}")
        
        # Run validation checks in order
        basic_checks = [
            self._check_error_intent,
            self._check_confidence,
            self._check_completeness,
            self._check_ambiguities,
        ]
        
        for check in basic_checks:
            result = check(intent)
            if result:  # If check returns a result, it's blocking
                logger.info(f"Gate decision: {result.decision.value} - {result.reasoning}")
                return result
        
        # Step 2: Evaluate against policies (if enabled)
        if self.enable_policies:
            policy_result = self.policy_engine.evaluate(intent)
            logger.info(f"🔐 Policy evaluation: {policy_result.effect.value}")
            
            # Check if policy blocks execution
            if policy_result.effect == PolicyEffect.DENY:
                logger.info(f"Gate decision: reject - {policy_result.reasoning}")
                return GateResult(
                    decision=GateDecision.REJECT,
                    intent=intent,
                    reasoning=f"Policy denied: {policy_result.reasoning}"
                )
        else:
            policy_result = None
        
        # Step 3: Run safety checks (may add confirmations)
        safety_result = self._check_safety(intent)
        
        # Step 4: Run resource constraint checks
        constraint_result = self._check_resource_constraints(intent)
        
        if constraint_result:
            logger.info(f"Gate decision: {constraint_result.decision.value} - {constraint_result.reasoning}")
            return constraint_result
        
        # Combine gate result with policy result
        return self._combine_results(safety_result, policy_result, intent)
            
    def _check_error_intent(self, intent: ExtractedIntent) -> Optional[GateResult]:
        """Check if this is an error intent from failed extraction"""
        if intent.query_type == "error":
            return GateResult(
                decision=GateDecision.REJECT,
                intent=intent,
                reasoning="Intent extraction failed",
                clarifying_questions=intent.clarifying_questions or [
                    "I couldn't understand your query. Could you rephrase it?",
                    "Try something like: 'list my EC2 instances' or 'show S3 buckets'"
                ]
            )
        return None
    
    def _check_confidence(self, intent: ExtractedIntent) -> Optional[GateResult]:
        """Check if confidence level meets requirements"""
        
        # Different operations have different confidence requirements
        if intent.operation == OperationType.DELETE:
            required_confidence = ConfidenceLevel.HIGH
        elif intent.operation == OperationType.WRITE:
            required_confidence = self.min_confidence_write
        else:
            required_confidence = self.min_confidence_proceed
        
        if self._confidence_level_value(intent.confidence) < self._confidence_level_value(required_confidence):
            return GateResult(
                decision=GateDecision.CLARIFY,
                intent=intent,
                reasoning=f"Confidence level {intent.confidence.value} is below required {required_confidence.value} for {intent.operation.value} operations",
                clarifying_questions=[
                    f"I'm not completely sure I understood correctly. You want to {intent.action} {intent.primary_service} resources?",
                    "Could you provide more specific details about what you want to do?"
                ]
            )
        
        return None
    
    def _check_completeness(self, intent: ExtractedIntent) -> Optional[GateResult]:
        """Check if intent has all required information"""
        questions = []
        
        # Check for unknown service
        if intent.primary_service == "unknown":
            questions.append("Which AWS service would you like to work with? (e.g., EC2, S3, RDS)")
        
        # Check for missing action on write/delete operations
        if intent.operation in [OperationType.WRITE, OperationType.DELETE]:
            if not intent.action or intent.action == "":
                questions.append(f"What specific action would you like to perform? (e.g., stop, terminate, update)")
        
        # Check for missing resource type when filters are applied
        if intent.primary_resource.filters and not intent.primary_resource.resource_type:
            questions.append(f"What type of {intent.primary_service} resource are you looking for?")
        
        if questions:
            return GateResult(
                decision=GateDecision.CLARIFY,
                intent=intent,
                reasoning="Intent is missing critical information",
                clarifying_questions=questions
            )
        
        return None
    
    def _check_ambiguities(self, intent: ExtractedIntent) -> Optional[GateResult]:
        """Check for ambiguities that need clarification"""
        if intent.ambiguities:
            questions = []
            
            # Convert ambiguities into questions
            for ambiguity in intent.ambiguities:
                if "region" in ambiguity.lower():
                    questions.append("Which AWS region should I use? (e.g., us-east-1, eu-west-1)")
                elif "resource" in ambiguity.lower():
                    questions.append(f"Could you specify which {intent.primary_service} resource?")
                else:
                    questions.append(f"Could you clarify: {ambiguity}")
            
            # For high-risk operations, ambiguities are blocking
            if intent.operation in [OperationType.DELETE, OperationType.WRITE]:
                return GateResult(
                    decision=GateDecision.CLARIFY,
                    intent=intent,
                    reasoning=f"Ambiguities detected for {intent.operation.value} operation require clarification",
                    clarifying_questions=questions
                )
            
            # For read operations, warn but don't block
            # Continue to other checks
        
        return None
    
    def _check_safety(self, intent: ExtractedIntent) -> Optional[GateResult]:
        """Check for safety concerns and high-risk operations"""
        warnings = []
        confirmations = []
        
        # Check for delete operations
        if intent.operation == OperationType.DELETE:
            if self.require_confirmation_for_delete:
                confirmations.append(
                    f"⚠️  You're about to DELETE {intent.primary_service} resources. "
                    "This action cannot be undone. Type 'confirm' to proceed."
                )
        
        # Check for write operations on protected resources
        if intent.operation in [OperationType.WRITE, OperationType.DELETE]:
            protected = self._check_protected_resources(intent)
            if protected:
                confirmations.append(
                    f"🔒 This operation targets protected resources (matching: {', '.join(protected)}). "
                    "Please confirm this is intentional."
                )
        
        # Check for broad operations without filters
        if intent.operation in [OperationType.WRITE, OperationType.DELETE]:
            if not intent.primary_resource.resource_ids and not intent.primary_resource.filters:
                confirmations.append(
                    f"⚠️  This will affect ALL {intent.primary_service} resources. "
                    "Are you sure you want to proceed without filters?"
                )
        
        # Check for high-risk actions
        if intent.action:
            action_lower = intent.action.lower()
            high_risk_actions = self.high_risk_operations.get(intent.operation, [])
            if action_lower in high_risk_actions:
                warnings.append(
                    f"High-risk action detected: {intent.action}"
                )
        
        # Require confirmation if needed
        if confirmations:
            return GateResult(
                decision=GateDecision.CONFIRM,
                intent=intent,
                reasoning="Operation requires explicit confirmation due to safety concerns",
                required_confirmations=confirmations,
                warnings=warnings
            )
        
        return None
    
    def _check_resource_constraints(self, intent: ExtractedIntent) -> Optional[GateResult]:
        """Check if operation exceeds resource constraints"""
        
        # Check limit constraints
        if intent.limit and intent.limit > self.max_resource_limit:
            if intent.operation in [OperationType.WRITE, OperationType.DELETE]:
                return GateResult(
                    decision=GateDecision.REJECT,
                    intent=intent,
                    reasoning=f"Requested limit ({intent.limit}) exceeds maximum allowed ({self.max_resource_limit}) for {intent.operation.value} operations",
                    clarifying_questions=[
                        f"The maximum allowed limit for {intent.operation.value} operations is {self.max_resource_limit}.",
                        "Would you like to proceed with a smaller batch or add more specific filters?"
                    ]
                )
        
        # Check for region constraints
        if not intent.regions and intent.operation in [OperationType.WRITE, OperationType.DELETE]:
            return GateResult(
                decision=GateDecision.CLARIFY,
                intent=intent,
                reasoning="Region must be specified for write/delete operations",
                clarifying_questions=[
                    "Which AWS region should I target for this operation?",
                    "For safety, write and delete operations require explicit region specification."
                ]
            )
        
        return None
    
    def _check_protected_resources(self, intent: ExtractedIntent) -> List[str]:
        """Check if intent targets protected resources"""
        protected = []
        
        # Check resource IDs
        for resource_id in intent.primary_resource.resource_ids:
            for pattern in self.protected_patterns:
                if pattern.lower() in resource_id.lower():
                    protected.append(pattern)
        
        # Check filters
        for filter_item in intent.primary_resource.filters:
            if filter_item.filter_type in ['name', 'tag']:
                for pattern in self.protected_patterns:
                    if pattern.lower() in str(filter_item.value).lower():
                        protected.append(pattern)
        
        return list(set(protected))  # Remove duplicates
    
    def _confidence_level_value(self, level: ConfidenceLevel) -> int:
        """Convert confidence level to numeric value for comparison"""
        mapping = {
            ConfidenceLevel.LOW: 1,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.HIGH: 3
        }
        return mapping.get(level, 0)
    
    def _combine_results(
        self,
        gate_result: GateResult,
        policy_result: PolicyEvaluationResult,
        intent: ExtractedIntent
    ) -> GateResult:
        """
        Combine original gate result with policy evaluation result
        
        Logic:
        - Policy DENY → REJECT (overrides everything)
        - Policy REQUIRE_APPROVAL + Gate PROCEED → CONFIRM
        - Policy REQUIRE_APPROVAL + Gate CONFIRM → CONFIRM (merge confirmations)
        - Policy ALLOW + Gate PROCEED → PROCEED
        - Policy ALLOW + Gate CONFIRM → CONFIRM
        """
        
        confirmations = []
        warnings = []
        
        if gate_result:  # ✅ Check if not None first
            confirmations.extend(gate_result.required_confirmations or [])
            warnings.extend(gate_result.warnings or [])
        
        # Policy explicitly denies
        if policy_result and policy_result.effect == PolicyEffect.DENY:
            return GateResult(
                decision=GateDecision.REJECT,
                intent=intent,
                reasoning=f"Policy denied: {policy_result.reasoning}",
                warnings=warnings
            )
        
        # Policy requires approval
        if policy_result and policy_result.effect == PolicyEffect.REQUIRE_APPROVAL:
            # Merge with existing confirmations if gate already required confirm
            confirmations.append(f"🔐 Policy requires approval: {policy_result.reasoning}")
        
        # Determine final decision
        if confirmations:
            return GateResult(
                decision=GateDecision.CONFIRM,
                intent=intent,
                reasoning="Operation requires explicit confirmation",
                required_confirmations=confirmations,
                warnings=warnings
            )
        
        # Policy allows - return original gate result
        return GateResult(
            decision=GateDecision.PROCEED,
            intent=intent,
            reasoning="All validation checks passed. Intent is clear and safe to execute.",
            warnings=warnings
        )
            
    def process_confirmation(self, gate_result: GateResult, user_response: str) -> GateResult:
        """
        Process user's confirmation response.
        
        Args:
            gate_result: The original gate result requiring confirmation
            user_response: User's response to confirmation request
            
        Returns:
            Updated GateResult with new decision
        """
        if gate_result.decision != GateDecision.CONFIRM:
            return gate_result
        
        # Check for explicit confirmation
        confirmation_phrases = ['confirm', 'yes', 'proceed', 'continue', 'go ahead']
        rejection_phrases = ['no', 'cancel', 'abort', 'stop', 'nevermind']
        
        user_lower = user_response.lower().strip()
        
        if any(phrase in user_lower for phrase in confirmation_phrases):
            logger.info("User confirmed high-risk operation")
            return GateResult(
                decision=GateDecision.PROCEED,
                intent=gate_result.intent,
                reasoning="User explicitly confirmed the operation",
                warnings=gate_result.warnings
            )
        elif any(phrase in user_lower for phrase in rejection_phrases):
            logger.info("User rejected high-risk operation")
            return GateResult(
                decision=GateDecision.REJECT,
                intent=gate_result.intent,
                reasoning="User declined to confirm the operation"
            )
        else:
            # Ambiguous response, ask again
            return GateResult(
                decision=GateDecision.CONFIRM,
                intent=gate_result.intent,
                reasoning="Confirmation response not clear",
                required_confirmations=[
                    "Please respond with 'confirm' to proceed or 'cancel' to abort."
                ],
                warnings=gate_result.warnings
            )


class IntentGateWithHistory:
    """
    Intent gate with conversation history tracking for multi-turn clarifications.
    """
    
    def __init__(self, config: Optional[Dict] = None, policies: Optional[List[Policy]] = None, enable_policies: bool = True):
        self.gate = IntentGate(config)
        self.pending_clarifications: Dict[str, GateResult] = {}
        
    def add_policy(self, policy: Policy):
        """Add a policy to the engine"""
        self.gate.add_policy(policy)
    
    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy by name"""
        return self.gate.remove_policy(policy_name)
    
    def evaluate(self, intent: ExtractedIntent, conversation_id: Optional[str] = None) -> GateResult:
        """
        Evaluate intent with conversation tracking.
        
        Args:
            intent: The extracted intent
            conversation_id: Optional conversation ID for tracking multi-turn interactions
            
        Returns:
            GateResult with decision
        """
        result = self.gate.evaluate(intent)
        
        # Store pending clarifications if needed
        if conversation_id and result.decision in [GateDecision.CLARIFY, GateDecision.CONFIRM]:
            self.pending_clarifications[conversation_id] = result
        
        return result
    
    def process_followup(
        self, 
        conversation_id: str, 
        user_response: str, 
        new_intent: Optional[ExtractedIntent] = None
    ) -> Optional[GateResult]:
        """
        Process a follow-up response to a clarification request.
        
        Args:
            conversation_id: The conversation ID
            user_response: User's follow-up response
            new_intent: Optionally, a newly extracted intent from the follow-up
            
        Returns:
            Updated GateResult or None if no pending clarification
        """
        if conversation_id not in self.pending_clarifications:
            return None
        
        previous_result = self.pending_clarifications[conversation_id]
        
        # If we have a confirmation pending
        if previous_result.decision == GateDecision.CONFIRM:
            result = self.gate.process_confirmation(previous_result, user_response)
            
            if result.decision != GateDecision.CONFIRM:
                # Confirmation resolved, remove from pending
                del self.pending_clarifications[conversation_id]
            else:
                # Still need confirmation, update pending
                self.pending_clarifications[conversation_id] = result
            
            return result
        
        # If we have a clarification pending and received a new intent
        if previous_result.decision == GateDecision.CLARIFY and new_intent:
            # Re-evaluate with the updated intent
            result = self.evaluate(new_intent, conversation_id)
            return result
        
        return None
    
    def clear_pending(self, conversation_id: str):
        """Clear pending clarifications for a conversation"""
        if conversation_id in self.pending_clarifications:
            del self.pending_clarifications[conversation_id]


if __name__ == "__main__":
    
    # Create a test intent
    test_intent = ExtractedIntent(
        query_type="simple",
        operation=OperationType.DELETE,
        confidence=ConfidenceLevel.HIGH,
        primary_service="ec2",
        primary_resource=AWSResource(
            service="ec2",
            resource_type="instance",
            resource_ids=["i-1234567890abcdef0"]
        ),
        action="terminate",
        regions=["us-east-1"],
        original_query="terminate instance i-1234567890abcdef0",
        normalized_query="terminate instance i-1234567890abcdef0",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    
    # Test the gate
    gate = IntentGate(
        enable_policies=True
    )
    result = gate.evaluate(test_intent)
    
    print(f"\n🚦 Gate Decision: {result.decision.value}")
    print(f"Reasoning: {result.reasoning}")
    if result.required_confirmations:
        print("\nConfirmations needed:")
        for conf in result.required_confirmations:
            print(f"  - {conf}")
    if result.warnings:
        print("\nWarnings:")
        for warn in result.warnings:
            print(f"  - {warn}")