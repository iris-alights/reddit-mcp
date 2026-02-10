#!/usr/bin/env python3
"""Reddit client using session cookies - no API required.

Combines reading (public JSON endpoints) and writing (session-authenticated forms).
Reddit no longer issues API keys, so this uses browser-style authentication.

Copyright (C) 2026 Iris Thomas. Released under the Unlicense.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

# Session file location (configurable via env)
SESSION_DIR = Path(os.environ.get("REDDIT_SESSION_DIR", Path.home() / ".config" / "reddit-mcp"))
SESSION_FILE = SESSION_DIR / "session.json"

# Reddit URLs
BASE_URL = "https://old.reddit.com"

# Headers to look like a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://old.reddit.com",
    "Referer": "https://old.reddit.com/",
}


def save_session(cookies: dict, username: str, browser: str = None):
    """Save session to disk."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "cookies": cookies,
        "username": username,
        "saved_at": time.time(),
    }
    if browser:
        data["browser"] = browser
    SESSION_FILE.write_text(json.dumps(data, indent=2))


def load_session() -> Optional[dict]:
    """Load session from disk if it exists."""
    if not SESSION_FILE.exists():
        return None

    try:
        data = json.loads(SESSION_FILE.read_text())
        # Check required fields exist
        if "cookies" not in data or "username" not in data:
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


class RedditClient:
    """Reddit client for both reading and writing."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.modhash: Optional[str] = None
        self.username: Optional[str] = None
        self.logged_in = False

    def _get_modhash_from_page(self) -> Optional[str]:
        """Fetch modhash from old.reddit.com page."""
        resp = self.session.get(BASE_URL)
        match = re.search(r'modhash["\s:]+([a-z0-9]+)', resp.text)
        if match:
            return match.group(1)
        match = re.search(r'"modhash":\s*"([a-z0-9]+)"', resp.text)
        if match:
            return match.group(1)
        return None

    def login(self, allow_refresh: bool = True) -> bool:
        """Log in to Reddit using saved session. Returns True on success.

        If the session is expired and we know which browser it came from,
        automatically tries to refresh from that browser.
        """
        saved = load_session()
        if not saved:
            return False

        for name, value in saved["cookies"].items():
            self.session.cookies.set(name, value, domain='.reddit.com')
        self.username = saved["username"]
        self.modhash = self._get_modhash_from_page()
        if self.modhash:
            self.logged_in = True
            return True

        # Session expired - try to auto-refresh if we know the browser
        if allow_refresh and saved.get("browser"):
            result = auth_from_browser(saved["browser"])
            if result.get("success"):
                # Clear old cookies and retry with fresh session
                self.session.cookies.clear()
                return self.login(allow_refresh=False)

        return False

    def _ensure_logged_in(self) -> bool:
        """Ensure we're logged in, logging in if needed."""
        if not self.logged_in:
            return self.login()
        return True

    async def _async_ensure_logged_in(self) -> bool:
        """Ensure we're logged in (async version - same as sync since no Playwright)."""
        if not self.logged_in:
            return self.login()
        return True

    # =========================================================================
    # READ OPERATIONS (no auth required)
    # =========================================================================

    def _normalize_url(self, url: str) -> str:
        """Normalize Reddit URL to old.reddit.com."""
        # Handle bare subreddit names
        if url.startswith('r/') or url.startswith('/r/'):
            url = f"https://old.reddit.com/{url.lstrip('/')}"
        # Handle bare post IDs
        elif re.match(r'^[a-zA-Z0-9]{5,10}$', url):
            url = f"https://old.reddit.com/comments/{url}"

        # Convert to old.reddit.com
        url = url.replace('www.reddit.com', 'old.reddit.com')
        url = re.sub(r'(?<!old\.)reddit\.com', 'old.reddit.com', url)

        return url

    def read_post(self, url: str, depth: int = 1, max_comments: int = 25) -> dict:
        """Read a Reddit post with comments.

        Args:
            url: Post URL or ID
            depth: How many levels of comment replies to show
            max_comments: Maximum comments to return

        Returns:
            Dict with post data and comments
        """
        url = self._normalize_url(url)

        # Strip query params and add .json
        url = url.split('?')[0].rstrip('/')
        if not url.endswith('.json'):
            url += '.json'

        resp = self.session.get(url)
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}

        if isinstance(data, dict) and 'error' in data:
            return {"success": False, "error": data.get('message', data['error'])}

        # Extract post data
        post_data = data[0]['data']['children'][0]['data']
        post = {
            "id": post_data.get('name'),
            "subreddit": post_data.get('subreddit'),
            "author": post_data.get('author'),
            "title": post_data.get('title'),
            "selftext": post_data.get('selftext'),
            "url": post_data.get('url') if not post_data.get('is_self') else None,
            "score": post_data.get('score'),
            "created_utc": post_data.get('created_utc'),
            "num_comments": post_data.get('num_comments'),
            "permalink": post_data.get('permalink'),
        }

        # Extract comments recursively
        def extract_comments(children, current_depth=1):
            comments = []
            for child in children:
                if child.get('kind') != 't1':
                    continue
                c = child['data']
                if c.get('author') in (None, '[deleted]'):
                    continue

                comment = {
                    "id": c.get('name'),
                    "author": c.get('author'),
                    "body": c.get('body'),
                    "score": c.get('score'),
                    "created_utc": c.get('created_utc'),
                    "depth": current_depth,
                    "replies": [],
                }

                # Get replies if within depth limit
                if current_depth < depth:
                    replies = c.get('replies')
                    if replies and isinstance(replies, dict):
                        reply_children = replies.get('data', {}).get('children', [])
                        comment['replies'] = extract_comments(reply_children, current_depth + 1)

                comments.append(comment)
                if len(comments) >= max_comments:
                    break
            return comments

        comment_children = data[1]['data']['children'] if len(data) > 1 else []
        comments = extract_comments(comment_children)

        return {
            "success": True,
            "post": post,
            "comments": comments,
        }

    def read_listing(self, subreddit: str, limit: int = 15, skip: int = 0,
                     sort: str = "hot") -> dict:
        """Read posts from a subreddit.

        Args:
            subreddit: Subreddit name (without r/)
            limit: Number of posts to return
            skip: Number of posts to skip
            sort: Sort order (hot, new, top, rising)

        Returns:
            Dict with list of posts
        """
        fetch_count = skip + limit
        url = f"{BASE_URL}/r/{subreddit}/{sort}.json?limit={fetch_count}"

        resp = self.session.get(url)
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}

        if isinstance(data, dict) and 'error' in data:
            return {"success": False, "error": data.get('message', data['error'])}

        posts = []
        children = data.get('data', {}).get('children', [])
        for child in children[skip:skip+limit]:
            if child.get('kind') != 't3':
                continue
            p = child['data']
            posts.append({
                "id": p.get('name'),
                "title": p.get('title'),
                "author": p.get('author'),
                "score": p.get('score'),
                "num_comments": p.get('num_comments'),
                "created_utc": p.get('created_utc'),
                "permalink": p.get('permalink'),
                "url": p.get('url') if not p.get('is_self') else None,
                "is_self": p.get('is_self'),
                "stickied": p.get('stickied'),
            })

        return {
            "success": True,
            "subreddit": subreddit,
            "posts": posts,
        }

    def search(self, subreddit: str, query: str, limit: int = 15,
               sort: str = "relevance", time_filter: str = "all") -> dict:
        """Search within a subreddit.

        Args:
            subreddit: Subreddit name
            query: Search query
            limit: Max results
            sort: relevance, hot, top, new, comments
            time_filter: all, hour, day, week, month, year

        Returns:
            Dict with search results
        """
        params = {
            "q": query,
            "restrict_sr": "on",
            "sort": sort,
            "t": time_filter,
            "limit": limit,
        }
        url = f"{BASE_URL}/r/{subreddit}/search.json?{urlencode(params)}"

        resp = self.session.get(url)
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}

        posts = []
        for child in data.get('data', {}).get('children', []):
            if child.get('kind') != 't3':
                continue
            p = child['data']
            posts.append({
                "id": p.get('name'),
                "title": p.get('title'),
                "author": p.get('author'),
                "score": p.get('score'),
                "num_comments": p.get('num_comments'),
                "created_utc": p.get('created_utc'),
                "permalink": p.get('permalink'),
                "is_self": p.get('is_self'),
            })

        return {
            "success": True,
            "subreddit": subreddit,
            "query": query,
            "posts": posts,
        }

    # =========================================================================
    # WRITE OPERATIONS (auth required)
    # =========================================================================

    def _already_replied(self, thing_id: str) -> bool:
        """Check if we've already replied to this thing."""
        if not self.username:
            return False

        info_url = f"{BASE_URL}/api/info.json"
        resp = self.session.get(info_url, params={"id": thing_id})

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return False

        children = data.get("data", {}).get("children", [])
        if not children:
            return False

        thing_data = children[0].get("data", {})
        permalink = thing_data.get("permalink")
        if not permalink:
            return False

        reply_url = f"{BASE_URL}{permalink}.json"
        resp = self.session.get(reply_url, params={"limit": 100})

        try:
            thread_data = resp.json()
        except json.JSONDecodeError:
            return False

        def check_replies(obj) -> bool:
            if isinstance(obj, dict):
                if obj.get("kind") == "t1":
                    author = obj.get("data", {}).get("author", "")
                    if author.lower() == self.username.lower():
                        return True
                    replies = obj.get("data", {}).get("replies")
                    if replies and isinstance(replies, dict):
                        return check_replies(replies)
                elif obj.get("kind") == "Listing":
                    for child in obj.get("data", {}).get("children", []):
                        if check_replies(child):
                            return True
                elif "data" in obj:
                    return check_replies(obj.get("data"))
                elif "children" in obj:
                    for child in obj.get("children", []):
                        if check_replies(child):
                            return True
            elif isinstance(obj, list):
                for item in obj:
                    if check_replies(item):
                        return True
            return False

        if isinstance(thread_data, list) and len(thread_data) > 1:
            return check_replies(thread_data[1])
        return check_replies(thread_data)

    def comment(self, thing_id: str, text: str, check_existing: bool = True) -> dict:
        """Post a comment.

        Args:
            thing_id: The fullname to reply to (t3_xxx for post, t1_xxx for comment)
            text: Comment text (markdown)
            check_existing: If True, check if we already replied

        Returns:
            Dict with success status and comment info
        """
        if not self._ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        if check_existing and self._already_replied(thing_id):
            return {"success": False, "error": f"Already replied to {thing_id}"}

        data = {
            "thing_id": thing_id,
            "text": text,
            "api_type": "json",
            "uh": self.modhash,
        }

        resp = self.session.post(f"{BASE_URL}/api/comment", data=data)

        try:
            result = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid response"}

        if "json" in result:
            errors = result["json"].get("errors", [])
            if errors:
                return {"success": False, "error": str(errors)}

            things = result["json"].get("data", {}).get("things", [])
            if things:
                d = things[0].get("data", {})
                comment_id = d.get("id") or d.get("name")
                # Permalink not in response directly; parse from HTML content
                permalink = None
                content = d.get("content", "")
                match = re.search(r'data-permalink="([^"]+)"', content)
                if match:
                    permalink = match.group(1)
                return {
                    "success": True,
                    "id": comment_id,
                    "permalink": f"https://reddit.com{permalink}" if permalink else None,
                }

        return {"success": True, "id": None, "permalink": None}

    def submit(self, subreddit: str, title: str, text: Optional[str] = None,
               url: Optional[str] = None, flair_id: Optional[str] = None) -> dict:
        """Submit a new post.

        Args:
            subreddit: Subreddit name (without r/)
            title: Post title
            text: Self post text (for text posts)
            url: Link URL (for link posts)
            flair_id: Optional flair ID

        Returns:
            Dict with success status and post info
        """
        if not self._ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        if text and url:
            return {"success": False, "error": "Cannot submit both text and url"}

        data = {
            "sr": subreddit,
            "title": title,
            "kind": "link" if url else "self",
            "api_type": "json",
            "uh": self.modhash,
            "resubmit": "true",
        }

        if text:
            data["text"] = text
        if url:
            data["url"] = url
        if flair_id:
            data["flair_id"] = flair_id

        resp = self.session.post(f"{BASE_URL}/api/submit", data=data)

        try:
            result = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid response"}

        if "json" in result:
            errors = result["json"].get("errors", [])
            if errors:
                return {"success": False, "error": str(errors)}

            d = result["json"].get("data", {})
            if d.get("url"):
                return {
                    "success": True,
                    "url": d["url"],
                    "id": d.get("name"),
                }

        return {"success": True, "raw": result}

    def vote(self, thing_id: str, direction: int) -> dict:
        """Vote on a post or comment.

        Args:
            thing_id: The fullname to vote on
            direction: 1 (upvote), -1 (downvote), 0 (remove vote)

        Returns:
            Dict with success status
        """
        if not self._ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        if direction not in (-1, 0, 1):
            return {"success": False, "error": "Direction must be -1, 0, or 1"}

        data = {
            "id": thing_id,
            "dir": direction,
            "uh": self.modhash,
        }

        resp = self.session.post(f"{BASE_URL}/api/vote", data=data)

        if resp.status_code == 200:
            return {"success": True, "thing_id": thing_id, "direction": direction}
        return {"success": False, "error": f"HTTP {resp.status_code}"}

    def delete(self, thing_id: str) -> dict:
        """Delete a post or comment.

        Args:
            thing_id: The fullname to delete

        Returns:
            Dict with success status
        """
        if not self._ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        data = {
            "id": thing_id,
            "uh": self.modhash,
        }

        resp = self.session.post(f"{BASE_URL}/api/del", data=data)

        if resp.status_code == 200:
            return {"success": True, "thing_id": thing_id}
        return {"success": False, "error": f"HTTP {resp.status_code}"}

    def inbox(self, limit: int = 25, unread_only: bool = False) -> dict:
        """Get inbox messages.

        Args:
            limit: Max messages to retrieve
            unread_only: Only get unread messages

        Returns:
            Dict with messages list
        """
        if not self._ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        url = f"{BASE_URL}/message/{'unread' if unread_only else 'inbox'}.json"
        resp = self.session.get(url, params={"limit": limit})

        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}

        messages = []
        for child in data.get("data", {}).get("children", []):
            msg = child.get("data", {})
            messages.append({
                "id": msg.get("name"),
                "author": msg.get("author"),
                "subject": msg.get("subject"),
                "body": msg.get("body"),
                "context": msg.get("context"),
                "created_utc": msg.get("created_utc"),
                "new": msg.get("new"),
                "type": child.get("kind"),
            })

        return {"success": True, "messages": messages}

    # =========================================================================
    # ASYNC WRITE OPERATIONS (for MCP server)
    # =========================================================================

    async def async_comment(self, thing_id: str, text: str, check_existing: bool = True) -> dict:
        """Post a comment (async version)."""
        if not await self._async_ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        if check_existing and self._already_replied(thing_id):
            return {"success": False, "error": f"Already replied to {thing_id}"}

        data = {
            "thing_id": thing_id,
            "text": text,
            "api_type": "json",
            "uh": self.modhash,
        }

        resp = self.session.post(f"{BASE_URL}/api/comment", data=data)

        try:
            result = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid response"}

        if "json" in result:
            errors = result["json"].get("errors", [])
            if errors:
                return {"success": False, "error": str(errors)}

            things = result["json"].get("data", {}).get("things", [])
            if things:
                d = things[0].get("data", {})
                comment_id = d.get("id") or d.get("name")
                # Permalink not in response directly; parse from HTML content
                permalink = None
                content = d.get("content", "")
                match = re.search(r'data-permalink="([^"]+)"', content)
                if match:
                    permalink = match.group(1)
                return {
                    "success": True,
                    "id": comment_id,
                    "permalink": f"https://reddit.com{permalink}" if permalink else None,
                }

        return {"success": True, "id": None, "permalink": None}

    async def async_submit(self, subreddit: str, title: str, text: Optional[str] = None,
                           url: Optional[str] = None, flair_id: Optional[str] = None) -> dict:
        """Submit a new post (async version)."""
        if not await self._async_ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        if text and url:
            return {"success": False, "error": "Cannot submit both text and url"}

        data = {
            "sr": subreddit,
            "title": title,
            "kind": "link" if url else "self",
            "api_type": "json",
            "uh": self.modhash,
            "resubmit": "true",
        }

        if text:
            data["text"] = text
        if url:
            data["url"] = url
        if flair_id:
            data["flair_id"] = flair_id

        resp = self.session.post(f"{BASE_URL}/api/submit", data=data)

        try:
            result = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid response"}

        if "json" in result:
            errors = result["json"].get("errors", [])
            if errors:
                return {"success": False, "error": str(errors)}

            d = result["json"].get("data", {})
            if d.get("url"):
                return {
                    "success": True,
                    "url": d["url"],
                    "id": d.get("name"),
                }

        return {"success": True, "raw": result}

    async def async_vote(self, thing_id: str, direction: int) -> dict:
        """Vote on a post or comment (async version)."""
        if not await self._async_ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        if direction not in (-1, 0, 1):
            return {"success": False, "error": "Direction must be -1, 0, or 1"}

        data = {
            "id": thing_id,
            "dir": direction,
            "uh": self.modhash,
        }

        resp = self.session.post(f"{BASE_URL}/api/vote", data=data)

        if resp.status_code == 200:
            return {"success": True, "thing_id": thing_id, "direction": direction}
        return {"success": False, "error": f"HTTP {resp.status_code}"}

    async def async_delete(self, thing_id: str) -> dict:
        """Delete a post or comment (async version)."""
        if not await self._async_ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        data = {
            "id": thing_id,
            "uh": self.modhash,
        }

        resp = self.session.post(f"{BASE_URL}/api/del", data=data)

        if resp.status_code == 200:
            return {"success": True, "thing_id": thing_id}
        return {"success": False, "error": f"HTTP {resp.status_code}"}

    async def async_inbox(self, limit: int = 25, unread_only: bool = False) -> dict:
        """Get inbox messages (async version)."""
        if not await self._async_ensure_logged_in():
            return {"success": False, "error": "Not logged in"}

        url = f"{BASE_URL}/message/{'unread' if unread_only else 'inbox'}.json"
        resp = self.session.get(url, params={"limit": limit})

        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}

        messages = []
        for child in data.get("data", {}).get("children", []):
            msg = child.get("data", {})
            messages.append({
                "id": msg.get("name"),
                "author": msg.get("author"),
                "subject": msg.get("subject"),
                "body": msg.get("body"),
                "context": msg.get("context"),
                "created_utc": msg.get("created_utc"),
                "new": msg.get("new"),
                "type": child.get("kind"),
            })

        return {"success": True, "messages": messages}


# =============================================================================
# CLI
# =============================================================================

def format_post(post: dict, comments: list, depth: int = 1) -> str:
    """Format a post and comments for display."""
    lines = []
    lines.append("=" * 79)
    lines.append(f"r/{post['subreddit']} | u/{post['author']} | {post['score']} points | {post['id']}")
    lines.append("=" * 79)
    lines.append("")
    lines.append(post['title'])
    lines.append("")

    if post.get('url'):
        lines.append(f"Link: {post['url']}")
        lines.append("")

    if post.get('selftext'):
        lines.append(post['selftext'])
        lines.append("")

    lines.append("-" * 79)
    lines.append(f"COMMENTS (depth: {depth})")
    lines.append("-" * 79)

    def format_comments(comments: list, indent: int = 0):
        for c in comments:
            prefix = "  " * indent
            marker = "▸" if indent == 0 else "↳"
            lines.append("")
            lines.append(f"{prefix}{marker} u/{c['author']} ({c['score']} pts) [{c['id']}]")
            for body_line in c['body'].split('\n'):
                lines.append(f"{prefix}{body_line}")
            if c.get('replies'):
                format_comments(c['replies'], indent + 1)

    format_comments(comments)
    return '\n'.join(lines)


def format_listing(subreddit: str, posts: list) -> str:
    """Format a subreddit listing for display."""
    lines = []
    lines.append("=" * 79)
    lines.append(f"r/{subreddit}")
    lines.append("=" * 79)
    lines.append("")

    for p in posts:
        score = str(p['score']).rjust(5)
        icon = "📌 " if p.get('stickied') else ("💬 " if p.get('is_self') else "🔗 ")
        title = p['title'][:70] + ("..." if len(p['title']) > 70 else "")
        lines.append(f"{score} │ {icon}{title}")
        lines.append(f"       https://reddit.com{p['permalink']}")

    return '\n'.join(lines)


def _try_extract_session(cj) -> Optional[dict]:
    """Try to extract and verify a Reddit session from a cookie jar.

    Returns dict with username and cookie value if successful, None otherwise.
    """
    cookies = {c.name: c.value for c in cj if 'reddit' in c.domain}

    if 'reddit_session' not in cookies:
        return None

    # Got a session cookie - verify it works
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set('reddit_session', cookies['reddit_session'], domain='.reddit.com')

    # Fetch user info to get username
    resp = session.get(f"{BASE_URL}/api/me.json")
    if resp.status_code != 200:
        return None

    try:
        user_data = resp.json()
        username = user_data.get('data', {}).get('name')
        if not username:
            return None
        return {"username": username, "cookie": cookies['reddit_session']}
    except json.JSONDecodeError:
        return None


def auth_from_browser(browser: str = None) -> dict:
    """Extract Reddit session from browser cookies.

    Args:
        browser: Specific browser to use (firefox, chrome, chromium, edge, opera, brave).
                 If None, tries each in order.

    Returns:
        Dict with success status and session info
    """
    try:
        import browser_cookie3
    except ImportError:
        return {"success": False, "error": "browser_cookie3 not installed. Run: pip install browser_cookie3"}

    # Snap/Flatpak alternate paths for Chrome-based browsers
    home = Path.home()
    alternate_paths = {
        "chromium": [
            home / "snap/chromium/common/chromium/Default/Cookies",
            home / ".var/app/org.chromium.Chromium/config/chromium/Default/Cookies",
        ],
        "chrome": [
            home / "snap/google-chrome/common/google-chrome/Default/Cookies",
            home / ".var/app/com.google.Chrome/config/google-chrome/Default/Cookies",
        ],
    }

    # Map of browser names to functions
    browsers = {
        "firefox": browser_cookie3.firefox,
        "chrome": browser_cookie3.chrome,
        "chromium": browser_cookie3.chromium,
        "safari": browser_cookie3.safari,
        "edge": browser_cookie3.edge,
        "opera": browser_cookie3.opera,
        "brave": browser_cookie3.brave,
    }

    # If specific browser requested, only try that one
    if browser:
        browser = browser.lower()
        if browser not in browsers:
            return {"success": False, "error": f"Unknown browser: {browser}. Options: {', '.join(browsers.keys())}"}
        browsers_to_try = [(browser, browsers[browser])]
    else:
        browsers_to_try = list(browsers.items())

    # Try each browser
    for browser_name, browser_func in browsers_to_try:
        # First try standard path via browser_cookie3
        try:
            cj = browser_func(domain_name='.reddit.com')
            result = _try_extract_session(cj)
            if result:
                save_session({'reddit_session': result['cookie']}, result['username'], browser_name)
                return {
                    "success": True,
                    "browser": browser_name,
                    "username": result['username'],
                    "session_file": str(SESSION_FILE),
                }
        except Exception:
            pass

        # Try alternate paths (Snap/Flatpak) for Chrome-based browsers
        if browser_name in alternate_paths:
            for alt_path in alternate_paths[browser_name]:
                if not alt_path.exists():
                    continue
                try:
                    # Use Chrome class with custom cookie_file (works for Chromium too)
                    # Note: Chrome() returns an object, need to call .load() to get cookies
                    chrome = browser_cookie3.Chrome(
                        cookie_file=str(alt_path),
                        domain_name='.reddit.com'
                    )
                    cj = chrome.load()
                    result = _try_extract_session(cj)
                    if result:
                        # Save just browser_name so auto-refresh can find it
                        save_session({'reddit_session': result['cookie']}, result['username'], browser_name)
                        return {
                            "success": True,
                            "browser": f"{browser_name} (snap/flatpak)",
                            "username": result['username'],
                            "session_file": str(SESSION_FILE),
                        }
                except Exception:
                    continue

    return {
        "success": False,
        "error": "No Reddit session found in any browser. Make sure you're logged into Reddit."
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Reddit client - read and write without API keys"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Auth - import session from browser
    auth_parser = subparsers.add_parser("auth", help="Import Reddit session from browser")
    auth_parser.add_argument("--browser", "-b",
                            choices=["firefox", "chrome", "chromium", "safari", "edge", "opera", "brave"],
                            help="Specific browser to use (auto-detects if not specified)")

    # Read post
    read_parser = subparsers.add_parser("read", help="Read a post with comments")
    read_parser.add_argument("url", help="Post URL or ID")
    read_parser.add_argument("--depth", type=int, default=1, help="Comment reply depth")
    read_parser.add_argument("--max-comments", type=int, default=25, help="Max comments")
    read_parser.add_argument("--json", action="store_true", help="Output JSON")

    # Listing
    listing_parser = subparsers.add_parser("listing", help="List subreddit posts")
    listing_parser.add_argument("subreddit", help="Subreddit name")
    listing_parser.add_argument("--limit", type=int, default=15, help="Number of posts")
    listing_parser.add_argument("--skip", type=int, default=0, help="Posts to skip")
    listing_parser.add_argument("--sort", default="hot", choices=["hot", "new", "top", "rising"])
    listing_parser.add_argument("--json", action="store_true", help="Output JSON")

    # Search
    search_parser = subparsers.add_parser("search", help="Search within subreddit")
    search_parser.add_argument("subreddit", help="Subreddit name")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=15, help="Max results")
    search_parser.add_argument("--sort", default="relevance")
    search_parser.add_argument("--time", default="all", dest="time_filter")
    search_parser.add_argument("--json", action="store_true", help="Output JSON")

    # Inbox
    inbox_parser = subparsers.add_parser("inbox", help="Check inbox")
    inbox_parser.add_argument("--unread", action="store_true", help="Unread only")
    inbox_parser.add_argument("--limit", type=int, default=25, help="Max messages")
    inbox_parser.add_argument("--json", action="store_true", help="Output JSON")

    # Comment
    comment_parser = subparsers.add_parser("comment", help="Post a comment")
    comment_parser.add_argument("thing_id", help="Thing ID to reply to")
    comment_parser.add_argument("text", help="Comment text")
    comment_parser.add_argument("--no-check", action="store_true", help="Skip duplicate check")

    # Submit
    submit_parser = subparsers.add_parser("submit", help="Submit a new post")
    submit_parser.add_argument("subreddit", help="Subreddit name")
    submit_parser.add_argument("title", help="Post title")
    submit_parser.add_argument("--text", help="Self post text")
    submit_parser.add_argument("--url", help="Link URL")

    # Vote
    vote_parser = subparsers.add_parser("vote", help="Vote on a post/comment")
    vote_parser.add_argument("thing_id", help="Thing ID")
    vote_parser.add_argument("direction", type=int, choices=[-1, 0, 1], help="-1/0/1")

    # Delete
    delete_parser = subparsers.add_parser("delete", help="Delete a post/comment")
    delete_parser.add_argument("thing_id", help="Thing ID to delete")

    args = parser.parse_args()

    if args.command == "auth":
        result = auth_from_browser(browser=args.browser)
        if result.get("success"):
            print(f"✓ Imported session from {result['browser']}")
            print(f"  Username: {result['username']}")
            print(f"  Saved to: {result['session_file']}")
        else:
            print(f"✗ {result.get('error')}", file=sys.stderr)
            print("\nManual setup instructions:", file=sys.stderr)
            print("1. Log into Reddit in your browser", file=sys.stderr)
            print("2. Open DevTools (F12) → Application → Cookies → reddit.com", file=sys.stderr)
            print("3. Copy the 'reddit_session' cookie value", file=sys.stderr)
            print(f"4. Create {SESSION_FILE} with:", file=sys.stderr)
            print('   {"cookies": {"reddit_session": "YOUR_COOKIE"}, "username": "YOUR_USERNAME"}', file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    client = RedditClient()

    if args.command == "read":
        result = client.read_post(args.url, depth=args.depth, max_comments=args.max_comments)
        if args.json:
            print(json.dumps(result, indent=2))
        elif result.get("success"):
            print(format_post(result["post"], result["comments"], args.depth))
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "listing":
        result = client.read_listing(args.subreddit, limit=args.limit, skip=args.skip, sort=args.sort)
        if args.json:
            print(json.dumps(result, indent=2))
        elif result.get("success"):
            print(format_listing(result["subreddit"], result["posts"]))
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "search":
        result = client.search(args.subreddit, args.query, limit=args.limit,
                               sort=args.sort, time_filter=args.time_filter)
        if args.json:
            print(json.dumps(result, indent=2))
        elif result.get("success"):
            print(format_listing(f"{result['subreddit']} (search: {result['query']})", result["posts"]))
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "inbox":
        result = client.inbox(limit=args.limit, unread_only=args.unread)
        if args.json:
            print(json.dumps(result, indent=2))
        elif result.get("success"):
            if not result["messages"]:
                print("No messages.")
            else:
                for msg in result["messages"]:
                    status = "[NEW] " if msg.get("new") else ""
                    print(f"\n{status}From u/{msg['author']}:")
                    if msg.get("subject"):
                        print(f"  Subject: {msg['subject']}")
                    body = msg.get('body', '')[:200]
                    print(f"  {body}{'...' if len(msg.get('body', '')) > 200 else ''}")
                    if msg.get("context"):
                        print(f"  Context: https://reddit.com{msg['context']}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "comment":
        result = client.comment(args.thing_id, args.text, check_existing=not args.no_check)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("success") else 1)

    elif args.command == "submit":
        result = client.submit(args.subreddit, args.title, text=args.text, url=args.url)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("success") else 1)

    elif args.command == "vote":
        result = client.vote(args.thing_id, args.direction)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("success") else 1)

    elif args.command == "delete":
        result = client.delete(args.thing_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
