"""
AWS NLP Agent Handler

Flow:
    User Query
    → Intent Extraction (LLM 1)
    → Intent Gate (Permission Check)
    → Command Generation (LLM 2)
    → MCP Execution
    → Response
"""

import ast
from dataclasses import asdict
import json
import time
import os
import boto3
from dotenv import load_dotenv
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters
from strands import Agent,tool
from llm.intent_extractor import IntentExtractionPipeline
from policy.intent_gate import IntentGate
from llm.intent_schema import ExtractedIntent
from logging import Logger
import logging

# Rich imports for beautiful CLI
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.live import Live
    from rich.layout import Layout
    from rich import box
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("⚠️  Install 'rich' for better formatting: pip install rich")

load_dotenv(dotenv_path="../.env")

# Initialize Rich console
console = Console(stderr=True) if RICH_AVAILABLE else None

# Configure logging to be less verbose
logging.basicConfig(
    level=logging.WARNING,  # Changed from INFO to WARNING
    format='%(message)s'
)

for logger_name in [
    'llm.intent_extractor',      # ← Your extractors
    'policy.intent_gate',         # ← Your gate
    'policy.policy_engine',       # ← Your policies
    'botocore',                   # ← AWS SDK
    'boto3',                      # ← AWS SDK
    'urllib3',                    # ← HTTP library
    'strands',                    # ← Agent framework
    'strands.telemetry',
    'strands.telemetry.metrics',
]:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.CRITICAL)  # Only critical errors
    logger.propagate = False  # Don't propagate to parent

SYSTEM_PROMPT = """
You are an AWS assistant that helps users interact with AWS services securely.
Your task is to:
1. Understand the user's natural language query about AWS.
2. Extract the intent and relevant details (service, action, resources) using extract_intent.
3. Check the extracted intent against security policies (via Intent Gate) using evaluate_intent.
4. If the intent is allowed, generate the appropriate AWS CLI command.
5. If the intent is not allowed, inform the user about the policy violation.
6. Execute allowed commands via the MCP client and return the output.
7. Always prioritize security and compliance in your responses.
"""

# Add debugging logs to validate the ExtractedIntent object
@tool
def extract_intent(query: str):
    """Extract intent from simple queries
    
    Args:
        query (str): User query to generate Intent for
    """
    try:
        
        bedrock_client = boto3.client('bedrock-runtime', region_name=os.getenv('AWS_REGION'))
        intent_extractor = IntentExtractionPipeline(bedrock_client)
        extracted_intent = intent_extractor.extract_intent(query)
        
        if RICH_AVAILABLE:
            # Create intent summary table
            table = Table(show_header=False, box=box.ROUNDED, padding=(0, 1))
            table.add_column("Property", style="cyan bold")
            table.add_column("Value", style="white")
            
            table.add_row("🎯 Service", extracted_intent.primary_service)
            table.add_row("⚙️  Operation", extracted_intent.operation.value)
            table.add_row("📊 Confidence", extracted_intent.confidence.value)
            regions = ', '.join(extracted_intent.regions) if extracted_intent.regions else 'default'
            table.add_row("🌍 Regions", regions)
            
            console.print("\n")
            console.print(Panel(
                table, 
                title="[bold green]✅ Intent Extracted[/bold green]", 
                border_style="green"
            ))
        
        # Debugging log
        logging.debug(f"Extracted Intent: {extracted_intent}")
        return extracted_intent.model_dump(mode='json')
    
    except Exception as e:
        return {
            "error": str(e)
        }


@tool
def evaluate_intent(intent):
    """Evaluate the intent against all gate check and policies

    Args:
        intent (ExtractedIntent, dict, or str): extracted intent from extract_intent to check against the policy gate
    """
    try:
        # Debugging log for input type
        logging.debug(f"Received intent for evaluation. Type: {type(intent)}, Content: {intent}")

        # If the intent is a JSON string, deserialize it into a dictionary
        if isinstance(intent, str):
            try:
                intent = ast.literal_eval(intent)  # Safely evaluate string to dict
            except json.JSONDecodeError as e:
                logging.error(f"Failed to decode JSON string: {str(e)}")
                return {
                    "error": "Invalid JSON string. Could not deserialize intent."
                }

        # If the intent is a dictionary, deserialize it into an ExtractedIntent object
        if isinstance(intent, dict):
            intent = ExtractedIntent(**intent)

        # Debugging log
        logging.debug(f"Evaluating Intent: {intent}")
        
        gate = IntentGate(
            enable_policies=True
        )
        result = gate.evaluate(intent)
        
        if RICH_AVAILABLE:
            decision = result.decision.value
            reasoning = result.reasoning
            
            if decision == 'proceed':
                style = "green"
                icon = "✅"
                title = "Security Check: PASSED"
            elif decision == 'confirm':
                style = "yellow"
                icon = "⚠️"
                title = "Confirmation Required"
            elif decision == 'clarify':
                style = "yellow"
                icon = "❓"
                title = "Clarification Needed"
            else:
                style = "red"
                icon = "❌"
                title = "Security Check: DENIED"
            
            message = f"[{style}]{icon} {reasoning}[/{style}]"
            
            console.print("\n")
            console.print(Panel(
                message, 
                title=f"[bold {style}]{title}[/bold {style}]", 
                border_style=style
            ))
            
            # Print warnings if any
            if result.warnings:
                console.print("\n[yellow]⚠️  Warnings:[/yellow]")
                for warning in result.warnings:
                    console.print(f"  • {warning}")
            
            # Print required confirmations if any
            if result.required_confirmations:
                console.print("\n[yellow]🔒 Confirmations Required:[/yellow]")
                for conf in result.required_confirmations:
                    console.print(f"  • {conf}")
        
        # Debugging log
        logging.debug(f"Evaluation Result: {result}")
        return asdict(result)
    except Exception as e:
        logging.error(f"Error during intent evaluation: {str(e)}")
        return {
            "error": str(e)
        }


class Handler:
    """
    Main orchestration handler for AWS NLP Agent with security pipeline.

    Implements multi-stage pipeline with security gates and validation.
    """

    def __init__(self):
        """
        Initialize Handler with all required components.

        Stages:
        1. MCP Client - Connect to AWS
        2. Intent Extractor - LLM 1 for intent extraction
        3. Command Generator - LLM 2 for CLI command generation
        4. Security Components - Intent Gate and Command Validator
        5. Execution Control - DryRun and Approval
        6. Agent - MCP-based executor
        7. Audit Logger - Log all executions
        """
        try:
            
            logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            self.structured_logger = Logger("aws_nlp_agent_handler")
            self.structured_logger.setLevel(logging.DEBUG)
            
            self.client = MCPClient(
                lambda: stdio_client(StdioServerParameters(
                    command="uvx",
                    args=["awslabs.aws-api-mcp-server@latest"]
                ))
            )
            self.client.start()
            
            aws_tools = self.client.list_tools_sync()
            self.tool_list = [
                extract_intent,
                evaluate_intent
            ]
            self.tool_list.extend(aws_tools)
            self.agent = Agent(
                system_prompt=SYSTEM_PROMPT,
                tools=self.tool_list
            )

        except Exception as e:
            if RICH_AVAILABLE:
                console.print(f"[bold red]❌ Failed to initialize:[/bold red] {str(e)}")
            else:
                print(f"❌ Failed to initialize: {str(e)}")
            raise RuntimeError(f"Failed to initialize handler: {str(e)}") from e

    def list_tools(self):
        """List available AWS MCP tools."""
        try:
            self.structured_logger.info(f"mcp_tools_discovered: {self.tool_list}")
        except Exception as e:
            self.structured_logger.error("mcp_tools_discovery_failed")

    def _print_header(self):
        """Print beautiful header"""
        if not RICH_AVAILABLE:
            print("\n" + "="*60)
            print("AWS NLP Agent - Interactive Mode")
            print("="*60 + "\n")
            return
        
        header = Panel.fit(
            "[bold cyan]AWS NLP Agent[/bold cyan]\n"
            "[dim]Natural Language Interface for AWS Operations[/dim]\n\n"
            "[yellow]Type your AWS queries in plain English[/yellow]\n"
            "[dim]Example: 'list my EC2 instances' or 'show S3 buckets'[/dim]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(header)

    def _print_intent_summary(self, intent_data: dict):
        """Print intent extraction summary"""
        if not RICH_AVAILABLE:
            return
        
        # Create a summary table
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        
        table.add_row("🎯 Service", intent_data.get('primary_service', 'unknown'))
        table.add_row("⚙️  Operation", intent_data.get('operation', 'unknown'))
        table.add_row("📊 Confidence", intent_data.get('confidence', 'unknown'))
        table.add_row("🌍 Region", ', '.join(intent_data.get('regions', [])) or 'default')
        
        console.print("\n")
        console.print(Panel(table, title="[bold green]✅ Intent Extracted[/bold green]", border_style="green"))

    def _print_gate_result(self, gate_result: dict):
        """Print gate evaluation result"""
        if not RICH_AVAILABLE:
            return
        
        decision = gate_result.get('decision', 'unknown')
        reasoning = gate_result.get('reasoning', '')
        
        if decision == 'proceed':
            style = "green"
            icon = "✅"
            title = "Security Check: PASSED"
        elif decision == 'confirm':
            style = "yellow"
            icon = "⚠️"
            title = "Confirmation Required"
        elif decision == 'clarify':
            style = "yellow"
            icon = "❓"
            title = "Clarification Needed"
        else:
            style = "red"
            icon = "❌"
            title = "Security Check: DENIED"
        
        message = f"[{style}]{icon} {reasoning}[/{style}]"
        
        console.print(Panel(message, title=f"[bold {style}]{title}[/bold {style}]", border_style=style))
        
        # Print any warnings or confirmations
        if gate_result.get('warnings'):
            console.print("\n[yellow]⚠️  Warnings:[/yellow]")
            for warning in gate_result['warnings']:
                console.print(f"  • {warning}")
        
        if gate_result.get('required_confirmations'):
            console.print("\n[yellow]🔒 Confirmations Required:[/yellow]")
            for conf in gate_result['required_confirmations']:
                console.print(f"  • {conf}")
    
    def run(
        self, user_query: str
    ) -> dict:
        """
        Execute user query through complete security pipeline with execution control.

        Pipeline:
        1. Extract intent from natural language (LLM 1)
        2. Validate intent against security policy (Intent Gate with PolicyEngine)
        3. Generate AWS CLI command from intent (LLM 2)
        6. Execute via MCP client (Agent)
        7. Format and return response
        8. Log execution to audit trail

        Args:
            user_query: Natural language user query
        Returns:
            Dictionary with success status, intent, command and response
        """
        
        # Initialize audit record
        start_time = time.time()
        
        if RICH_AVAILABLE:
            console.print(f"\n[bold]Query:[/bold] [cyan]{user_query}[/cyan]\n")

            with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                    transient=True
                ) as progress:
                
                progress.add_task("Processing...", total=None)
                try:
                    
                    import sys
                    from io import StringIO
                    
                    # Capture stdout
                    old_stdout = sys.stdout
                    sys.stdout = StringIO()
                    
                    result = self.agent(user_query)
                    return {
                        "success": True,
                        "result": result
                    }
                except Exception as e:
                    console.print(f"\n[bold red]❌ Error:[/bold red] {str(e)}")
                    return {
                        "success": False,
                        "error": "execution_failed",
                        "message": str(e),
                    }
                finally:
                    end_time = time.time()
                    duration = end_time - start_time
                    console.print(f"[green]✅ Query execution completed in {duration:.2f} seconds[/green]")
                    sys.stdout = old_stdout

        else:
            self.structured_logger.info(f"query_received : {user_query}")
            try:
                
                import sys
                from io import StringIO
                
                old_stdout = sys.stdout
                sys.stdout = StringIO()
                
                result = self.agent(user_query)
                return {
                    "success": True,
                    "result": result
                }
            except Exception as e:
                print(f"\n❌ Error: {str(e)}")
                import traceback
                traceback.print_exc()
                return {
                    "success": False,
                    "error": "execution_failed",
                    "message": str(e),
                }
            finally:
                end_time = time.time()
                duration = end_time - start_time
                self.structured_logger.info(f"query_execution_completed in {duration:.2f} seconds")
                sys.stdout = old_stdout
    
    def run_interactive(self):
        """Run handler in interactive mode for testing."""
        
        self._print_header()
        
        while True:
            try:
                if RICH_AVAILABLE:
                    query = console.input("\n[bold green]AWS>[/bold green] ").strip()
                else:
                    query = input("\nAWS> ").strip()
                
                if query.lower() in ['quit', 'exit', 'q']:
                    if RICH_AVAILABLE:
                        console.print("\n[cyan]👋 Goodbye![/cyan]\n")
                    else:
                        print("\n👋 Goodbye!\n")
                    break

                if not query:
                    continue

                # Execute query
                result = self.run(query)
                
                # Print result
                if result['success']:
                    agent_result = result['result']
                    
                    # Extract the final message
                    if hasattr(agent_result, 'message') and 'content' in agent_result.message:
                        content = agent_result.message['content']
                        if content and len(content) > 0:
                            final_text = content[0].get('text', '')
                            
                            if RICH_AVAILABLE:
                                # Render as markdown for beautiful formatting
                                console.print("\n")
                                console.print(Panel(
                                    Markdown(final_text),
                                    title="[bold cyan]📋 Results[/bold cyan]",
                                    border_style="cyan",
                                    padding=(1, 2)
                                ))
                            else:
                                print(f"\n{final_text}\n")
                else:
                    if RICH_AVAILABLE:
                        console.print(f"[bold red]Error:[/bold red] {result.get('error', 'Unknown error')}")
                    else:
                        print(f"Error: {result.get('error', 'Unknown error')}")

            except KeyboardInterrupt:
                if RICH_AVAILABLE:
                    console.print("\n\n[cyan]👋 Interrupted. Goodbye![/cyan]\n")
                else:
                    print("\n\n👋 Interrupted. Goodbye!\n")
                break
            except Exception as e:
                if RICH_AVAILABLE:
                    console.print(f"\n[bold red]❌ Error:[/bold red] {str(e)}\n")
                else:
                    print(f"\n❌ Error: {str(e)}\n")


if __name__ == "__main__":
    handler = Handler()
    # Example usage (uncomment to test):
    # result = handler.run("List EC2 instances in ap-south-1 region")
    # print(result)

    # Or run interactive mode:
    handler.run_interactive()