# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Email the maintainer directly (or open a private security advisory on GitHub)
3. Include a detailed description of the vulnerability and steps to reproduce

We will respond within 48 hours and work with you to understand and address the issue.

## Security Considerations

### API Token Security

This MCP server requires a Seafile API token for authentication. Please be aware:

- **API tokens grant full access** to your Seafile account
- **Never commit your `.env` file** - it contains your API token
- **Never share your API token** in logs, screenshots, or public forums
- **Rotate tokens periodically** - generate new tokens and revoke old ones
- **Use scoped tokens** if your Seafile server supports them (limits access to specific libraries)

### Local Mode (stdio) Risks

In local mode this MCP server runs on your machine. Be aware that:

- The server has access to whatever the Seafile API token allows
- MCP clients (like Claude Desktop) can invoke any tool exposed by this server
- Review tool descriptions to understand what operations are possible

### Hosted Mode (HTTP) Risks

In hosted mode the server is reachable over the network. Be aware that:

- Each client sends its own Seafile token with every request; the server forwards it to Seafile and does not store or log it
- The server never uses a token of its own (`SEAFILE_TOKEN` is ignored), so unauthenticated requests cannot access any data
- Users must trust the operator of a hosted server, since their token passes through it
- Always put the server behind HTTPS (reverse proxy) and set `MCP_ALLOWED_HOSTS` to enable Host/Origin header checks
- The Docker setup binds to `127.0.0.1` by default so only your reverse proxy can reach it

### Network Security

- Use HTTPS for your Seafile server and, in hosted mode, for the MCP server
- In local mode the server does not expose any network ports (uses stdio transport)
- Credentials are loaded from environment variables or request headers, not passed via command line

### Best Practices

1. **Minimal permissions**: If your Seafile server supports library-specific tokens, use them
2. **Secure your `.env` file**: Ensure it has restrictive file permissions (`chmod 600 .env`)
3. **Review before running**: Inspect the `src/server.py` code before running
4. **Keep updated**: Pull updates to get security fixes
5. **Monitor access**: Check your Seafile server's access logs periodically

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |

## Dependencies

This project depends on:
- `mcp` - Model Context Protocol library
- `httpx` - HTTP client
- `python-dotenv` - Environment variable loading
- `pypdf`, `pypdfium2` - PDF text extraction and page rendering
- `pillow` - Image decoding and resizing

Keep dependencies updated to receive security patches:

```bash
pip install --upgrade -r requirements.txt
```
