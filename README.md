# reddit-mcp

MCP server for Reddit. Read-only mode works out of the box with no setup. Write mode requires a session cookie and comes with risks.

## Read-Only Mode (No Setup Required)

Reading from Reddit requires no credentials. Just install and use:

```bash
pip install reddit-mcp
```

The read tools (`reddit_read`, `reddit_listing`, `reddit_search`) fetch public JSON from `old.reddit.com`. This is identical to viewing Reddit in a browser — no login required.

**Note:** Feeding Reddit content to AI probably violates Reddit's ToS. However, read-only access is indistinguishable from normal browsing, so there's no practical risk — Reddit can't tell the difference between you reading a post and Claude reading it.

### MCP Config (Read-Only)

```json
{
  "mcpServers": {
    "reddit": {
      "command": "reddit-mcp"
    }
  }
}
```

### CLI Examples (Read-Only)

```bash
# Read a post with comments
reddit read https://reddit.com/r/LocalLLaMA/comments/abc123/post_title

# List subreddit posts
reddit listing LocalLLaMA --limit 10

# Search
reddit search LocalLLaMA "llama 3"
```

---

## Write Mode (Session Cookie Required)

**⚠️ Read this before proceeding.**

Write mode lets you post comments, submit posts, vote, and check your inbox. It works by using session cookies from your browser.

### The Risk

**This violates Reddit's Terms of Service.** Reddit [severely restricted API access](https://www.reddit.com/r/reddit/comments/145bram/addressing_the_community_about_changes_to_our_api/) in 2023 and stopped issuing new free API keys entirely in December 2025. Using automation to bypass their API restrictions is explicitly against their rules.

If Reddit detects automated access on your account, **your account may be permanently banned**. There's no way to predict if or when this will happen.

### If You Accept the Risk

#### Option 1: Auto-Import from Browser (Recommended)

If you're logged into Reddit in your browser, the CLI can import your session automatically:

```bash
# Auto-detect browser
reddit auth

# Or specify a browser
reddit auth --browser firefox
reddit auth --browser chrome
```

This extracts the `reddit_session` cookie and saves it to `~/.config/reddit-mcp/session.json`.

**Supported browsers:**

| Browser | Linux | macOS | Windows |
|---------|-------|-------|---------|
| Firefox | ✓ | ✓ | ✓ |
| Chrome | ✓ | ✓ | ✓ |
| Chromium | ✓ | ✓ | ✓ |
| Safari | — | ? | — |
| Edge | ✓ | ✓ | ✓ |
| Opera | ✓ | ✓ | ✓ |
| Brave | ✓ | ✓ | ✓ |

✓ = supported, ? = untested, — = not applicable

**Notes:**
- Snap and Flatpak installations of Chrome/Chromium are supported on Linux
- Chrome-based browsers may prompt for keychain/keyring access to decrypt cookies
- Safari support is untested — please report if it works (or doesn't)

**Using different accounts:** If you use different browsers for different Reddit accounts, specify the browser:

```bash
# Main account in Firefox
reddit auth --browser firefox

# Alt account in Chromium (use different session directory)
REDDIT_SESSION_DIR=~/.config/reddit-mcp-alt reddit auth --browser chromium
```

#### Option 2: Manual Cookie Export

If auto-import doesn't work:

1. Log into Reddit in your browser
2. Open DevTools (F12) → Application → Cookies → `https://www.reddit.com`
3. Find the cookie named `reddit_session`
4. Copy its value (it's a long JWT string starting with `eyJ...`)
5. Create `~/.config/reddit-mcp/session.json`:

```json
{
  "cookies": {
    "reddit_session": "eyJhbGciOiJS... (your full cookie value here)"
  },
  "username": "your_reddit_username"
}
```

**Note:** Manual setup doesn't support auto-refresh. When your cookie expires, you'll need to repeat these steps. Use `reddit auth` if you want automatic refresh.

#### (Optional) Override the Session Location

By default, the session is stored in `~/.config/reddit-mcp/`. You can override this in your MCP config if you want Claude to use a different Reddit account than your CLI default, or if you're running multiple instances with different accounts:

```json
{
  "mcpServers": {
    "reddit": {
      "command": "reddit-mcp",
      "env": {
        "REDDIT_SESSION_DIR": "/path/to/session/directory"
      }
    }
  }
}
```

### How Write Mode Works

1. Write operations load the session cookie from `~/.config/reddit-mcp/session.json`
2. The cookie is used to authenticate with `old.reddit.com`
3. When the cookie expires, reddit-mcp automatically re-imports from the same browser

Reddit session cookies last a long time (months), so refreshes are rare. If auto-refresh fails (e.g., you logged out of the browser), just run `reddit auth` again.

### Write Tools

| Tool | Description |
|------|-------------|
| `reddit_inbox` | Check replies, mentions, messages |
| `reddit_comment` | Reply to a post or comment |
| `reddit_submit` | Submit a new post |
| `reddit_vote` | Upvote/downvote |
| `reddit_delete` | Delete your own content |

### CLI Examples (Write Mode)

```bash
# Check inbox
reddit inbox
reddit inbox --unread

# Post a comment (thing_id is t3_xxx for posts, t1_xxx for comments)
reddit comment t3_abc123 "This is my reply"

# Submit a text post
reddit submit LocalLLaMA "Post Title" --text "Post body here"

# Submit a link post
reddit submit LocalLLaMA "Post Title" --url "https://example.com"

# Vote (1 = upvote, -1 = downvote, 0 = remove vote)
reddit vote t3_abc123 1

# Delete your own post or comment
reddit delete t1_xyz789
```

---

## Why This Exists

Reddit severely restricted third-party API access in 2023 and stopped issuing new free API keys entirely in December 2025. If you want to build something that interacts with Reddit programmatically, your options are:

1. Be a large company that can negotiate API access
2. Scrape public pages (read-only)
3. Use session cookies (what this does for writes)

This tool exists because the AI/LLM community benefits from being able to interact with Reddit, and Reddit has made that impossible through official channels.

## License

[Unlicense](https://unlicense.org/) — Public domain. Do whatever you want with it.

The author takes no responsibility for any consequences of using this tool.
