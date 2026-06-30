import sys
import os

print("Python executable:", sys.executable)
print("Current working directory:", os.getcwd())

# Test individual imports
try:
    from google.adk.agents import Agent, LlmAgent
    print("✅ google.adk.agents imports OK")
except Exception as e:
    print("❌ google.adk.agents imports FAILED:", e)

try:
    from google.adk.workflow import Workflow, node, START, JoinNode
    print("✅ google.adk.workflow imports OK")
except Exception as e:
    print("❌ google.adk.workflow imports FAILED:", e)

try:
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
    print("✅ MCPToolset import OK")
except Exception as e:
    print("❌ MCPToolset import FAILED:", e)

try:
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    print("✅ StdioConnectionParams import OK")
except Exception as e:
    print("❌ StdioConnectionParams import FAILED:", e)

try:
    from mcp.client.stdio import StdioServerParameters
    print("✅ StdioServerParameters import OK")
except Exception as e:
    print("❌ StdioServerParameters import FAILED:", e)

print("\nAttempting full import of app.agent...")
try:
    import app.agent
    print("✅ Full import of app.agent succeeded!")
except Exception as e:
    print("❌ Full import of app.agent FAILED:")
    import traceback
    traceback.print_exc()
