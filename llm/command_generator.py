"""
Command Generator - Second LLM for generating AWS CLI commands.

Takes a validated intent and generates specific AWS CLI commands.
Uses strands Agent with a focused system prompt for CLI command generation.

The command generator is policy-aware: it generates different types of commands
based on the resolved capability (read-only vs write vs delete operations).
"""

import re
from dotenv import load_dotenv
from strands import Agent
from llm.intent_schema import StateQueryIntent

load_dotenv(dotenv_path="../.env")


# Base system prompt template - will be customized based on capability
COMMAND_GENERATOR_BASE_PROMPT = """
You are an AWS CLI command generator. Your job is to generate VALID AWS CLI commands from user intent.

Given an intent with service, region, and operation, generate the appropriate AWS CLI command.

CRITICAL RULES:
1. Return ONLY the AWS CLI command, nothing else
2. Always include --region flag with the region
3. Use --output json for parseable results
4. {operation_restrictions}
5. For large result sets, include --max-items if appropriate
6. Do NOT include any explanations, markdown, or surrounding text

COMMAND STRUCTURE: aws <service> <operation> --region <region> --output json [--options]

SERVICE-SPECIFIC EXAMPLES:

EC2 Examples:
Intent: {{service: "ec2", region: "us-east-1", operation: "list"}}
Output: aws ec2 describe-instances --region us-east-1 --output json

Intent: {{service: "ec2", region: "us-west-2", operation: "describe"}}
Output: aws ec2 describe-security-groups --region us-west-2 --output json

S3 Examples:
Intent: {{service: "s3", region: "us-west-2", operation: "list"}}
Output: aws s3 list-buckets --region us-west-2 --output json

Intent: {{service: "s3", region: "us-east-1", operation: "get"}}
Output: aws s3api head-bucket --bucket <bucket-name> --region us-east-1 --output json

RDS Examples:
Intent: {{service: "rds", region: "eu-west-1", operation: "describe"}}
Output: aws rds describe-db-instances --region eu-west-1 --output json

Intent: {{service: "rds", region: "us-east-1", operation: "list"}}
Output: aws rds describe-db-snapshots --region us-east-1 --output json

Lambda Examples:
Intent: {{service: "lambda", region: "us-east-1", operation: "list"}}
Output: aws lambda list-functions --region us-east-1 --output json

Intent: {{service: "lambda", region: "us-west-2", operation: "describe"}}
Output: aws lambda get-function --function-name <function-name> --region us-west-2 --output json

EKS Examples:
Intent: {{service: "eks", region: "us-east-1", operation: "list"}}
Output: aws eks list-clusters --region us-east-1 --output json

Intent: {{service: "eks", region: "eu-west-1", operation: "describe"}}
Output: aws eks describe-cluster --name <cluster-name> --region eu-west-1 --output json

IAM Examples:
Intent: {{service: "iam", region: "us-east-1", operation: "list"}}
Output: aws iam list-users --region us-east-1 --output json

Intent: {{service: "iam", region: "us-east-1", operation: "get"}}
Output: aws iam get-user --user-name <username> --region us-east-1 --output json

CloudWatch Examples:
Intent: {{service: "cloudwatch", region: "us-east-1", operation: "describe"}}
Output: aws cloudwatch describe-alarms --region us-east-1 --output json

Intent: {{service: "cloudwatch", region: "us-west-2", operation: "get"}}
Output: aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --region us-west-2 --output json

DynamoDB Examples:
Intent: {{service: "dynamodb", region: "us-east-1", operation: "list"}}
Output: aws dynamodb list-tables --region us-east-1 --output json

Intent: {{service: "dynamodb", region: "us-west-2", operation: "describe"}}
Output: aws dynamodb describe-table --table-name <table-name> --region us-west-2 --output json

IMPORTANT NOTES:
- For services like S3 that require resource names, use placeholder syntax: <resource-name>, <bucket-name>, <table-name>, etc.
- Always map intent operations to actual AWS CLI operations (e.g., "list" → "describe-instances" for EC2)
- Use service-specific command names (e.g., "s3api" for some S3 operations)
- The command MUST be executable by AWS CLI
- Return ONLY the command line, no quotes, no markdown, no explanation

RETURN FORMAT: Single line AWS CLI command starting with "aws"
"""


class CommandGenerator:
    """
    LLM-based AWS CLI command generator (LLM 2).

    Takes a validated StateQueryIntent and generates a specific AWS CLI command.
    Is policy-aware: generates different types of commands based on capability.
    """

    def __init__(self):
        """Initialize Command Generator with strands Agent."""
        # Start with read-only mode by default (most restrictive)
        self.agent = None
        self.current_capability = None

    def _get_system_prompt(self, capability: str = None) -> str:
        """
        Get the system prompt based on the capability type.

        Args:
            capability: Capability name (e.g., "EC2.Modify", "EC2.Destructive", "Lambda.Invoke")
                       If None, defaults to read-only mode

        Returns:
            Customized system prompt for the capability type
        """
        # Determine operation restrictions based on capability
        if capability is None:
            # Default: read-only mode (most restrictive)
            operation_restrictions = "ONLY read-only operations (list, describe, get, head, show, query, scan, read). NO write or delete operations."
        elif "Invoke" in capability or "Modify" in capability:
            # Write operations allowed (start, stop, modify, invoke, update, put, create)
            operation_restrictions = "Can include write operations (start, stop, reboot, create, update, modify, invoke, put, batch-write) as needed for the capability."
        elif "Destructive" in capability:
            # Destructive operations allowed (delete, terminate, remove)
            operation_restrictions = "Can include destructive operations (delete, terminate, remove, drop) as needed for the capability."
        else:
            # Default to read-only for unknown capabilities
            operation_restrictions = "ONLY read-only operations (list, describe, get, head, show, query, scan, read). NO write or delete operations."

        base_prompt = COMMAND_GENERATOR_BASE_PROMPT.format(
            operation_restrictions=operation_restrictions
        )

        return base_prompt + """

SERVICE-SPECIFIC EXAMPLES:

EC2 Examples:
Intent: {{service: "ec2", region: "us-east-1", operation: "describe"}}
Output: aws ec2 describe-instances --region us-east-1 --output json

Intent: {{service: "ec2", region: "us-east-1", operation: "start"}}
Output: aws ec2 start-instances --instance-ids <instance-id> --region us-east-1 --output json

Intent: {{service: "ec2", region: "us-east-1", operation: "stop"}}
Output: aws ec2 stop-instances --instance-ids <instance-id> --region us-east-1 --output json

Intent: {{service: "ec2", region: "us-east-1", operation: "terminate"}}
Output: aws ec2 terminate-instances --instance-ids <instance-id> --region us-east-1 --output json

S3 Examples:
Intent: {{service: "s3", region: "us-west-2", operation: "list"}}
Output: aws s3 list-buckets --region us-west-2 --output json

Intent: {{service: "s3", region: "us-east-1", operation: "get"}}
Output: aws s3api head-bucket --bucket <bucket-name> --region us-east-1 --output json

RDS Examples:
Intent: {{service: "rds", region: "eu-west-1", operation: "describe"}}
Output: aws rds describe-db-instances --region eu-west-1 --output json

Intent: {{service: "rds", region: "us-east-1", operation: "stop"}}
Output: aws rds stop-db-instance --db-instance-identifier <db-instance-id> --region us-east-1 --output json

Lambda Examples:
Intent: {{service: "lambda", region: "us-east-1", operation: "list"}}
Output: aws lambda list-functions --region us-east-1 --output json

Intent: {{service: "lambda", region: "us-west-2", operation: "invoke"}}
Output: aws lambda invoke --function-name <function-name> --region us-west-2 /tmp/output.json

DynamoDB Examples:
Intent: {{service: "dynamodb", region: "us-east-1", operation: "list"}}
Output: aws dynamodb list-tables --region us-east-1 --output json

Intent: {{service: "dynamodb", region: "us-west-2", operation: "delete"}}
Output: aws dynamodb delete-table --table-name <table-name> --region us-west-2 --output json

IMPORTANT NOTES:
- For services requiring resource names, use placeholder syntax: <resource-name>, <bucket-name>, <table-name>, <instance-id>, etc.
- Always map intent operations to actual AWS CLI operations (e.g., "list" → "describe-instances" for EC2, "start" → "start-instances")
- Use service-specific command names (e.g., "s3api" for some S3 operations)
- The command MUST be executable by AWS CLI
- Return ONLY the command line, no quotes, no markdown, no explanation

RETURN FORMAT: Single line AWS CLI command starting with "aws"
"""

    def generate(self, intent: StateQueryIntent, capability: str = None) -> str:
        """
        Generate AWS CLI command from validated intent and capability.

        Args:
            intent: Validated StateQueryIntent with service, region, operation
            capability: Optional capability name (e.g., "EC2.Modify", "EC2.Destructive")
                       Determines what types of operations are allowed

        Returns:
            AWS CLI command string (e.g., "aws ec2 start-instances --instance-ids i-123 --region us-east-1 --output json")

        Raises:
            ValueError: If command generation fails or result is invalid
        """
        # Update agent if capability changed
        if capability != self.current_capability:
            self.current_capability = capability
            system_prompt = self._get_system_prompt(capability)
            self.agent = Agent(system_prompt=system_prompt)

        # Format intent as JSON-like prompt for clarity
        prompt = f"""Generate AWS CLI command for this intent:
Service: {intent.service}
Region: {intent.region}
Operation: {intent.operation}
Resource Hint: {intent.resource_hint if hasattr(intent, 'resource_hint') and intent.resource_hint else 'N/A'}

Return ONLY the command."""

        try:
            # Call LLM to generate command
            raw_command = self.agent(prompt)

            # Clean up response to extract pure command
            command = self._clean_command(str(raw_command))

            # Validate command format
            if not command.startswith('aws '):
                raise ValueError(f"Generated command does not start with 'aws': {command}")

            return command

        except Exception as e:
            raise ValueError(f"Command generation failed: {str(e)}") from e

    def _clean_command(self, raw: str) -> str:
        """
        Clean up LLM output to extract pure AWS CLI command.

        Handles:
        - Markdown code blocks (```bash, ```)
        - Surrounding quotes
        - Extra whitespace
        - Multiple lines (takes first line)

        Args:
            raw: Raw LLM output

        Returns:
            Cleaned command string
        """
        # Remove markdown code blocks
        raw = re.sub(r'```bash\n?', '', raw)
        raw = re.sub(r'```\n?', '', raw)
        raw = re.sub(r'```', '', raw)

        # Remove surrounding quotes
        raw = raw.strip().strip('"').strip("'")

        # Get first non-empty line
        for line in raw.split('\n'):
            line = line.strip()
            if line:
                return line

        raise ValueError("No command found in LLM output")
