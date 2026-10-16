# Seafile MCP Server

[![Author](https://img.shields.io/badge/author-Setu%20Kathawate-blue)](https://github.com/setugk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that connects Claude to your Seafile file storage. This lets you ask Claude to browse, search, read, and manage files on your self-hosted Seafile server using natural language.

---

## What is Seafile?

[Seafile](https://www.seafile.com/) is an open-source, self-hosted file sync and share platform - similar to Dropbox or Google Drive, but you control your own data. It's popular for personal use, teams, and enterprises who want privacy and control over their files.

**Why Seafile?**
- **Self-hosted**: Your files stay on your own server
- **Privacy-focused**: No third-party access to your data
- **Fast sync**: Efficient file synchronization across devices
- **Libraries**: Organize files into encrypted or unencrypted libraries
- **Cross-platform**: Apps for Windows, Mac, Linux, iOS, Android

**Don't have Seafile yet?** Here's how to get started:

| Option | Description | Link |
|--------|-------------|------|
| **Seafile Cloud** | Hosted by Seafile (easiest) | [cloud.seafile.com](https://cloud.seafile.com/) |
| **Docker Install** | Self-host with Docker (recommended) | [Docker Guide](https://manual.seafile.com/docker/deploy_seafile_with_docker/) |
| **Manual Install** | Self-host on Linux server | [Manual Guide](https://manual.seafile.com/deploy/) |
| **Synology NAS** | Run on Synology NAS | [Synology Package](https://www.seafile.com/en/download/) |
| **UGREEN NAS** | Run on UGREEN NAS via Docker | [Docker Guide](https://manual.seafile.com/docker/deploy_seafile_with_docker/) |
| **Raspberry Pi** | Self-host on a Pi | [Pi Guide](https://manual.seafile.com/deploy/deploy_with_raspberrypi/) |

### Why This MCP Server?

- **Direct connection** - Connects straight to your Seafile server, no third-party service
- **Privacy-first** - Your data never leaves your infrastructure
- **Free & open source** - No subscriptions, no vendor lock-in
- **Full control** - Inspect, modify, and extend the code as needed
- **Run it your way** - Locally on your machine, or hosted once for your whole team

---

## What can you do with this MCP server?

Once set up, you can ask Claude things like:

**Document Lookups**
- "What are my flight details for the Hawaii trip?"
- "When is my car rental pickup?"
- "Find my tax files from 2024"
- "What's in my Immigration folder?"
- "Show me my recent receipts"
- "List all of Mom's travel folders"
- "Find Dad's visa documents"

**Organization**
- "Create a new folder called '2025 Taxes'"
- "Move the completed trip to Archive"
- "What's in my 'Ideas' folder?"

**Quick Search**
- "Find all PDFs related to insurance"
- "Which folders were modified this month?"
- "Do I have a copy of my lease agreement?"

## Features

| Feature | Description |
|---------|-------------|
| **Browse Libraries** | List all libraries, view library details |
| **Navigate Folders** | List directory contents at any path |
| **Read Files** | Read text file contents directly |
| **File Operations** | Create, rename, move, copy, delete files and folders |
| **Download Links** | Generate download links for any file |
| **Upload Links** | Get upload links for directories |
| **Search** | Search for files across libraries (if enabled on your server) |

---

## Two Ways to Run It

| | **Local (stdio)** | **Hosted (HTTP)** |
|---|---|---|
| **Where it runs** | On each user's machine, launched by their MCP client | Once, on your server (Docker) |
| **Who it's for** | Just you | You, your family, or your team |
| **Token lives in** | Your local `.env` file | Each user's MCP client config |
| **Seafile URL set by** | Your local `.env` file | The server operator (`SEAFILE_URL`) |
| **Users need to install** | Python and this repo | Nothing, just a URL and their token |

In hosted mode, every user sends **their own** Seafile token. The server forwards it to Seafile, so everyone only sees what their own Seafile account allows. The server never uses a token of its own.

---

## Step 1: Get Your Seafile API Token

Both modes need a Seafile API token.

#### Option A: Using the Seafile Web Interface

1. Log into your Seafile web interface
2. Click your avatar/profile icon in the top right
3. Go to **Settings** → **Web API Auth Token**
4. Click **Generate Token** or copy your existing token

#### Option B: Using curl (Command Line)

```bash
curl -d "username=YOUR_EMAIL&password=YOUR_PASSWORD" \
     https://YOUR_SEAFILE_SERVER/api2/auth-token/
```

Replace:
- `YOUR_EMAIL` - Your Seafile login email
- `YOUR_PASSWORD` - Your Seafile password
- `YOUR_SEAFILE_SERVER` - Your Seafile server URL (e.g., `cloud.seafile.com`)

The response will look like:
```json
{"token": "a1b2c3d4e5f6g7h8i9j0..."}
```

Copy the token value (without quotes).

---

## Option A: Local Mode (stdio)

### Prerequisites

- **Python 3.10 or higher** - Check with `python3 --version`
- **Claude Desktop app** or **Claude Code CLI**

### Install

```bash
git clone https://github.com/setugk/seafile-mcp.git
cd seafile-mcp

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env` and set:

```
SEAFILE_URL=https://your-seafile-server.com
SEAFILE_TOKEN=your-api-token-here
```

- No trailing slash on the URL
- No quotes around values
- Keep this file secret (it's already in `.gitignore`)

### Connect to Claude

**Claude Code:**

```bash
claude mcp add seafile -- /FULL/PATH/TO/seafile-mcp/venv/bin/python /FULL/PATH/TO/seafile-mcp/src/server.py
```

**Claude Desktop:** open `Claude` menu → `Settings` → `Developer` → `Edit Config` and add:

```json
{
  "mcpServers": {
    "seafile": {
      "command": "/FULL/PATH/TO/seafile-mcp/venv/bin/python",
      "args": ["/FULL/PATH/TO/seafile-mcp/src/server.py"]
    }
  }
}
```

Replace `/FULL/PATH/TO/` with the absolute path to this repo. On Windows the Python path is `C:\\path\\to\\seafile-mcp\\venv\\Scripts\\python.exe`. Then fully quit and reopen Claude Desktop.

**Test it:** ask Claude to "List my Seafile libraries".

---

## Option B: Hosted Mode (HTTP + Docker)

Run one server that anyone with an account on your Seafile can connect to by URL.

### Prerequisites

- A server with **Docker** and **Docker Compose**
- A domain for the MCP server (e.g. `files-mcp.example.com`)
- A reverse proxy for HTTPS (Caddy, nginx, Traefik, Cloudflare Tunnel, ...)

### Deploy

```bash
git clone https://github.com/setugk/seafile-mcp.git
cd seafile-mcp
```

Create a `.env` file next to `docker-compose.yml`:

```
SEAFILE_URL=https://files.example.com
MCP_ALLOWED_HOSTS=files-mcp.example.com
```

Start it:

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health    # {"status":"ok"}
```

The container listens on `127.0.0.1:8000`, so it is only reachable through your reverse proxy. For example, with Caddy:

```
files-mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

The MCP endpoint is then `https://files-mcp.example.com/mcp`.

**Without Compose:**

```bash
docker build -t seafile-mcp .
docker run -d --name seafile-mcp --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e SEAFILE_URL=https://files.example.com \
  -e MCP_ALLOWED_HOSTS=files-mcp.example.com \
  seafile-mcp
```

**Without Docker:**

```bash
SEAFILE_URL=https://files.example.com python src/server.py --transport http --host 127.0.0.1 --port 8000
```

### Connect to Claude

Each user adds the server with **their own** Seafile token:

**Claude Code:**

```bash
claude mcp add --transport http seafile https://files-mcp.example.com/mcp \
  --header "Authorization: Bearer YOUR_SEAFILE_TOKEN"
```

**Other MCP clients:** use the Streamable HTTP transport with URL `https://files-mcp.example.com/mcp` and the header `Authorization: Bearer YOUR_SEAFILE_TOKEN`.

### Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SEAFILE_URL` | *(required)* | Your Seafile server URL, no trailing slash |
| `SEAFILE_TOKEN` | | Local mode only. **Ignored in hosted mode.** |
| `MCP_TRANSPORT` | `stdio` (`http` in Docker) | `stdio` or `http`. Also `--transport` |
| `MCP_HOST` | `127.0.0.1` (`0.0.0.0` in Docker) | Bind address. Also `--host` |
| `MCP_PORT` | `8000` | Port. Also `--port` |
| `MCP_ALLOWED_HOSTS` | | Comma-separated public hostnames. Enables Host/Origin checks (DNS rebinding protection). Recommended in production |

---

## Available Tools

Once connected, Claude has access to these tools:

| Tool | Description |
|------|-------------|
| `hello` | Test that the MCP server is working |
| `ping_server` | Test connection to your Seafile server |
| `get_account_info` | Get your Seafile account information |
| `list_libraries` | List all your libraries/repos |
| `get_library` | Get details of a specific library |
| `list_directory` | List contents of a folder |
| `create_library` | Create a new library |
| `delete_library` | Delete a library (permanent!) |
| `create_directory` | Create a new folder |
| `delete_item` | Delete a file or folder |
| `rename_item` | Rename a file or folder |
| `move_item` | Move a file or folder |
| `copy_item` | Copy a file or folder |
| `get_file_content` | Read a text file's contents |
| `get_file_download_link` | Get a download URL for a file |
| `get_upload_link` | Get an upload URL for a folder |
| `search_files` | Search for files (requires search enabled on server) |

---

## Troubleshooting

### "Server not appearing in Claude Desktop"

- Double-check the paths in your config are absolute paths (start with `/` on Mac/Linux or `C:\` on Windows)
- Make sure you fully restarted Claude Desktop (not just closed the window)
- Check for JSON syntax errors in your config file (missing commas, brackets)

### "SEAFILE_TOKEN is not configured" (local mode)

- Make sure you created the `.env` file (not just `.env.example`)
- Make sure the `.env` file is in the project root directory (same folder as `src/`)
- Check there are no extra spaces or quotes in your `.env` values

### "Missing Seafile token" (hosted mode)

- Your MCP client isn't sending the token. Check the `Authorization: Bearer YOUR_SEAFILE_TOKEN` header in your client config

### "Seafile rejected the token" or "401 Unauthorized"

- Your API token may have expired - generate a new one
- Make sure you copied the full token with no extra spaces
- In hosted mode, make sure your token is for the same Seafile server the MCP server points at

### "Connection error: Could not reach server"

- Verify your Seafile server URL is correct and accessible
- Try opening the URL in a browser
- In hosted mode, the MCP server itself must be able to reach Seafile. Test with `docker exec seafile-mcp python -c "import urllib.request; print(urllib.request.urlopen('https://files.example.com').status)"`

### "421 Misdirected Request" or "Invalid Host header" (hosted mode)

- `MCP_ALLOWED_HOSTS` doesn't match the hostname clients connect to, or your reverse proxy isn't passing the original `Host` header

### "Module not found" errors (local mode)

- Make sure you're using the Python from the virtual environment in your config
- Run `venv/bin/pip install -r requirements.txt` again. This project needs `mcp` 2.x

### Check server logs

```bash
# Local mode
source venv/bin/activate
python src/server.py

# Hosted mode
docker compose logs -f
```

---

## Roadmap

Features planned for future releases:

| Feature | Status | Description |
|---------|--------|-------------|
| **PDF reading** | Planned | Extract text from PDF files so Claude can answer questions about receipts, contracts, etc. |
| **Image OCR** | Idea | Extract text from images using OCR |
| **File upload** | Idea | Upload files to Seafile via Claude |

Have a feature request? [Open an issue](https://github.com/setugk/seafile-mcp/issues)!

---

## Security & Privacy

> **Important:** Please read [SECURITY.md](SECURITY.md) for full security considerations.

### Protecting Your Credentials

- **Never commit your `.env` file** - It contains your API token
- **Secure file permissions** - Run `chmod 600 .env` to restrict access
- **Rotate tokens periodically** - Generate new tokens and revoke old ones
- **Use HTTPS** - Always connect to your Seafile server over HTTPS

### What Claude Can See

When using this MCP server:
- Claude sees **file and folder names** when you browse
- Claude sees **file contents** when you ask to read them
- Conversations are processed by Anthropic's servers

**Best practice:** Avoid asking Claude to read highly sensitive files (passwords, private keys, financial account numbers).

### What Claude Can Do

The MCP server allows Claude to:
- Browse, read, and search files
- Create, rename, move, copy, and **delete** files/folders

**Be careful with destructive commands.** Consider using a read-only API token if your Seafile server supports scoped permissions.

### Local Mode

- The MCP server runs locally with your user permissions
- Anyone with access to your machine could read your `.env` file
- Use standard device security (lock screen, disk encryption)

### Hosted Mode

- **Always serve it over HTTPS.** Tokens are sent with every request
- **Users trust the operator.** Each user's token passes through the MCP server. The server doesn't store or log tokens, but users should only connect to servers they trust
- **The server has no token of its own.** Requests without a valid Seafile token can't do anything, so the endpoint can be public
- **Tokens are full-access.** A Seafile API token can do everything the account can, including deleting libraries
- **Set `MCP_ALLOWED_HOSTS`** to enable Host/Origin header checks

**Reporting vulnerabilities:** See [SECURITY.md](SECURITY.md) for responsible disclosure guidelines.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## License

MIT License - See LICENSE file for details.

---

## Author

**Setu Kathawate**

- GitHub: [@setugk](https://github.com/setugk)

## Acknowledgments

- Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- Uses the [Seafile Web API](https://download.seafile.com/published/web-api/home.md)
