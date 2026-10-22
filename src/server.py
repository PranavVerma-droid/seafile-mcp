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
import base64
import binascii
import logging
import os
import posixpath
from datetime import datetime

import anyio
import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from file_readers import UnsupportedFileError, detect_kind, read_image, read_pdf, read_text

# Load environment variables
load_dotenv()

SEAFILE_URL = os.getenv("SEAFILE_URL", "").rstrip("/")
SEAFILE_TOKEN = os.getenv("SEAFILE_TOKEN", "")

# Largest file get_file_content will download (in hosted mode this is held in server memory)
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "20"))

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
    json: dict | None = None,
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
            json=json,
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
async def get_file_content(
    ctx: Context, library_id: str, path: str, page_start: int = 1, max_pages: int = 20
) -> list[str | Image]:
    """Read a file. Handles text files, PDFs and images.

    - Text files are returned as text.
    - PDFs return the text of each page. Scanned pages without a text layer
      are returned as images. Long PDFs are read in chunks: use page_start
      and max_pages to page through them.
    - Images (PNG, JPEG, GIF, WebP, BMP, TIFF) are returned as images, so you
      can read text, receipts, tables or handwriting in them directly.

    Args:
        library_id: The ID of the library
        path: Path to the file
        page_start: PDFs only. First page to read, starting at 1 (default: 1)
        max_pages: PDFs only. Maximum number of pages to read (default: 20)
    """
    # First get the download link
    link_response = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/file/", params={"p": path}
    )
    if link_response.status_code != 200:
        return [f"Error getting download link: {error_message(link_response)}"]

    download_url = link_response.text.strip('"')
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

    # Stream the download so oversized files are rejected without loading them fully
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", download_url, timeout=60.0) as response:
            if response.status_code != 200:
                return [f"Error downloading file: {response.status_code}"]
            too_big = [
                f"File is larger than the {MAX_FILE_SIZE_MB} MB limit. "
                "Use get_file_download_link to download it instead."
            ]
            if int(response.headers.get("content-length", 0)) > max_bytes:
                return too_big
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    return too_big
    data = bytes(data)

    # Parsing and rendering are CPU-bound; keep them off the event loop
    try:
        match detect_kind(path, data):
            case "pdf":
                return await anyio.to_thread.run_sync(read_pdf, data, page_start, max_pages)
            case "image":
                return [await anyio.to_thread.run_sync(read_image, data)]
            case _:
                return [read_text(data)]
    except UnsupportedFileError as e:
        return [f"Error: {e}"]


@mcp.tool()
async def upload_file(
    ctx: Context,
    library_id: str,
    path: str,
    content: str,
    encoding: str = "text",
    overwrite: bool = False,
) -> str:
    """Upload a file to a library, or replace an existing one.

    Use this to save notes, documents, CSVs, code or other files you write.
    The parent directory must already exist (see create_directory).

    Args:
        library_id: The ID of the library
        path: Full path of the file to create, including its name (e.g. "/Notes/todo.md")
        content: The file content. Plain text, or base64 if encoding is "base64"
        encoding: "text" (default, saved as UTF-8) or "base64" for binary files
        overwrite: Replace the file if it already exists (default: False)
    """
    if path.endswith("/"):
        return "Error: path must include a file name, e.g. /Notes/todo.md"
    path = "/" + path.lstrip("/")
    parent_dir, filename = posixpath.split(path)
    if not filename:
        return "Error: path must include a file name, e.g. /Notes/todo.md"

    if encoding == "text":
        data = content.encode("utf-8")
    elif encoding == "base64":
        try:
            data = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            return "Error: content is not valid base64"
    else:
        return 'Error: encoding must be "text" or "base64"'

    if len(data) > MAX_FILE_SIZE_MB * 1024 * 1024:
        return f"Error: file is larger than the {MAX_FILE_SIZE_MB} MB limit"

    # Seafile silently renames uploads that clash with an existing file
    # ("todo (1).md"), so check first and only replace when asked to.
    detail = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/file/detail/", params={"p": path}
    )
    exists = detail.status_code == 200
    if exists and not overwrite:
        return f"Error: '{path}' already exists. Call again with overwrite=True to replace it."
    if detail.status_code not in (200, 404):
        return f"Error checking for an existing file: {error_message(detail)}"

    link_response = await seafile_request(
        ctx, "GET", f"/api2/repos/{library_id}/upload-link/", params={"p": parent_dir}
    )
    if link_response.status_code != 200:
        return f"Error getting upload link: {error_message(link_response)}"
    upload_url = link_response.text.strip('"')

    form = {"parent_dir": parent_dir}
    if exists:
        form["replace"] = "1"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            upload_url,
            params={"ret-json": "1"},
            data=form,
            files={"file": (filename, data)},
            timeout=120.0,
        )
    if response.status_code != 200:
        return f"Error uploading file: Status {response.status_code}: {response.text}"

    action = "Replaced" if exists else "Uploaded"
    return f"{action} '{path}' ({len(data)} bytes)"


@mcp.tool()
async def get_upload_link(ctx: Context, library_id: str, path: str = "/") -> str:
    """Get an upload link for a directory, for a person to upload files with
    (e.g. via curl or a script). To upload a file yourself, use upload_file.

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


# The permission choices offered by Seafile's "Generate Link" dialog
SHARE_LINK_PERMISSIONS = {
    "preview_download": {"can_edit": False, "can_download": True, "can_upload": False},
    "preview_only": {"can_edit": False, "can_download": False, "can_upload": False},
    "download_upload": {"can_edit": False, "can_download": True, "can_upload": True},
}


def share_link_permission(permissions: dict) -> str:
    """Name the permission of a share link from its Seafile permissions dict."""
    if permissions.get("can_edit"):
        return "edit"
    if permissions.get("can_upload"):
        return "download_upload"
    if permissions.get("can_download", True):
        return "preview_download"
    return "preview_only"


def format_share_link(link: dict) -> dict:
    """Simplify a share link returned by the Seafile API."""
    return {
        "link": link.get("link"),
        "token": link.get("token"),
        "library_id": link.get("repo_id"),
        "library_name": link.get("repo_name"),
        "path": link.get("path"),
        "is_dir": link.get("is_dir"),
        "permission": share_link_permission(link.get("permissions") or {}),
        # Older Seafile versions don't report the password, so this can be unknown
        "password_protected": bool(link["password"]) if "password" in link else None,
        "expires": link.get("expire_date") or None,
        "is_expired": link.get("is_expired"),
        "views": link.get("view_cnt"),
        "created": link.get("ctime"),
    }


@mcp.tool()
async def list_share_links(ctx: Context, library_id: str = "", path: str = "") -> list:
    """List existing share links (public links anyone with the URL can open).

    With no arguments, lists all of your share links. Give library_id to list
    the links in one library, and also path to list the links for one file or
    folder.

    Args:
        library_id: Optional library ID to limit the results to
        path: Optional path of a file or folder (requires library_id)
    """
    if path and not library_id:
        return [{"error": "path requires library_id"}]
    params = {}
    if library_id:
        params["repo_id"] = library_id
    if path:
        params["path"] = path

    response = await seafile_request(ctx, "GET", "/api/v2.1/share-links/", params=params)
    if response.status_code == 200:
        return [format_share_link(link) for link in response.json()]
    return [{"error": error_message(response)}]


@mcp.tool()
async def create_share_link(
    ctx: Context,
    library_id: str,
    path: str,
    permission: str = "preview_download",
    password: str = "",
    expire_days: int = 0,
    expiration_date: str = "",
) -> dict:
    """Create a share link for a file or folder and return its URL.

    Anyone with the link can open it, so add a password or expiry for
    anything sensitive. Check list_share_links first if an existing link
    would do.

    Args:
        library_id: The ID of the library
        path: Path to the file or folder to share
        permission: "preview_download" (default), "preview_only", or
            "download_upload" (folders only: visitors can also upload)
        password: Optional password visitors must enter. Seafile requires a
            minimum length (8 characters by default)
        expire_days: Optional number of days until the link expires
        expiration_date: Optional expiry as an ISO date or datetime
            (e.g. "2026-12-31" or "2026-12-31T18:00:00+05:30"). Use either
            this or expire_days, not both
    """
    if permission not in SHARE_LINK_PERMISSIONS:
        return {"error": f"permission must be one of: {', '.join(SHARE_LINK_PERMISSIONS)}"}
    if expire_days and expiration_date:
        return {"error": "Use either expire_days or expiration_date, not both"}
    if expire_days < 0:
        return {"error": "expire_days must be a positive number of days"}

    body = {
        "repo_id": library_id,
        "path": path,
        "permissions": SHARE_LINK_PERMISSIONS[permission],
    }
    if password:
        body["password"] = password
    if expire_days:
        body["expire_days"] = expire_days
    if expiration_date:
        try:
            datetime.fromisoformat(expiration_date)
        except ValueError:
            return {"error": 'expiration_date must be an ISO date like "2026-12-31"'}
        body["expiration_time"] = expiration_date

    response = await seafile_request(ctx, "POST", "/api/v2.1/share-links/", json=body)
    if response.status_code not in (200, 201):
        return {"error": error_message(response)}

    result = format_share_link(response.json())
    if password:
        result["password"] = password
        result["password_protected"] = True
    if (expire_days or expiration_date) and not result["expires"]:
        # Older Seafile versions ignore expiration_time instead of rejecting it
        result["warning"] = "Seafile created the link without an expiry. Delete it or use expire_days."
    return result


@mcp.tool()
async def delete_share_link(ctx: Context, token: str) -> str:
    """Delete a share link, so its URL stops working.

    Args:
        token: The link's token (from list_share_links), or the full link URL
    """
    token = token.strip().rstrip("/").rsplit("/", 1)[-1]
    if not token:
        return "Error: token is required"
    response = await seafile_request(ctx, "DELETE", f"/api/v2.1/share-links/{token}/")
    if response.status_code in (200, 204):
        return f"Share link {token} deleted"
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
