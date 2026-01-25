"""
Comprehensive Test Cases for Intent Gate

Tests all validation layers:
1. Basic validation (confidence, completeness, ambiguities)
2. Policy evaluation (ALLOW, DENY, REQUIRE_APPROVAL)
3. Safety checks (protected resources, confirmations)
4. Resource constraints
5. Multi-turn conversations
"""

import datetime
from ..policy.intent_gate import IntentGate, IntentGateWithHistory, GateDecision
from ..llm.intent_schema import (ExtractedIntent, OperationType, ConfidenceLevel, AWSResource, ResourceFilter)
from ..policy.policy_schema import PolicyBuilder, ConditionOperator


def create_intent(
    operation: OperationType,
    service: str = "ec2",
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    resource_type: str = "instance",
    resource_ids: list = None,
    filters: list = None,
    regions: list = None,
    action: str = "test",
    ambiguities: list = None,
    query_type: str = "simple"
):
    """Helper to create test intents"""
    return ExtractedIntent(
        query_type=query_type,
        operation=operation,
        confidence=confidence,
        primary_service=service,
        primary_resource=AWSResource(
            service=service,
            resource_type=resource_type,
            resource_ids=resource_ids or [],
            filters=filters or []
        ),
        action=action,
        regions=regions if regions is not None else ["us-east-1"],
        ambiguities=ambiguities or [],
        original_query="test query",
        normalized_query="test query",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


def print_result(test_name: str, result, expected_decision: GateDecision = None):
    """Print test result"""
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"{'='*80}")
    print(f"🚦 Decision: {result.decision.value.upper()}")
    print(f"📋 Reasoning: {result.reasoning}")
    
    if result.clarifying_questions:
        print("\n❓ Clarifying Questions:")
        for q in result.clarifying_questions:
            print(f"   • {q}")
    
    if result.required_confirmations:
        print("\n⚠️  Required Confirmations:")
        for c in result.required_confirmations:
            print(f"   • {c}")
    
    if result.warnings:
        print("\n⚡ Warnings:")
        for w in result.warnings:
            print(f"   • {w}")
    
    if expected_decision:
        status = "✅ PASS" if result.decision == expected_decision else "❌ FAIL"
        print(f"\n{status} - Expected: {expected_decision.value}, Got: {result.decision.value}")
    
    return result


# ============================================================================
# TEST SUITE 1: BASIC READ OPERATIONS
# ============================================================================

def test_suite_1_basic_reads():
    """Test basic READ operations (should mostly PROCEED)"""
    print("\n" + "="*80)
    print("TEST SUITE 1: BASIC READ OPERATIONS")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Test 1.1: Simple read with high confidence
    print("\n--- Test 1.1: Simple READ (high confidence) ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="list"
    )
    result = print_result("Simple READ - EC2 instances", gate.evaluate(intent), GateDecision.PROCEED)
    
    # Test 1.2: Read with medium confidence
    print("\n--- Test 1.2: READ with medium confidence ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="s3",
        confidence=ConfidenceLevel.MEDIUM,
        action="list"
    )
    result = print_result("Medium confidence READ - S3 buckets", gate.evaluate(intent), GateDecision.PROCEED)
    
    # Test 1.3: Read with low confidence (should CLARIFY)
    print("\n--- Test 1.3: READ with low confidence ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="rds",
        confidence=ConfidenceLevel.LOW,
        action="describe"
    )
    result = print_result("Low confidence READ - RDS", gate.evaluate(intent), GateDecision.CLARIFY)
    
    # Test 1.4: Read different services
    print("\n--- Test 1.4: READ various services ---")
    services = ["s3", "lambda", "dynamodb", "cloudwatch"]
    for service in services:
        intent = create_intent(
            operation=OperationType.READ,
            service=service,
            confidence=ConfidenceLevel.HIGH,
            action="list"
        )
        result = gate.evaluate(intent)
        print(f"   {service}: {result.decision.value}")


# ============================================================================
# TEST SUITE 2: WRITE OPERATIONS
# ============================================================================

def test_suite_2_write_operations():
    """Test WRITE operations (should require approval/confirmation)"""
    print("\n" + "="*80)
    print("TEST SUITE 2: WRITE OPERATIONS")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Test 2.1: Simple write (should require approval)
    print("\n--- Test 2.1: Simple WRITE ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        resource_ids=["i-12345"]
    )
    result = print_result("WRITE - Stop EC2 instance", gate.evaluate(intent), GateDecision.CONFIRM)
    
    # Test 2.2: Write with low confidence (should CLARIFY)
    print("\n--- Test 2.2: WRITE with low confidence ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.LOW,
        action="restart"
    )
    result = print_result("Low confidence WRITE", gate.evaluate(intent), GateDecision.CLARIFY)
    
    # Test 2.3: Write without region (should CLARIFY)
    print("\n--- Test 2.3: WRITE without region ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        regions=[]
    )
    result = print_result("WRITE without region", gate.evaluate(intent), GateDecision.CLARIFY)
    
    # Test 2.4: Write without action (should CLARIFY)
    print("\n--- Test 2.4: WRITE without action ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action=""
    )
    result = print_result("WRITE without action", gate.evaluate(intent), GateDecision.CLARIFY)


# ============================================================================
# TEST SUITE 3: DELETE OPERATIONS
# ============================================================================

def test_suite_3_delete_operations():
    """Test DELETE operations (should be DENIED by policy)"""
    print("\n" + "="*80)
    print("TEST SUITE 3: DELETE OPERATIONS")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Test 3.1: Delete with specific resource (should DENY)
    print("\n--- Test 3.1: DELETE specific resource ---")
    intent = create_intent(
        operation=OperationType.DELETE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="terminate",
        resource_ids=["i-12345"]
    )
    result = print_result("DELETE - Terminate EC2", gate.evaluate(intent), GateDecision.REJECT)
    
    # Test 3.2: Delete without resource IDs (should DENY)
    print("\n--- Test 3.2: DELETE all resources ---")
    intent = create_intent(
        operation=OperationType.DELETE,
        service="s3",
        confidence=ConfidenceLevel.HIGH,
        action="delete",
        resource_ids=[]
    )
    result = print_result("DELETE - All S3 buckets", gate.evaluate(intent), GateDecision.REJECT)
    
    # Test 3.3: Delete with low confidence (should CLARIFY before policy check)
    print("\n--- Test 3.3: DELETE with low confidence ---")
    intent = create_intent(
        operation=OperationType.DELETE,
        service="rds",
        confidence=ConfidenceLevel.LOW,
        action="delete"
    )
    result = print_result("Low confidence DELETE", gate.evaluate(intent), GateDecision.CLARIFY)


# ============================================================================
# TEST SUITE 4: PROTECTED RESOURCES
# ============================================================================

def test_suite_4_protected_resources():
    """Test operations on protected resources (production, etc)"""
    print("\n" + "="*80)
    print("TEST SUITE 4: PROTECTED RESOURCES")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Test 4.1: Write to production resource (should CONFIRM)
    print("\n--- Test 4.1: WRITE to production resource ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="restart",
        resource_ids=["i-production-server"]
    )
    result = print_result("WRITE to production resource ID", gate.evaluate(intent), GateDecision.REJECT)
    
    # Test 4.2: Write to resource with production tag (should DENY)
    print("\n--- Test 4.2: WRITE to resource with production tag ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="rds",
        confidence=ConfidenceLevel.HIGH,
        action="reboot",
        filters=[
            ResourceFilter(
                filter_type="tag",
                key="Environment",
                value="production",
                operator="equals"
            )
        ]
    )
    result = print_result("WRITE to production tagged resource", gate.evaluate(intent), GateDecision.REJECT)
    
    # Test 4.3: Write to development resource (should CONFIRM)
    print("\n--- Test 4.3: WRITE to development resource ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        filters=[
            ResourceFilter(
                filter_type="tag",
                key="Environment",
                value="development",
                operator="equals"
            )
        ]
    )
    result = print_result("WRITE to development resource", gate.evaluate(intent), GateDecision.CONFIRM)


# ============================================================================
# TEST SUITE 5: AMBIGUITIES AND MISSING INFO
# ============================================================================

def test_suite_5_ambiguities():
    """Test intents with ambiguities or missing information"""
    print("\n" + "="*80)
    print("TEST SUITE 5: AMBIGUITIES AND MISSING INFO")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Test 5.1: Unknown service (should CLARIFY)
    print("\n--- Test 5.1: Unknown service ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="unknown",
        confidence=ConfidenceLevel.HIGH,
        action="list"
    )
    result = print_result("Unknown service", gate.evaluate(intent), GateDecision.CLARIFY)
    
    # Test 5.2: Write with region ambiguity (should CLARIFY)
    print("\n--- Test 5.2: WRITE with region ambiguity ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        ambiguities=["Region not specified"]
    )
    result = print_result("WRITE with region ambiguity", gate.evaluate(intent), GateDecision.CLARIFY)
    
    # Test 5.3: Error intent (should REJECT)
    print("\n--- Test 5.3: Error intent ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="ec2",
        confidence=ConfidenceLevel.LOW,
        query_type="error"
    )
    result = print_result("Error intent", gate.evaluate(intent), GateDecision.REJECT)


# ============================================================================
# TEST SUITE 6: RESOURCE CONSTRAINTS
# ============================================================================

def test_suite_6_resource_constraints():
    """Test resource limit constraints"""
    print("\n" + "="*80)
    print("TEST SUITE 6: RESOURCE CONSTRAINTS")
    print("="*80)
    
    gate = IntentGate(
        enable_policies=True,
        config={'max_resource_limit': 50}
    )
    
    # Test 6.1: Excessive limit on write (should REJECT)
    print("\n--- Test 6.1: WRITE with excessive limit ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop"
    )
    intent.limit = 100  # Exceeds max of 50
    result = print_result("WRITE with limit=100 (max=50)", gate.evaluate(intent), GateDecision.REJECT)
    
    # Test 6.2: Acceptable limit (should CONFIRM)
    print("\n--- Test 6.2: WRITE with acceptable limit ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop"
    )
    intent.limit = 30  # Within limit
    result = print_result("WRITE with limit=30 (max=50)", gate.evaluate(intent), GateDecision.CONFIRM)


# ============================================================================
# TEST SUITE 7: CONFIRMATION FLOW
# ============================================================================

def test_suite_7_confirmation_flow():
    """Test confirmation processing"""
    print("\n" + "="*80)
    print("TEST SUITE 7: CONFIRMATION FLOW")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Create a write intent that requires confirmation
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        resource_ids=["i-12345"]
    )
    
    # Test 7.1: Initial request (should CONFIRM)
    print("\n--- Test 7.1: Initial request ---")
    result = print_result("Initial WRITE request", gate.evaluate(intent), GateDecision.CONFIRM)
    
    # Test 7.2: User confirms (should PROCEED)
    print("\n--- Test 7.2: User confirms ---")
    confirmed = gate.process_confirmation(result, "confirm")
    print_result("After user confirms", confirmed, GateDecision.PROCEED)
    
    # Test 7.3: User rejects (should REJECT)
    print("\n--- Test 7.3: User rejects ---")
    rejected = gate.process_confirmation(result, "cancel")
    print_result("After user cancels", rejected, GateDecision.REJECT)
    
    # Test 7.4: Ambiguous response (should stay CONFIRM)
    print("\n--- Test 7.4: Ambiguous response ---")
    ambiguous = gate.process_confirmation(result, "maybe")
    print_result("After ambiguous response", ambiguous, GateDecision.CONFIRM)


# ============================================================================
# TEST SUITE 8: MULTI-TURN CONVERSATION
# ============================================================================

def test_suite_8_multi_turn():
    """Test multi-turn conversation handling"""
    print("\n" + "="*80)
    print("TEST SUITE 8: MULTI-TURN CONVERSATION")
    print("="*80)
    
    gate = IntentGateWithHistory(enable_policies=True)
    conv_id = "test-conversation-1"
    
    # Turn 1: Initial query with ambiguity
    print("\n--- Turn 1: Query with region ambiguity ---")
    intent1 = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        regions=[],
        ambiguities=["Region not specified"]
    )
    result1 = gate.evaluate(intent1, conv_id)
    print_result("Turn 1: Initial query", result1, GateDecision.CLARIFY)
    
    # Turn 2: User provides region
    print("\n--- Turn 2: User provides region ---")
    intent2 = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        regions=["us-east-1"]
    )
    result2 = gate.process_followup(conv_id, "us-east-1", intent2)
    print_result("Turn 2: After region provided", result2, GateDecision.CONFIRM)
    
    # Turn 3: User confirms
    print("\n--- Turn 3: User confirms ---")
    result3 = gate.process_followup(conv_id, "confirm", None)
    print_result("Turn 3: After confirmation", result3, GateDecision.PROCEED)
    
    # Cleanup
    gate.clear_pending(conv_id)


# ============================================================================
# TEST SUITE 9: CUSTOM POLICIES
# ============================================================================

def test_suite_9_custom_policies():
    """Test with custom policies"""
    print("\n" + "="*80)
    print("TEST SUITE 9: CUSTOM POLICIES")
    print("="*80)
    
    # Create gate with no default policies
    gate = IntentGate(enable_policies=True, policies=[])
    
    # Add custom policy: Only allow EC2 reads
    custom_policy = (
        PolicyBuilder("custom-restrictive")
        .statement("allow-ec2-reads")
        .allow()
        .read_operations()
        .service("ec2")
        .end_statement()
        .build()
    )
    gate.add_policy(custom_policy)
    
    # Test 9.1: EC2 read (should PROCEED)
    print("\n--- Test 9.1: EC2 READ (allowed) ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="list"
    )
    result = print_result("EC2 READ with custom policy", gate.evaluate(intent), GateDecision.PROCEED)
    
    # Test 9.2: S3 read (should DENY - not in policy)
    print("\n--- Test 9.2: S3 READ (not allowed) ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="s3",
        confidence=ConfidenceLevel.HIGH,
        action="list"
    )
    result = print_result("S3 READ with custom policy", gate.evaluate(intent), GateDecision.REJECT)


# ============================================================================
# TEST SUITE 10: EDGE CASES
# ============================================================================

def test_suite_10_edge_cases():
    """Test edge cases and special scenarios"""
    print("\n" + "="*80)
    print("TEST SUITE 10: EDGE CASES")
    print("="*80)
    
    gate = IntentGate(enable_policies=True)
    
    # Test 10.1: Operation with multiple confirmations needed
    print("\n--- Test 10.1: Multiple confirmation triggers ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="stop",
        resource_ids=[],  # No resource IDs (broad operation)
        filters=[]  # No filters (affects all)
    )
    result = print_result("Broad WRITE with no filters", gate.evaluate(intent))
    print(f"   Number of confirmations: {len(result.required_confirmations)}")
    
    # Test 10.2: Write to master branch resource
    print("\n--- Test 10.2: Protected pattern 'master' ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="lambda",
        confidence=ConfidenceLevel.HIGH,
        action="update",
        resource_ids=["master-function"]
    )
    result = print_result("WRITE to 'master' resource", gate.evaluate(intent), GateDecision.CONFIRM)
    
    # Test 10.3: High risk action
    print("\n--- Test 10.3: High risk action (restart) ---")
    intent = create_intent(
        operation=OperationType.WRITE,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        action="restart",
        resource_ids=["i-12345"]
    )
    result = print_result("High risk action: restart", gate.evaluate(intent))
    
    # Test 10.4: Read with filters but no resource type
    print("\n--- Test 10.4: Filters without resource type ---")
    intent = create_intent(
        operation=OperationType.READ,
        service="ec2",
        confidence=ConfidenceLevel.HIGH,
        resource_type="",
        action="describe",
        filters=[
            ResourceFilter(
                filter_type="tag",
                key="Name",
                value="test",
                operator="equals"
            )
        ]
    )
    result = print_result("READ with filters, no resource type", gate.evaluate(intent), GateDecision.CLARIFY)


# ============================================================================
# RUN ALL TESTS
# ============================================================================

def run_all_tests():
    """Run all test suites"""
    print("\n" + "="*80)
    print("INTENT GATE - COMPREHENSIVE TEST SUITE")
    print("="*80)
    print("Testing all validation layers and decision paths")
    print("="*80)
    
    test_suite_1_basic_reads()
    test_suite_2_write_operations()
    test_suite_3_delete_operations()
    test_suite_4_protected_resources()
    test_suite_5_ambiguities()
    test_suite_6_resource_constraints()
    test_suite_7_confirmation_flow()
    test_suite_8_multi_turn()
    test_suite_9_custom_policies()
    test_suite_10_edge_cases()
    
    print("\n" + "="*80)
    print("✅ ALL TEST SUITES COMPLETED")
    print("="*80)


if __name__ == "__main__":
    run_all_tests()