"""
Seafile MCP Server
A Model Context Protocol server for Seafile file operations.

Runs in one of two modes:
  - stdio (default): a local MCP server launched by your MCP client. The
    Seafile token is read from SEAFILE_TOKEN in the environment / .env.
  - http: a hosted MCP server using the Streamable HTTP transport. Each
    client sends its own Seafile token as "Authorization: Bearer <token>",
    so Seafile enforces every user's own permissions.

Author: Setu Kathawate
License: MIT
Repository: https://github.com/setugk/seafile-mcp
"""

import argparse
import logging
import os

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

# Load environment variables
load_dotenv()

SEAFILE_URL = os.getenv("SEAFILE_URL", "").rstrip("/")
SEAFILE_TOKEN = os.getenv("SEAFILE_TOKEN", "")

logger = logging.getLogger("seafile-mcp")

# Set at startup by main(): "stdio" or "http"
TRANSPORT = "stdio"

# Create the MCP server
mcp = MCPServer("Seafile MCP")


class SeafileAuthError(ToolError):
    """Raised when no Seafile token is available for a request."""


def get_token(ctx: Context) -> str:
    """Get the Seafile token for the current request.

    In stdio mode this is SEAFILE_TOKEN from the environment. In http mode it
    is the bearer token sent by the client; the server's own SEAFILE_TOKEN is
    never used, so a public endpoint can't act as the server owner.
    """
    if TRANSPORT == "stdio":
        if not SEAFILE_TOKEN:
            raise SeafileAuthError("SEAFILE_TOKEN is not configured in .env")
        return SEAFILE_TOKEN

    headers = ctx.headers or {}
    auth = headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() not in ("bearer", "token") or not token.strip():
        raise SeafileAuthError(
            "Missing Seafile token. Send it as 'Authorization: Bearer <your-seafile-token>'."
        )
    return token.strip()


def get_headers(ctx: Context) -> dict:
    """Get authorization headers for Seafile API requests."""
    return {
        "Authorization": f"Token {get_token(ctx)}",
        "Accept": "application/json",
    }


async def seafile_request(
    ctx: Context,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    timeout: float = 10.0,
) -> httpx.Response:
    """Make an authenticated request to the Seafile API."""
    if not SEAFILE_URL:
        raise SeafileAuthError("SEAFILE_URL is not configured")
    async with httpx.AsyncClient() as client:
        return await client.request(
            method,
            f"{SEAFILE_URL}{path}",
            headers=get_headers(ctx),
            params=params,
            data=data,
            timeout=timeout,
        )


def error_message(response: httpx.Response) -> str:
    """Format an error from a Seafile API response."""
    if response.status_code in (401, 403) and TRANSPORT == "http":
        return f"Status {response.status_code}: Seafile rejected the token (invalid, expired, or no permission)"
    return f"Status {response.status_code}: {response.text}"


@mcp.tool()
def hello() -> str:
    """A simple test tool to verify MCP is working."""
    return "Hello from MCP! Your server is working correctly."


@mcp.tool()
async def ping_server(ctx: Context) -> str:
    """Test connection to the Seafile server and verify authentication."""
    try:
        response = await seafile_request(ctx, "GET", "/api2/auth/ping/")
        if response.status_code == 200:
            return f"Connected to {SEAFILE_URL} - Authentication successful!"
        return f"Error: {error_message(response)}"
    except SeafileAuthError as e:
        return f"Error: {e}"
    except httpx.ConnectError as e:
        return f"Connection error: Could not reach {SEAFILE_URL} - {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_account_info(ctx: Context) -> dict:
    """Get information about the authenticated Seafile account."""
    response = await seafile_request(ctx, "GET", "/api2/account/info/")
    if response.status_code == 200:
        return response.json()
    return {"error": error_message(response)}


@mcp.tool()
async def list_libraries(ctx: Context) -> list:
    """List all libraries (repos) accessible to the authenticated user."""
    response = await seafile_request(ctx, "GET", "/api2/repos/")
    if response.status_code == 200:
        # Return simplified info for each library
        return [
            {
                "id": lib.get("id"),
                "name": lib.get("name"),
                "size": lib.get("size"),
                "owner": lib.get("owner"),
                "encrypted": lib.get("encrypted"),
            }
            for lib in response.json()
        ]
    return [{"error": error_message(response)}]


@mcp.tool()
async def get_library(ctx: Context, library_id: str) -> dict:
    """Get details of a specific library by ID.

    Args:
        library_id: The ID of the library to retrieve
    """
    response = await seafile_request(ctx, "GET", f"/api2/repos/{library_id}/")
    if response.status_code == 200:
        return response.json()
    return {"error": error_message(response)}


@mcp.tool()
async def list_directory(ctx: Context, library_id: str, path: str = "/") -> list:
    """List contents of a directory in a library.

    Args:
        library_id: The ID of the library
        path: Path within the library (default: root "/")
    """
    response = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/dir/", params={"p": path}
    )
    if response.status_code == 200:
        return [
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "size": item.get("size") if item.get("type") == "file" else None,
                "modified": item.get("mtime"),
            }
            for item in response.json()
        ]
    return [{"error": error_message(response)}]


@mcp.tool()
async def create_library(ctx: Context, name: str, description: str = "", password: str = "") -> dict:
    """Create a new library.

    Args:
        name: Name for the new library
        description: Optional description
        password: Optional password to encrypt the library
    """
    data = {"name": name}
    if description:
        data["desc"] = description
    if password:
        data["passwd"] = password

    response = await seafile_request(ctx, "POST", "/api2/repos/", data=data)
    if response.status_code in (200, 201):
        return response.json()
    return {"error": error_message(response)}


@mcp.tool()
async def delete_library(ctx: Context, library_id: str) -> str:
    """Delete a library. WARNING: This permanently deletes all contents.

    Args:
        library_id: The ID of the library to delete
    """
    response = await seafile_request(ctx, "DELETE", f"/api2/repos/{library_id}/")
    if response.status_code in (200, 204):
        return f"Library {library_id} deleted successfully"
    return f"Error: {error_message(response)}"


@mcp.tool()
async def create_directory(ctx: Context, library_id: str, path: str) -> str:
    """Create a new directory in a library.

    Args:
        library_id: The ID of the library
        path: Full path of the directory to create (e.g., "/new-folder")
    """
    response = await seafile_request(
        ctx,
        "POST",
        f"/api2/repos/{library_id}/dir/",
        params={"p": path},
        data={"operation": "mkdir"},
    )
    if response.status_code in (200, 201):
        return f"Directory '{path}' created successfully"
    return f"Error: {error_message(response)}"


@mcp.tool()
async def delete_item(ctx: Context, library_id: str, path: str) -> str:
    """Delete a file or directory from a library.

    Args:
        library_id: The ID of the library
        path: Path to the file or directory to delete
    """
    response = await seafile_request(
        ctx, "DELETE", f"/api2/repos/{library_id}/file/", params={"p": path}
    )
    if response.status_code in (200, 204):
        return f"'{path}' deleted successfully"
    return f"Error: {error_message(response)}"


@mcp.tool()
async def rename_item(ctx: Context, library_id: str, path: str, new_name: str) -> str:
    """Rename a file or directory.

    Args:
        library_id: The ID of the library
        path: Current path to the file or directory
        new_name: New name for the item
    """
    response = await seafile_request(
        ctx,
        "POST",
        f"/api2/repos/{library_id}/file/",
        params={"p": path},
        data={"operation": "rename", "newname": new_name},
    )
    if response.status_code == 200:
        return f"Renamed to '{new_name}' successfully"
    return f"Error: {error_message(response)}"


@mcp.tool()
async def move_item(ctx: Context, library_id: str, path: str, dst_library_id: str, dst_path: str) -> str:
    """Move a file or directory to a new location.

    Args:
        library_id: Source library ID
        path: Path to the file or directory to move
        dst_library_id: Destination library ID
        dst_path: Destination directory path
    """
    response = await seafile_request(
        ctx,
        "POST",
        f"/api2/repos/{library_id}/file/",
        params={"p": path},
        data={"operation": "move", "dst_repo": dst_library_id, "dst_dir": dst_path},
    )
    if response.status_code == 200:
        return f"Moved '{path}' to '{dst_path}' successfully"
    return f"Error: {error_message(response)}"


@mcp.tool()
async def copy_item(ctx: Context, library_id: str, path: str, dst_library_id: str, dst_path: str) -> str:
    """Copy a file or directory to a new location.

    Args:
        library_id: Source library ID
        path: Path to the file or directory to copy
        dst_library_id: Destination library ID
        dst_path: Destination directory path
    """
    response = await seafile_request(
        ctx,
        "POST",
        f"/api2/repos/{library_id}/file/",
        params={"p": path},
        data={"operation": "copy", "dst_repo": dst_library_id, "dst_dir": dst_path},
    )
    if response.status_code == 200:
        return f"Copied '{path}' to '{dst_path}' successfully"
    return f"Error: {error_message(response)}"


@mcp.tool()
async def get_file_download_link(ctx: Context, library_id: str, path: str) -> str:
    """Get a download link for a file.

    Args:
        library_id: The ID of the library
        path: Path to the file
    """
    response = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/file/", params={"p": path}
    )
    if response.status_code == 200:
        return response.text.strip('"')
    return f"Error: {error_message(response)}"


@mcp.tool()
async def get_file_content(ctx: Context, library_id: str, path: str) -> str:
    """Get the content of a text file.

    Args:
        library_id: The ID of the library
        path: Path to the file
    """
    # First get the download link
    link_response = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/file/", params={"p": path}
    )
    if link_response.status_code != 200:
        return f"Error getting download link: {error_message(link_response)}"

    download_url = link_response.text.strip('"')

    # Download the content
    async with httpx.AsyncClient() as client:
        content_response = await client.get(download_url, timeout=30.0)
    if content_response.status_code == 200:
        return content_response.text
    return f"Error downloading file: {content_response.status_code}"


@mcp.tool()
async def get_upload_link(ctx: Context, library_id: str, path: str = "/") -> str:
    """Get an upload link for a directory. Use this to upload files.

    Args:
        library_id: The ID of the library
        path: Directory path where files will be uploaded (default: root)
    """
    response = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/upload-link/", params={"p": path}
    )
    if response.status_code == 200:
        return response.text.strip('"')
    return f"Error: {error_message(response)}"


@mcp.tool()
async def search_files(ctx: Context, query: str, library_id: str = "") -> list:
    """Search for files across libraries.

    Args:
        query: Search query string
        library_id: Optional library ID to limit search scope
    """
    params = {"q": query}
    if library_id:
        params["repo_id"] = library_id

    response = await seafile_request(ctx, "GET", "/api2/search/", params=params, timeout=30.0)
    if response.status_code == 200:
        return [
            {
                "name": item.get("name"),
                "path": item.get("fullpath"),
                "library_id": item.get("repo_id"),
                "library_name": item.get("repo_name"),
            }
            for item in response.json().get("results", [])
        ]
    return [{"error": error_message(response)}]


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Health check endpoint for Docker and load balancers (http mode only)."""
    return JSONResponse({"status": "ok"})


def transport_security(host: str) -> TransportSecuritySettings | None:
    """Build DNS rebinding protection settings from MCP_ALLOWED_HOSTS.

    MCP_ALLOWED_HOSTS is a comma-separated list of hostnames the server is
    reached at (e.g. "files-mcp.example.com"). When unset, the SDK default
    applies: protection on for localhost binds, off otherwise.
    """
    allowed = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if not allowed:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed + [f"{h}:*" for h in allowed],
        allowed_origins=[f"https://{h}" for h in allowed] + [f"http://{h}:*" for h in allowed],
    )


def main() -> None:
    global TRANSPORT

    parser = argparse.ArgumentParser(description="Seafile MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="stdio for a local MCP server, http for a hosted one (env: MCP_TRANSPORT)",
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"), help="http bind address (env: MCP_HOST)")
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")), help="http port (env: MCP_PORT)")
    args = parser.parse_args()

    TRANSPORT = args.transport
    logging.basicConfig(level=logging.INFO)
    # httpx logs every request URL (including file paths); keep that out of server logs
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not SEAFILE_URL:
        logger.warning("SEAFILE_URL is not set; all Seafile tools will fail")

    if TRANSPORT == "stdio":
        mcp.run()
        return

    if SEAFILE_TOKEN:
        logger.warning("SEAFILE_TOKEN is ignored in http mode; clients must send their own token")
    logger.info("Serving Seafile MCP for %s at http://%s:%d/mcp", SEAFILE_URL, args.host, args.port)
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        transport_security=transport_security(args.host),
    )


if __name__ == "__main__":
    main()
