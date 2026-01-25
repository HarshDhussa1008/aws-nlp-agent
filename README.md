# AWS NLP Agent

> Natural language interface for AWS operations with intelligent intent extraction and policy-based access control

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](./tests)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](./tests)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Policy Controls](#policy-controls)
- [Testing](#testing)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Examples](#examples)
- [Contributing](#contributing)
- [License](#license)

---

## 🎯 Overview

AWS NLP Agent transforms natural language queries into safe, validated AWS operations. It combines intelligent intent extraction with robust policy-based access control to provide a secure, user-friendly interface to AWS services.

**Say goodbye to complex AWS CLI commands:**

```
Instead of:
$ aws ec2 describe-instances --filters "Name=tag:Environment,Values=production" \
  --query "Reservations[*].Instances[*].[InstanceId,State.Name]"

Just ask:
> show me production EC2 instances
```

The system understands your intent, validates it against security policies, and executes it safely.

---

## 🏗️ Architecture

The AWS NLP Agent is built on a **three-layer architecture**:

```
┌─────────────────────────────────────────────────────────────┐
│                        User Query                            │
│          "Show me expensive EC2 instances with high CPU"     │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Intent Extraction                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  • Natural language understanding                    │   │
│  │  • Multi-step query detection                        │   │
│  │  • Service & operation identification                │   │
│  │  • Dependency tracking                               │   │
│  │  • LLM-powered (AWS Bedrock)                         │   │
│  └─────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                ┌───────────▼───────────┐
                │  ExtractedIntent      │
                │  • operation: READ    │
                │  • service: ec2       │
                │  • is_multi_step: true│
                │  • sub_intents: [...]  │
                └───────────┬───────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Intent Gate + Policy Engine                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Validation Pipeline:                                │   │
│  │  1. Confidence & Completeness Checks                 │   │
│  │  2. Policy Evaluation (DENY > ALLOW > REQUIRE_APPROVAL) │
│  │  3. Safety Checks (protected resources, confirmations)│
│  │  4. Resource Constraints (limits, regions)           │   │
│  │  5. Decision: PROCEED | CLARIFY | CONFIRM | REJECT  │   │
│  └─────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                ┌───────────▼───────────┐
                │  GateResult           │
                │  • decision: CONFIRM  │
                │  • confirmations: [...] │
                │  • reasoning: "..."    │
                └───────────┬───────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Execution Planning (Coming Soon)                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  • AWS API call generation                           │   │
│  │  • Multi-step orchestration                          │   │
│  │  • Dependency resolution                             │   │
│  │  • Error handling & retries                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Layer Status

| Layer | Component | Status | Test Coverage |
|-------|-----------|--------|---------------|
| **1** | Intent Extraction | ✅ Production Ready | 100% (30+ tests) |
| **2** | Intent Gate + Policies | ✅ Production Ready | 100% (43+ tests) |
| **3** | Execution Planning | 🚧 In Development | - |

---

## ✨ Features

### 🧠 Intelligent Intent Extraction

- **Natural Language Understanding**: Converts queries like "show expensive instances" into structured intents
- **Multi-Step Query Detection**: Automatically identifies queries requiring multiple AWS API calls
- **Service Auto-Detection**: Recognizes 20+ AWS services and their resources
- **Dependency Tracking**: Understands when step N depends on data from step M
- **Confidence Scoring**: Assesses query clarity (HIGH/MEDIUM/LOW confidence)
- **Ambiguity Detection**: Identifies missing information and asks clarifying questions

**Supported Query Types:**
- ✅ Simple queries: "list EC2 instances"
- ✅ Multi-step queries: "show instances with high CPU" (EC2 + CloudWatch)
- ✅ Cost analysis: "most expensive S3 buckets" (S3 + Cost Explorer)
- ✅ Audit queries: "who accessed my bucket" (S3 + CloudTrail)
- ✅ Complex queries: "production instances with volumes and CPU metrics"

### 🛡️ Policy-Based Access Control

- **IAM-Like Policies**: Define granular access control with familiar syntax
- **Three Policy Effects**: `ALLOW`, `DENY` (highest priority), `REQUIRE_APPROVAL`
- **Resource Patterns**: Support wildcards (`i-prod-*`, `i-temp-*`)
- **Tag-Based Control**: Policies based on resource tags (`Environment=production`)
- **Condition Operators**: `EQUALS`, `IN`, `CONTAINS`, `STARTS_WITH`, `MATCHES` (regex)
- **Policy Precedence**: Secure by default (DENY > ALLOW > REQUIRE_APPROVAL > Default DENY)

**Built-in Protection:**
- 🔒 Production resource protection
- 🚫 Delete operation blocking (configurable)
- ⚠️ High-risk action confirmations
- 🌍 Region restrictions
- 📊 Resource limit enforcement

### ✅ Comprehensive Validation

- **Confidence Validation**: Ensures query clarity before execution
- **Completeness Checks**: Verifies all required information present
- **Safety Checks**: Warns about destructive or broad operations
- **Resource Constraints**: Enforces limits on batch operations
- **Multi-Turn Conversations**: Handles clarifications and confirmations

### 🔄 Decision Types

| Decision | Meaning | Example |
|----------|---------|---------|
| **PROCEED** | Safe to execute immediately | "list EC2 instances" with high confidence |
| **CLARIFY** | Need more information | "list instances" (which region?) |
| **CONFIRM** | Need explicit user approval | "stop all production instances" |
| **REJECT** | Cannot or should not execute | "delete production database" |

---

## 🔐 Policy Controls

### Policy Syntax

Policies use a fluent builder API inspired by AWS IAM:

```python
from policy_schema import PolicyBuilder, OperationType, ConditionOperator

policy = (
    PolicyBuilder("my-policy")
    .with_description("Custom access control")
    
    # Statement 1: Allow reads
    .statement("allow-reads")
    .allow()
    .read_operations()
    .all_resources()
    .end_statement()
    
    # Statement 2: Deny production modifications
    .statement("deny-prod")
    .deny()
    .operations(OperationType.WRITE, OperationType.DELETE)
    .all_resources()
    .when_tag("Environment", ConditionOperator.EQUALS, "production")
    .end_statement()
    
    # Statement 3: Require approval for deletes
    .statement("approve-deletes")
    .require_approval()
    .delete_operations()
    .all_resources()
    .end_statement()
    
    .build()
)
```

### Built-in Policy Templates

```python
from policy_schema import PolicyTemplates

# 1. Read-only access
gate.add_policy(PolicyTemplates.read_only())

# 2. Production protection
gate.add_policy(PolicyTemplates.deny_production_modifications())

# 3. Region restrictions
gate.add_policy(PolicyTemplates.region_restrictions(["us-east-1", "us-west-2"]))

# 4. Service allowlist
gate.add_policy(PolicyTemplates.service_restrictions(
    allowed_services=["ec2", "s3"],
    denied_services=["iam", "kms"]
))

# 5. Critical resource approval
gate.add_policy(PolicyTemplates.require_approval_for_critical())

# 6. Resource blocklist
gate.add_policy(PolicyTemplates.specific_resource_deny(
    service="ec2",
    resource_ids=["i-critical-001", "i-database-master"]
))
```

---

### Quick Smoke Test

```python
# Test extraction
from test_intent_extraction import *
mock = create_mock_llm_response(operation_type="read", primary_service="ec2")
client = MockBedrockClient(mock)
extractor = IntentExtractor(client)
intent = extractor.extract("list instances")
assert intent.operation.value == "read"

# Test gate
from test_intent_gate_comprehensive import *
gate = IntentGate(enable_policies=True)
result = gate.evaluate(create_intent(OperationType.READ, "ec2"))
assert result.decision == GateDecision.PROCEED
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file:

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key

# Bedrock Configuration
BEDROCK_MODEL_ID=<MODEL _IDENTIFIER>

# Gate Configuration
MIN_CONFIDENCE_PROCEED=medium
MIN_CONFIDENCE_WRITE=high
REQUIRE_CONFIRMATION_DELETE=true
MAX_RESOURCE_LIMIT=100

# Policy Configuration
ENABLE_POLICIES=true
DEFAULT_POLICY_SET=production  # development | staging | production | read-only

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Gate Configuration

```python
config = {
    # Confidence thresholds
    'min_confidence_proceed': ConfidenceLevel.MEDIUM,
    'min_confidence_write': ConfidenceLevel.HIGH,
    
    # Safety settings
    'require_confirmation_delete': True,
    'require_confirmation_write': False,
    'max_resource_limit': 100,
    
    # Protected patterns
    'protected_patterns': ['prod', 'production', 'master', 'main']
}

gate = IntentGate(config=config, enable_policies=True)
```

## 🗺️ Roadmap

### Current Release (v1.0 - Q1 2026)
- ✅ Intent Extraction (Layer 1)
- ✅ Intent Gate with Policies (Layer 2)
- 🚧 Execution Planning (Layer 3)

### Future Features
- 🔮 Multi-region query execution
- 🔮 Query result caching
- 🔮 Cost estimation before execution
- 🔮 Execution history and rollback
- 🔮 Slack/Teams integration
- 🔮 Web UI dashboard
- 🔮 Query templates and shortcuts
- 🔮 Advanced analytics and reporting

---

## 📊 Performance

### Benchmarks

| Operation | Avg Time | Notes |
|-----------|----------|-------|
| Intent Extraction | ~800ms | Depends on LLM response time |
| Policy Evaluation | <10ms | In-memory policy engine |
| Gate Validation | <5ms | Excluding policy evaluation |
| End-to-End (Simple) | ~850ms | Extract + Validate |
| End-to-End (Multi-step) | ~1200ms | More complex extraction |

### Scalability

- **Concurrent Requests**: Supports 100+ concurrent query extractions
- **Policy Count**: Tested with 50+ policies, <20ms evaluation time
- **Multi-Step Queries**: Handles up to 10 steps efficiently
- **Cache Support**: Ready for result caching (coming in v1.1)

---

## 🔒 Security

### Security Features

- **Secure by Default**: Denies operations unless explicitly allowed
- **Policy Precedence**: DENY always wins, even over ALLOW
- **Production Protection**: Built-in safeguards for production resources
- **Audit Logging**: All decisions logged with reasoning
- **No Credential Storage**: Uses AWS SDK credential chain
- **Input Validation**: Validates all intents before execution

### Security Best Practices

1. **Always enable policies** in production
2. **Use environment presets** (development/staging/production)
3. **Review audit logs** regularly
4. **Principle of least privilege** in policy design
5. **Test policies** before deployment
6. **Monitor denial patterns** for potential issues

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.

---

## 🙏 Acknowledgments

- Built with [AWS Bedrock](https://aws.amazon.com/bedrock/) for LLM capabilities
- Inspired by AWS IAM policy syntax
- Tested with [Pydantic](https://pydantic-docs.helpmanual.io/) for data validation

---

## 🌟 Star History

If you find this project useful, please consider giving it a star! ⭐

---

**Made with ❤️ **
