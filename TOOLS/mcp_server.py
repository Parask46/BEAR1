from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import sys
import os

# Import existing tools from BEAR
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import tool_loader

mcp_server = Server("bear-mcp-server")
schemas, functions = tool_loader.get_all_tools()

@mcp_server.list_tools()
async def list_tools():
    """Exposes all of BEAR's internal tools over MCP."""
    from mcp.types import Tool
    tools = []
    for schema in schemas:
        tools.append(
            Tool(
                name=schema["function"]["name"],
                description=schema["function"].get("description", ""),
                inputSchema=schema["function"].get("parameters", {})
            )
        )
    return tools

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Executes the tool remotely."""
    if name in functions:
        result = functions[name](**arguments)
        return [{"type": "text", "text": str(result)}]
    raise ValueError(f"Tool {name} not found")

async def run():
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(run())