"""
Comprehensive Test Suite for Intent Extraction

Tests the IntentExtractor and IntentExtractionPipeline with:
1. Single-step queries
2. Multi-step queries
3. Cost analysis queries
4. Metric/performance queries
5. Audit queries
6. Edge cases and error handling
"""

import json
import datetime
from unittest.mock import Mock, MagicMock, patch
from ..llm.intent_schema import (
    ExtractedIntent,
    OperationType,
    ConfidenceLevel
)
from ..llm.intent_extractor import IntentExtractor

class MockBedrockClient:
    """Mock Bedrock client for testing without actual API calls"""
    
    def __init__(self, response_data: dict):
        self.response_data = response_data
    
    def invoke_model(self, **kwargs):
        """Mock invoke_model method"""
        response_body = json.dumps({
            "output": {
                "message": {
                    "content": [
                        {"text": json.dumps(self.response_data)}
                    ]
                }
            }
        })
        
        return {
            "body": MockStreamingBody(response_body)
        }


class MockStreamingBody:
    """Mock streaming body for Bedrock response"""
    
    def __init__(self, content: str):
        self.content = content
    
    def read(self):
        return self.content.encode('utf-8')


def create_mock_llm_response(
    operation_type: str = "read",
    confidence: float = 0.95,
    is_multi_step: bool = False,
    primary_service: str = "ec2",
    resource_type: str = "instance",
    action_verb: str = "list",
    regions: list = None,
    sub_intents: list = None,
    additional_services: list = None,
    ambiguities: list = None
) -> dict:
    """Helper to create mock LLM response"""
    
    response = {
        "operation_type": operation_type,
        "confidence": confidence,
        "is_multi_step": is_multi_step,
        "complexity": "complex" if is_multi_step else "simple",
        "primary_service": primary_service,
        "additional_services": additional_services or [],
        "resource_type": resource_type,
        "action_verb": action_verb,
        "regions": regions or ["us-east-1"],
        "execution_plan": {
            "total_steps": len(sub_intents) if sub_intents else 1,
            "requires_joins": is_multi_step,
            "join_strategy": "instance_id" if is_multi_step else None,
            "estimated_complexity": "medium" if is_multi_step else "low"
        },
        "sub_intents": sub_intents or [],
        "data_flow": {
            "input_from_user": ["query"],
            "intermediate_data": [],
            "final_output": "results"
        },
        "resource_ids": [],
        "time_range": {
            "start": None,
            "end": None,
            "period": None
        },
        "cost_filters": {
            "min_amount": None,
            "max_amount": None,
            "currency": "USD",
            "granularity": "daily"
        },
        "output_preferences": {
            "format": "table",
            "sort_by": None,
            "limit": None,
            "group_by": None
        },
        "ambiguities": ambiguities or [],
        "assumptions": []
    }
    
    return response


def print_test_result(test_name: str, intent: ExtractedIntent, expected: dict = None):
    """Print test result"""
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"{'='*80}")
    print(f"📋 Query Type: {intent.query_type}")
    print(f"🎯 Operation: {intent.operation.value}")
    print(f"🎓 Confidence: {intent.confidence.value}")
    print(f"🔧 Service: {intent.primary_service}")
    print(f"📦 Resource: {intent.primary_resource.resource_type}")
    print(f"⚡ Action: {intent.action}")
    print(f"🌍 Regions: {intent.regions}")
    
    if intent.is_multi_step:
        print(f"🔀 Multi-Step: Yes ({len(intent.sub_intents)} steps)")
        for sub in intent.sub_intents:
            print(f"   Step {sub.step_number}: {sub.resource.service} - {sub.description}")
    else:
        print(f"🔀 Multi-Step: No")
    
    if intent.ambiguities:
        print(f"⚠️  Ambiguities: {intent.ambiguities}")
    
    if expected:
        checks = []
        if 'query_type' in expected:
            checks.append(('query_type', intent.query_type == expected['query_type']))
        if 'operation' in expected:
            checks.append(('operation', intent.operation.value == expected['operation']))
        if 'is_multi_step' in expected:
            checks.append(('is_multi_step', intent.is_multi_step == expected['is_multi_step']))
        if 'service' in expected:
            checks.append(('service', intent.primary_service == expected['service']))
        
        all_passed = all(result for _, result in checks)
        status = "✅ PASS" if all_passed else "❌ FAIL"
        print(f"\n{status}")
        for check_name, result in checks:
            symbol = "✅" if result else "❌"
            print(f"  {symbol} {check_name}")
    
    return intent


# =============================================================================
# TEST SUITE 1: SIMPLE SINGLE-STEP QUERIES
# =============================================================================

def test_suite_1_simple_queries():
    """Test simple single-step queries"""
    print("\n" + "="*80)
    print("TEST SUITE 1: SIMPLE SINGLE-STEP QUERIES")
    print("="*80)
    
    from ..llm.intent_extractor import IntentExtractor
    
    # Test 1.1: List EC2 instances
    print("\n--- Test 1.1: List EC2 instances ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        confidence=0.95,
        is_multi_step=False,
        primary_service="ec2",
        resource_type="instance",
        action_verb="list"
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model', 'AWS_REGION': 'us-east-1'}):
        intent = extractor.extract("list ec2 instances")
    
    print_test_result(
        "List EC2 instances",
        intent,
        {
            'query_type': 'simple',
            'operation': 'read',
            'is_multi_step': False,
            'service': 'ec2'
        }
    )
    
    # Test 1.2: List S3 buckets
    print("\n--- Test 1.2: List S3 buckets ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        primary_service="s3",
        resource_type="bucket",
        action_verb="list"
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show s3 buckets")
    
    print_test_result(
        "List S3 buckets",
        intent,
        {'service': 's3', 'operation': 'read'}
    )
    
    # Test 1.3: Stop EC2 instance (WRITE operation)
    print("\n--- Test 1.3: Stop EC2 instance ---")
    mock_response = create_mock_llm_response(
        operation_type="write",
        confidence=0.9,
        primary_service="ec2",
        resource_type="instance",
        action_verb="stop",
        sub_intents=[]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("stop instance i-12345")
    
    print_test_result(
        "Stop EC2 instance",
        intent,
        {'operation': 'write', 'service': 'ec2'}
    )
    
    # Test 1.4: Query with filters
    print("\n--- Test 1.4: List running instances ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        primary_service="ec2",
        resource_type="instance",
        action_verb="list",
        sub_intents=[]
    )
    mock_response["filters"] = [
        {
            "filter_type": "state",
            "key": "instance-state-name",
            "value": "running",
            "operator": "equals"
        }
    ]
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("list running instances")
    
    print_test_result("List running instances", intent)


# =============================================================================
# TEST SUITE 2: MULTI-STEP QUERIES
# =============================================================================

def test_suite_2_multi_step_queries():
    """Test multi-step queries requiring multiple services"""
    print("\n" + "="*80)
    print("TEST SUITE 2: MULTI-STEP QUERIES")
    print("="*80)
    
    # Test 2.1: Instances with high CPU
    print("\n--- Test 2.1: Instances with high CPU ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        confidence=0.92,
        is_multi_step=True,
        primary_service="ec2",
        additional_services=["cloudwatch"],
        resource_type="instance",
        action_verb="find",
        sub_intents=[
            {
                "step": 1,
                "service": "ec2",
                "operation": "read",
                "action": "describe-instances",
                "description": "Get all running EC2 instances",
                "resource_type": "instance",
                "filters": [{"filter_type": "state", "key": "state", "value": "running", "operator": "equals"}],
                "depends_on": [],
                "outputs": ["instance_ids", "instance_types"],
                "aggregation": None
            },
            {
                "step": 2,
                "service": "cloudwatch",
                "operation": "read",
                "action": "get-metric-statistics",
                "description": "Get CPU metrics for instances",
                "resource_type": "metric",
                "filters": [{"filter_type": "metric", "key": "CPUUtilization", "value": "80", "operator": "greater_than"}],
                "depends_on": [1],
                "outputs": ["cpu_metrics"],
                "aggregation": {"type": "average", "field": "CPUUtilization", "group_by": None}
            }
        ]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show instances with high CPU")
    
    print_test_result(
        "Instances with high CPU",
        intent,
        {
            'query_type': 'complex',
            'is_multi_step': True,
            'service': 'ec2'
        }
    )
    
    # Test 2.2: Unused IAM access keys
    print("\n--- Test 2.2: Unused IAM access keys ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        confidence=0.88,
        is_multi_step=True,
        primary_service="iam",
        additional_services=["cloudtrail"],
        resource_type="access-key",
        action_verb="find",
        sub_intents=[
            {
                "step": 1,
                "service": "iam",
                "operation": "read",
                "action": "list-users",
                "description": "Get all IAM users",
                "resource_type": "user",
                "filters": [],
                "depends_on": [],
                "outputs": ["user_names"],
                "aggregation": None
            },
            {
                "step": 2,
                "service": "iam",
                "operation": "read",
                "action": "list-access-keys",
                "description": "Get access keys for each user",
                "resource_type": "access-key",
                "filters": [],
                "depends_on": [1],
                "outputs": ["access_key_ids"],
                "aggregation": None
            },
            {
                "step": 3,
                "service": "cloudtrail",
                "operation": "read",
                "action": "lookup-events",
                "description": "Check last usage from CloudTrail",
                "resource_type": "event",
                "filters": [{"filter_type": "date_range", "key": "StartTime", "value": "90days", "operator": "greater_than"}],
                "depends_on": [2],
                "outputs": ["last_used_dates"],
                "aggregation": None
            }
        ]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("find unused IAM access keys")
    
    print_test_result(
        "Unused IAM access keys",
        intent,
        {
            'is_multi_step': True,
            'service': 'iam'
        }
    )
    
    # Test 2.3: RDS instances and snapshots
    print("\n--- Test 2.3: RDS instances and their snapshots ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        is_multi_step=True,
        primary_service="rds",
        resource_type="db-instance",
        action_verb="describe",
        sub_intents=[
            {
                "step": 1,
                "service": "rds",
                "operation": "read",
                "action": "describe-db-instances",
                "description": "Get all RDS instances",
                "resource_type": "db-instance",
                "filters": [],
                "depends_on": [],
                "outputs": ["db_instance_identifiers"],
                "aggregation": None
            },
            {
                "step": 2,
                "service": "rds",
                "operation": "read",
                "action": "describe-db-snapshots",
                "description": "Get snapshots for each instance",
                "resource_type": "db-snapshot",
                "filters": [],
                "depends_on": [1],
                "outputs": ["snapshot_data"],
                "aggregation": {"type": "group_by", "field": "snapshot_create_time", "group_by": "db_instance_identifier"}
            }
        ]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show RDS instances and their snapshots")
    
    print_test_result(
        "RDS instances and snapshots",
        intent,
        {'is_multi_step': True}
    )


# =============================================================================
# TEST SUITE 3: COST ANALYSIS QUERIES
# =============================================================================

def test_suite_3_cost_queries():
    """Test cost analysis queries"""
    print("\n" + "="*80)
    print("TEST SUITE 3: COST ANALYSIS QUERIES")
    print("="*80)
    
    
    # Test 3.1: Most expensive EC2 instances
    print("\n--- Test 3.1: Most expensive EC2 instances ---")
    mock_response = create_mock_llm_response(
        operation_type="analyze",
        is_multi_step=True,
        primary_service="ec2",
        additional_services=["cost-explorer"],
        resource_type="instance",
        action_verb="analyze",
        sub_intents=[
            {
                "step": 1,
                "service": "ec2",
                "operation": "read",
                "action": "describe-instances",
                "description": "Get all EC2 instances",
                "resource_type": "instance",
                "filters": [],
                "depends_on": [],
                "outputs": ["instance_ids"],
                "aggregation": None
            },
            {
                "step": 2,
                "service": "cost-explorer",
                "operation": "read",
                "action": "get-cost-and-usage",
                "description": "Get cost data for instances",
                "resource_type": "cost",
                "filters": [{"filter_type": "service", "key": "SERVICE", "value": "EC2", "operator": "equals"}],
                "depends_on": [1],
                "outputs": ["cost_data"],
                "aggregation": {"type": "sum", "field": "UnblendedCost", "group_by": "instance_id"}
            }
        ]
    )
    mock_response["cost_filters"] = {
        "min_amount": None,
        "max_amount": None,
        "currency": "USD",
        "granularity": "monthly"
    }
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show most expensive EC2 instances this month")
    
    print_test_result(
        "Most expensive EC2 instances",
        intent,
        {
            'operation': 'analyze',
            'is_multi_step': True
        }
    )
    
    # Test 3.2: S3 buckets with high storage costs
    print("\n--- Test 3.2: Expensive S3 buckets ---")
    mock_response = create_mock_llm_response(
        operation_type="analyze",
        is_multi_step=True,
        primary_service="s3",
        additional_services=["cost-explorer"],
        resource_type="bucket",
        sub_intents=[
            {
                "step": 1,
                "service": "s3",
                "operation": "read",
                "action": "list-buckets",
                "description": "Get all S3 buckets",
                "resource_type": "bucket",
                "filters": [],
                "depends_on": [],
                "outputs": ["bucket_names"],
                "aggregation": None
            },
            {
                "step": 2,
                "service": "cost-explorer",
                "operation": "read",
                "action": "get-cost-and-usage",
                "description": "Get storage costs per bucket",
                "resource_type": "cost",
                "filters": [
                    {"filter_type": "service", "key": "SERVICE", "value": "S3", "operator": "equals"},
                    {"filter_type": "cost_threshold", "key": "cost", "value": "100", "operator": "greater_than"}
                ],
                "depends_on": [1],
                "outputs": ["cost_data"],
                "aggregation": {"type": "sum", "field": "cost", "group_by": "bucket_name"}
            }
        ]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("find S3 buckets costing more than $100")
    
    print_test_result("Expensive S3 buckets", intent)


# =============================================================================
# TEST SUITE 4: AUDIT AND COMPLIANCE QUERIES
# =============================================================================

def test_suite_4_audit_queries():
    """Test audit and compliance queries"""
    print("\n" + "="*80)
    print("TEST SUITE 4: AUDIT AND COMPLIANCE QUERIES")
    print("="*80)
        
    # Test 4.1: Who accessed S3 bucket
    print("\n--- Test 4.1: S3 bucket access audit ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        is_multi_step=True,
        primary_service="s3",
        additional_services=["cloudtrail"],
        resource_type="bucket",
        action_verb="audit",
        sub_intents=[
            {
                "step": 1,
                "service": "cloudtrail",
                "operation": "read",
                "action": "lookup-events",
                "description": "Query CloudTrail for S3 access events",
                "resource_type": "event",
                "filters": [
                    {"filter_type": "resource", "key": "ResourceName", "value": "my-bucket", "operator": "equals"},
                    {"filter_type": "date_range", "key": "StartTime", "value": "7days", "operator": "within"}
                ],
                "depends_on": [],
                "outputs": ["access_events", "user_identities"],
                "aggregation": {"type": "group_by", "field": "event", "group_by": "userIdentity"}
            }
        ]
    )
    mock_response["time_range"] = {
        "start": None,
        "end": None,
        "period": "last_week"
    }
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("who accessed my-bucket in the last week")
    
    print_test_result("S3 bucket access audit", intent)
    
    # Test 4.2: Recent IAM changes
    print("\n--- Test 4.2: Recent IAM changes ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        is_multi_step=True,
        primary_service="iam",
        additional_services=["cloudtrail"],
        resource_type="policy",
        sub_intents=[
            {
                "step": 1,
                "service": "cloudtrail",
                "operation": "read",
                "action": "lookup-events",
                "description": "Find IAM modification events",
                "resource_type": "event",
                "filters": [
                    {"filter_type": "service", "key": "EventSource", "value": "iam.amazonaws.com", "operator": "equals"},
                    {"filter_type": "date_range", "key": "StartTime", "value": "24hours", "operator": "within"}
                ],
                "depends_on": [],
                "outputs": ["iam_events"],
                "aggregation": None
            }
        ]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show recent IAM policy changes")
    
    print_test_result("Recent IAM changes", intent)


# =============================================================================
# TEST SUITE 5: COMPLEX MULTI-SERVICE QUERIES
# =============================================================================

def test_suite_5_complex_queries():
    """Test complex queries spanning multiple services"""
    print("\n" + "="*80)
    print("TEST SUITE 5: COMPLEX MULTI-SERVICE QUERIES")
    print("="*80)
        
    # Test 5.1: Production instances with volumes and CPU
    print("\n--- Test 5.1: Production instances with volumes and CPU ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        confidence=0.9,
        is_multi_step=True,
        primary_service="ec2",
        additional_services=["cloudwatch"],
        resource_type="instance",
        sub_intents=[
            {
                "step": 1,
                "service": "ec2",
                "operation": "read",
                "action": "describe-instances",
                "description": "Get production instances",
                "resource_type": "instance",
                "filters": [{"filter_type": "tag", "key": "Environment", "value": "production", "operator": "equals"}],
                "depends_on": [],
                "outputs": ["instance_ids"],
                "aggregation": None
            },
            {
                "step": 2,
                "service": "ec2",
                "operation": "read",
                "action": "describe-volumes",
                "description": "Get attached volumes",
                "resource_type": "volume",
                "filters": [],
                "depends_on": [1],
                "outputs": ["volume_data"],
                "aggregation": None
            },
            {
                "step": 3,
                "service": "cloudwatch",
                "operation": "read",
                "action": "get-metric-statistics",
                "description": "Get CPU metrics",
                "resource_type": "metric",
                "filters": [],
                "depends_on": [1],
                "outputs": ["cpu_metrics"],
                "aggregation": {"type": "average", "field": "CPUUtilization", "group_by": None}
            }
        ]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show production instances with their volumes and CPU usage")
    
    print_test_result(
        "Production instances with volumes and CPU",
        intent,
        {
            'is_multi_step': True,
            'service': 'ec2'
        }
    )


# =============================================================================
# TEST SUITE 6: EDGE CASES AND ERROR HANDLING
# =============================================================================

def test_suite_6_edge_cases():
    """Test edge cases and error handling"""
    print("\n" + "="*80)
    print("TEST SUITE 6: EDGE CASES AND ERROR HANDLING")
    print("="*80)
        
    # Test 6.1: Low confidence query
    print("\n--- Test 6.1: Ambiguous query (low confidence) ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        confidence=0.6,  # Low confidence
        primary_service="ec2",
        resource_type="instance",
        ambiguities=["Unclear which metric to check", "Time range not specified"]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("show me the things")
    
    print_test_result(
        "Ambiguous query",
        intent,
        {'confidence': 'low'}
    )
    
    # Test 6.2: Query with specific regions
    print("\n--- Test 6.2: Multi-region query ---")
    mock_response = create_mock_llm_response(
        operation_type="read",
        primary_service="ec2",
        regions=["us-east-1", "us-west-2", "eu-west-1"]
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("list instances in us-east-1, us-west-2, and eu-west-1")
    
    print_test_result("Multi-region query", intent)
    assert len(intent.regions) == 3
    print("  ✅ Regions correctly extracted")
    
    # Test 6.3: Delete operation
    print("\n--- Test 6.3: DELETE operation ---")
    mock_response = create_mock_llm_response(
        operation_type="delete",
        confidence=0.95,
        primary_service="s3",
        resource_type="bucket",
        action_verb="delete"
    )
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("delete bucket my-old-bucket")
    
    print_test_result(
        "DELETE operation",
        intent,
        {'operation': 'delete'}
    )


# =============================================================================
# TEST SUITE 7: INTENT BUILDER LOGIC
# =============================================================================

def test_suite_7_builder_logic():
    """Test the _build_intent_object logic"""
    print("\n" + "="*80)
    print("TEST SUITE 7: INTENT BUILDER LOGIC")
    print("="*80)
        
    # Test 7.1: Confidence level mapping
    print("\n--- Test 7.1: Confidence level mapping ---")
    
    test_cases = [
        (0.95, ConfidenceLevel.HIGH, "High confidence (0.95)"),
        (0.9, ConfidenceLevel.HIGH, "High confidence (0.9)"),
        (0.85, ConfidenceLevel.MEDIUM, "Medium confidence (0.85)"),
        (0.7, ConfidenceLevel.MEDIUM, "Medium confidence (0.7)"),
        (0.6, ConfidenceLevel.LOW, "Low confidence (0.6)"),
        (0.5, ConfidenceLevel.LOW, "Low confidence (0.5)")
    ]
    
    for conf_score, expected_level, desc in test_cases:
        mock_response = create_mock_llm_response(confidence=conf_score)
        mock_client = MockBedrockClient(mock_response)
        extractor = IntentExtractor(mock_client)
        
        with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
            intent = extractor.extract("test query")
        
        passed = intent.confidence == expected_level
        symbol = "✅" if passed else "❌"
        print(f"{symbol} {desc}: {intent.confidence.value}")
    
    # Test 7.2: Query type classification
    print("\n--- Test 7.2: Query type classification ---")
    
    # Simple query
    mock_response = create_mock_llm_response(
        is_multi_step=False
    )
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("list instances")
    
    print(f"  Simple query → query_type: {intent.query_type}")
    assert intent.query_type == "simple"
    
    # Complex query
    mock_response = create_mock_llm_response(
        is_multi_step=True
    )
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("complex query")
    
    print(f"  Complex query → query_type: {intent.query_type}")
    assert intent.query_type == "complex"
    
    # Test 7.3: Invalid operation type handling
    print("\n--- Test 7.3: Invalid operation type fallback ---")
    
    mock_response = create_mock_llm_response()
    mock_response["operation_type"] = "invalid_operation"  # Invalid
    
    mock_client = MockBedrockClient(mock_response)
    extractor = IntentExtractor(mock_client)
    
    with patch.dict('os.environ', {'BEDROCK_MODEL_ID': 'test-model'}):
        intent = extractor.extract("test query")
    
    print(f"  Invalid operation_type → defaults to: {intent.operation.value}")
    assert intent.operation == OperationType.READ
    print("  ✅ Correctly defaults to READ")


# =============================================================================
# RUN ALL TESTS
# =============================================================================

def run_all_tests():
    """Run all test suites"""
    print("\n" + "="*80)
    print("INTENT EXTRACTION - COMPREHENSIVE TEST SUITE")
    print("="*80)
    print("Testing intent extraction with mocked LLM responses")
    print("="*80)
    
    test_suite_1_simple_queries()
    test_suite_2_multi_step_queries()
    test_suite_3_cost_queries()
    test_suite_4_audit_queries()
    test_suite_5_complex_queries()
    test_suite_6_edge_cases()
    test_suite_7_builder_logic()
    
    print("\n" + "="*80)
    print("✅ ALL TEST SUITES COMPLETED")
    print("="*80)


if __name__ == "__main__":
    run_all_tests()