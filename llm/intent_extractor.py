import datetime
import json
import logging
import sys
from typing import Dict
from .intent_schema import *
from dotenv import load_dotenv
import boto3
import os

load_dotenv(dotenv_path="../.env")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

class IntentExtractor:
    """Fast path for simple, clear queries"""
    
    def __init__(self, bedrock_client):
        self.bedrock = bedrock_client
        self.model_id = os.getenv('BEDROCK_MODEL_ID')
        self.regions = [os.getenv('AWS_REGION', 'us-east-1')]
    
    EXTRACTION_PROMPT = """You are an AWS multi-step query planner. Analyze the user's query and create a complete execution plan.

AWS Services & Their Data:
- ec2: Instances, volumes, AMIs, security groups, network interfaces
- s3: Buckets, objects, storage classes, access logs
- rds: Databases, snapshots, parameter groups
- lambda: Functions, layers, event sources
- ecs/eks: Containers, clusters, services, tasks
- vpc: Subnets, route tables, NACLs, VPNs, transit gateways
- iam: Users, roles, policies, access keys, login profiles
- cloudwatch: Metrics, alarms, logs, dashboards
- cloudtrail: API activity, events, audit logs
- cost-explorer: Costs, usage, forecasts, budgets
- elb/alb: Load balancers, target groups, listeners
- route53: Hosted zones, record sets, health checks
- dynamodb: Tables, items, indexes, backups
- sns/sqs: Topics, subscriptions, queues, messages
- cloudformation: Stacks, resources, templates
- systems-manager: Parameters, documents, patch compliance
- config: Configuration items, compliance, rules
- trusted-advisor: Recommendations, checks
- organizations: Accounts, OUs, policies

Multi-Step Query Indicators:
1. **Cross-Service Dependencies**: Query needs data from multiple services
   - "cost of instances" → EC2 + Cost Explorer
   - "unused IAM keys" → IAM users + IAM access keys + CloudTrail
   - "expensive buckets" → S3 + Cost Explorer
   
2. **Metric/Performance Data**: Performance metrics require CloudWatch
   - "high CPU instances" → EC2 + CloudWatch
   - "slow lambda functions" → Lambda + CloudWatch
   - "database connections" → RDS + CloudWatch
   
3. **Audit/Activity Data**: Activity tracking requires CloudTrail/CloudWatch Logs
   - "who accessed this bucket" → S3 + CloudTrail
   - "recent IAM changes" → IAM + CloudTrail
   - "API calls from IP" → CloudTrail
   
4. **Cost Analysis**: Financial queries require Cost Explorer
   - "most expensive resources" → Resource API + Cost Explorer
   - "cost breakdown by service" → Cost Explorer + multiple services
   - "budget utilization" → Cost Explorer + Budgets
   
5. **Compliance/Config**: Configuration compliance needs Config service
   - "non-compliant resources" → Config + resource API
   - "security group changes" → EC2 + Config + CloudTrail
   
6. **Same-Service Multi-Step**: Multiple calls to same service
   - "instances and their volumes" → EC2 (instances) + EC2 (volumes)
   - "users and their access keys" → IAM (users) + IAM (access keys)
   - "RDS instances and snapshots" → RDS (instances) + RDS (snapshots)

7. **Aggregation Across Dimensions**: Requires collecting and joining data
   - "instances per VPC" → EC2 (instances) + VPC data + aggregation
   - "costs by account" → Cost Explorer across accounts
   - "resources by region" → Multiple region queries + aggregation

User Query: {query}

Analyze the query and determine:
1. What data sources are needed?
2. What is the dependency order? (what must be fetched first?)
3. How should data be joined/correlated?
4. Is this single-step or multi-step?

Extract and respond in this EXACT JSON schema:
{{
    "operation_type": "read|write|delete|analyze",
    "confidence": 0.0-1.0,
    "is_multi_step": true|false,
    "complexity": "simple|moderate|complex",
    "primary_service": "main_aws_service",
    "additional_services": ["other_services_needed"],
    "resource_type": "primary_resource_type",
    "action_verb": "exact_action",
    "regions": ["region_codes"],
    
    "execution_plan": {{
        "total_steps": number,
        "requires_joins": true|false,
        "join_strategy": "instance_id|bucket_name|user_name|resource_arn|null",
        "estimated_complexity": "low|medium|high"
    }},
    
    "sub_intents": [
        {{
            "step": 1,
            "service": "aws_service",
            "action": "api_action",
            "description": "what this step does",
            "resource_type": "resource_type",
            "filters": [
                {{
                    "filter_type": "state|tag|name|id|type|date_range|cost_threshold",
                    "key": "filter_key",
                    "value": "filter_value",
                    "operator": "equals|contains|greater_than|less_than|between"
                }}
            ],
            "depends_on": [step_numbers_this_depends_on],
            "outputs": ["what_data_this_step_produces"],
            "aggregation": {{
                "type": "sum|count|average|group_by|null",
                "field": "field_to_aggregate",
                "group_by": "field_to_group_by"
            }}
        }}
    ],
    
    "data_flow": {{
        "input_from_user": ["what_user_provided"],
        "intermediate_data": [
            {{
                "step": step_number,
                "data": "what_data_is_passed_between_steps"
            }}
        ],
        "final_output": "what_user_gets"
    }},
    
    "resource_ids": ["specific_ids_if_mentioned"],
    "time_range": {{
        "start": "datetime_or_null",
        "end": "datetime_or_null",
        "period": "last_hour|last_day|last_week|last_month|null"
    }},
    "cost_filters": {{
        "min_amount": number_or_null,
        "max_amount": number_or_null,
        "currency": "USD",
        "granularity": "daily|monthly|hourly"
    }},
    "output_preferences": {{
        "format": "table|json|summary|chart",
        "sort_by": "field_name_or_null",
        "limit": number_or_null,
        "group_by": "field_name_or_null"
    }},
    "ambiguities": ["unclear_aspects"],
    "assumptions": ["what_we_assumed"]
}}

CRITICAL RULES:
1. Set is_multi_step=true if query needs data from multiple services OR multiple API calls
2. Order sub_intents by dependency (data needed from step 1 before step 2 can run)
3. Specify join_strategy when steps need to be correlated (e.g., instance_id links EC2 to CloudWatch)
4. Include depends_on array to show step dependencies
5. Identify what intermediate data flows between steps
6. For cost queries, always include Cost Explorer as a step
7. For metric queries, always include CloudWatch as a step
8. For audit queries, include CloudTrail/Config as appropriate
9. Same-service multi-step is valid (e.g., EC2 instances + EC2 volumes)
10. Always return json response only without any additional text, starting with {{ and ending with }}.

Examples:

Query: "Show me the cost of instances with high CPU"
→ is_multi_step: true
→ Steps: 1) EC2 describe-instances (state=running), 2) CloudWatch get-metrics (CPU > 80%), 3) Cost Explorer get-cost-and-usage (for filtered instances)

Query: "Find unused IAM access keys"
→ is_multi_step: true
→ Steps: 1) IAM list-users, 2) IAM list-access-keys (for each user), 3) CloudTrail query-events (check last used)

Query: "List running instances in us-east-1"
→ is_multi_step: false
→ Steps: 1) EC2 describe-instances (single call)

Query: "Most expensive S3 buckets this month"
→ is_multi_step: true
→ Steps: 1) S3 list-buckets, 2) Cost Explorer get-cost-and-usage (group by bucket, this month)

Query: "RDS instances and their latest snapshots"
→ is_multi_step: true
→ Steps: 1) RDS describe-db-instances, 2) RDS describe-db-snapshots (for each instance)

Query: "Show production instances with their attached volumes and current CPU usage"
→ is_multi_step: true
→ Steps: 1) EC2 describe-instances (tag:Environment=production), 2) EC2 describe-volumes (attached to instances from step 1), 3) CloudWatch get-metric-statistics (CPU for instances from step 1)

Always return json response only without any additional text, starting with {{ and ending with }}.
"""

    def extract(self, query: str) -> ExtractedIntent:
        """Extract intent from simple queries"""
        
        prompt = self.EXTRACTION_PROMPT.format(query=query)
        
        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                'inferenceConfig': {
                    'maxTokens': 2048,
                    'temperature': 0.0
                },
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}]
                    }
                ]
            })
        )
        
        result = json.loads(response['body'].read())
        
        # Validate response structure
        if result["output"]["message"]["content"] is None:
            raise ValueError("Empty response from LLM")
        
        # clean response text
        response_text = result["output"]["message"]["content"][0]['text'].strip()
        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        cleaned_text = response_text[start:end]
        
        # Parse JSON response
        try:
            extracted = json.loads(cleaned_text)
            logger.debug(f"Extracted intent: {extracted}")
        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON: {result["output"]["message"]["content"]}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        
        # Validate required fields
        required_fields = ['operation_type', 'primary_service', 'is_multi_step']
        missing = [f for f in required_fields if f not in extracted]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        
        # Convert to structured intent
        intent = self._build_intent_object(query, extracted)
        return intent
    
    def _build_intent_object(self, query: str, extracted: Dict) -> ExtractedIntent:
        """Build ExtractedIntent from raw extraction"""
        
        is_multi_step = extracted.get('is_multi_step', False)
        
        # Build sub-intents
        sub_intents = []
        filters = []
        
        for si in extracted.get('sub_intents', []):
            filters = [
                ResourceFilter(
                    filter_type=f.get('filter_type', 'unknown'),
                    key=f.get('key', ''),
                    value=f.get('value', ''),
                    operator=f.get('operator', 'equals')
                )
                for f in si.get('filters', [])
            ]
            
            sub_intent = SubIntent(
                step_number=si.get('step', 0),
                operation=OperationType(si.get('operation', 'read').lower()),
                resource=AWSResource(
                    service=si.get('service', ''),
                    resource_type=si.get('resource_type'),
                    resource_ids=si.get('resource_ids', []),
                    filters=filters
                ),
                description=si.get('description', ''),
                depends_on=si.get('depends_on', []),
                outputs=si.get('outputs', []),
                aggregation=si.get('aggregation')
            )
            sub_intents.append(sub_intent)
        
        # Build resource
        resource = AWSResource(
            service=extracted['primary_service'],
            resource_type=extracted.get('resource_type'),
            resource_ids=extracted.get('resource_ids', []),
            filters=filters
        )
        
        # Determine confidence level
        conf_score = extracted.get('confidence', 0.0)
        if conf_score >= 0.9:
            confidence = ConfidenceLevel.HIGH
        elif conf_score >= 0.7:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW
        
        # Validate and normalize operation_type
        operation_type = extracted.get('operation_type', 'read').lower()
        try:
            operation = OperationType(operation_type)
        except ValueError:
            logger.warning(f"Invalid operation_type '{operation_type}', defaulting to READ")
            operation = OperationType.READ
            
        # Use regions from extraction, fallback to default
        regions = extracted.get('regions', [])
        if not regions:
            regions = self.regions
        
        # Query type based on complexity
        complexity = extracted.get('complexity', 'simple')
        if is_multi_step or complexity in ['moderate', 'complex']:
            query_type = "complex"
        else:
            query_type = "simple"
        
        return ExtractedIntent(
            query_type=query_type,
            operation=operation,
            confidence=confidence,
            primary_service=extracted['primary_service'],
            primary_resource=resource,
            action=extracted.get('action_verb', ''),
            regions=regions,
            is_multi_step=is_multi_step,
            sub_intents=sub_intents,
            output_format=extracted.get('output_preferences', {}).get('format', 'table'),
            limit=extracted.get('output_preferences', {}).get('limit'),
            ambiguities=extracted.get('ambiguities', []),
            original_query=query,
            normalized_query=query.strip().lower(),
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            sorting={
                "sort_by": extracted.get('output_preferences', {}).get('sort_by'),
                "group_by": extracted.get('output_preferences', {}).get('group_by')
            } if extracted.get('output_preferences', {}).get('sort_by') or extracted.get('output_preferences', {}).get('group_by') else None,
            extracted_entities={
                "additional_services": extracted.get('additional_services', []),
                "execution_plan": [extracted.get('execution_plan', {})],
                "data_flow": [extracted.get('data_flow', {})],
                "time_range": [extracted.get('time_range', {})],
                "cost_filters": [extracted.get('cost_filters', {})],
                "assumptions": extracted.get('assumptions', [])
            }
        )
        

class IntentExtractionPipeline:
    """Orchestrates the entire intent extraction process"""
    
    def __init__(self, bedrock_runtime_client):
        self.simple_extractor = IntentExtractor(bedrock_runtime_client)
    
    def _create_error_intent(
        self, 
        query: str, 
        error: str, 
        start_time: datetime.datetime
    ) -> ExtractedIntent:
        """Create a safe error intent when extraction fails completely"""
        
        return ExtractedIntent(
            query_type="error",
            operation=OperationType.READ,
            confidence=ConfidenceLevel.LOW,
            primary_service="unknown",
            primary_resource=AWSResource(service="unknown", resource_type="unknown"),
            action="",
            regions=[],
            ambiguities=[f"Failed to extract intent: {error}"],
            clarifying_questions=[
                "I couldn't understand that query. Could you rephrase it?",
                "Try something like: 'show me expensive EC2 instances' or 'list S3 buckets with high storage costs'"
            ],
            original_query=query,
            normalized_query=query.strip().lower(),
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            processing_time_ms=(
                datetime.datetime.now(datetime.timezone.utc) - start_time
            ).total_seconds() * 1000
        )
    
    def extract_intent(self, query: str, context: Optional[Dict] = None) -> ExtractedIntent:
        """Main extraction pipeline"""
        
        start_time = datetime.datetime.now(datetime.timezone.utc)
        intent = None
        
        logger.info(f"Extracting intent for query: '{query}'")
            
        # Go straight to extraction
        intent = self.simple_extractor.extract(query)
        
        # Add processing time
        intent.processing_time_ms = (
            datetime.datetime.now(datetime.timezone.utc) - start_time
        ).total_seconds() * 1000
        
        # Enhanced logging
        if intent.is_multi_step:
            services = [intent.primary_service] + intent.extracted_entities.get('additional_services', [])
            logger.info(
                f"✅ Multi-step intent: services={services}, "
                f"steps={len(intent.sub_intents)}, "
                f"operation={intent.operation.value}, "
                f"confidence={intent.confidence.value}, "
                f"time={intent.processing_time_ms:.0f}ms"
            )
            
            # Log each step
            for sub in intent.sub_intents:
                depends = f"depends on {sub.depends_on}" if sub.depends_on else "independent"
                logger.info(f"   Step {sub.step_number}: {sub.resource.service}.{sub.resource.resource_type}.{sub.operation} - {sub.description} ({depends})")
        else:
            logger.info(
                f"✅ Simple intent: service={intent.primary_service}, "
                f"operation={intent.operation.value}, "
                f"confidence={intent.confidence.value}, "
                f"time={intent.processing_time_ms:.0f}ms"
            )
        
        # Check if we should proceed based on confidence
        if intent.confidence == ConfidenceLevel.LOW:
            logger.warning(f"⚠️  Low confidence intent. Ambiguities: {intent.ambiguities}")
        
        return intent
        
if __name__ == "__main__":

    load_dotenv(dotenv_path="../.env")
    bedrock_client = boto3.client('bedrock-runtime', region_name=os.getenv('AWS_REGION'))

    pipeline = IntentExtractionPipeline(bedrock_client)
    
    while test_query := input("How can I help you today?\n> "):
        
        if test_query.lower() in ['exit', 'quit']:
            print("Goodbye!")
            sys.exit(0)
        
        intent = pipeline.extract_intent(test_query)
        print(json.dumps(intent.model_dump(), indent=4))
