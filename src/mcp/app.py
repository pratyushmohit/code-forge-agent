import uvicorn
from fastmcp import FastMCP
from src.mcp.schema import get_condensed_service_schema
from src.mcp.auth import get_temporary_credentials

mcp = FastMCP("aws-mcp")


@mcp.tool()
def get_service_schema(service_name: str) -> dict:
    """
    Returns a condensed botocore service model for the given AWS service.
    Includes all operation names and their top-level input parameter names and types.
    Use this before writing boto3 code to get exact operation signatures.
    """
    return get_condensed_service_schema(service_name)


@mcp.tool()
def get_temp_credentials(duration_seconds: int = 3600) -> dict:
    """
    Returns short-lived AWS STS credentials.
    Use these to build a boto3.Session for code execution.
    Credentials expire after duration_seconds (default 1 hour).
    """
    return get_temporary_credentials(duration_seconds)


app = mcp.http_app(path="/mcp", stateless_http=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
