#!/usr/bin/env python3
"""MCP server for Reddit - read and write without API keys.

Copyright (C) 2026 Iris Thomas. Released under the Unlicense.
"""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .reddit import RedditClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reddit-mcp")

# Initialize server and client
server = Server("reddit-mcp")
client = RedditClient()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Reddit tools."""
    return [
        Tool(
            name="reddit_read",
            description="Read a Reddit post with comments. Returns post content, metadata, and threaded comments.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Post URL (e.g., https://reddit.com/r/sub/comments/xxx/title) or post ID"
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How many levels of comment replies to include (default: 1)",
                        "default": 1
                    },
                    "max_comments": {
                        "type": "integer",
                        "description": "Maximum number of comments to return (default: 25)",
                        "default": 25
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="reddit_listing",
            description="List posts from a subreddit. Returns titles, scores, and permalinks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subreddit": {
                        "type": "string",
                        "description": "Subreddit name without r/ prefix (e.g., 'LocalLLaMA')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of posts to return (default: 15)",
                        "default": 15
                    },
                    "skip": {
                        "type": "integer",
                        "description": "Number of posts to skip for pagination (default: 0)",
                        "default": 0
                    },
                    "sort": {
                        "type": "string",
                        "description": "Sort order: hot, new, top, rising (default: hot)",
                        "enum": ["hot", "new", "top", "rising"],
                        "default": "hot"
                    }
                },
                "required": ["subreddit"]
            }
        ),
        Tool(
            name="reddit_search",
            description="Search for posts within a subreddit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subreddit": {
                        "type": "string",
                        "description": "Subreddit name without r/ prefix"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 15)",
                        "default": 15
                    },
                    "sort": {
                        "type": "string",
                        "description": "Sort: relevance, hot, top, new, comments",
                        "default": "relevance"
                    },
                    "time_filter": {
                        "type": "string",
                        "description": "Time filter: all, hour, day, week, month, year",
                        "default": "all"
                    }
                },
                "required": ["subreddit", "query"]
            }
        ),
        Tool(
            name="reddit_inbox",
            description="Check Reddit inbox for replies, mentions, and messages. Requires authentication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum messages to retrieve (default: 25)",
                        "default": 25
                    },
                    "unread_only": {
                        "type": "boolean",
                        "description": "Only return unread messages (default: false)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="reddit_comment",
            description="Post a comment reply. Requires authentication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thing_id": {
                        "type": "string",
                        "description": "Fullname of thing to reply to (t3_xxx for post, t1_xxx for comment)"
                    },
                    "text": {
                        "type": "string",
                        "description": "Comment text (supports markdown)"
                    },
                    "check_existing": {
                        "type": "boolean",
                        "description": "Check if already replied to avoid duplicates (default: true)",
                        "default": True
                    }
                },
                "required": ["thing_id", "text"]
            }
        ),
        Tool(
            name="reddit_submit",
            description="Submit a new post to a subreddit. Requires authentication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subreddit": {
                        "type": "string",
                        "description": "Subreddit name without r/ prefix"
                    },
                    "title": {
                        "type": "string",
                        "description": "Post title"
                    },
                    "text": {
                        "type": "string",
                        "description": "Self post body text (for text posts)"
                    },
                    "url": {
                        "type": "string",
                        "description": "Link URL (for link posts, mutually exclusive with text)"
                    }
                },
                "required": ["subreddit", "title"]
            }
        ),
        Tool(
            name="reddit_vote",
            description="Vote on a post or comment. Requires authentication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thing_id": {
                        "type": "string",
                        "description": "Fullname of thing to vote on (t3_xxx or t1_xxx)"
                    },
                    "direction": {
                        "type": "integer",
                        "description": "Vote direction: 1 (upvote), -1 (downvote), 0 (remove vote)",
                        "enum": [-1, 0, 1]
                    }
                },
                "required": ["thing_id", "direction"]
            }
        ),
        Tool(
            name="reddit_delete",
            description="Delete your own post or comment. Requires authentication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thing_id": {
                        "type": "string",
                        "description": "Fullname of thing to delete (t3_xxx or t1_xxx)"
                    }
                },
                "required": ["thing_id"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a Reddit tool."""
    try:
        if name == "reddit_read":
            result = client.read_post(
                arguments["url"],
                depth=arguments.get("depth", 1),
                max_comments=arguments.get("max_comments", 25)
            )

        elif name == "reddit_listing":
            result = client.read_listing(
                arguments["subreddit"],
                limit=arguments.get("limit", 15),
                skip=arguments.get("skip", 0),
                sort=arguments.get("sort", "hot")
            )

        elif name == "reddit_search":
            result = client.search(
                arguments["subreddit"],
                arguments["query"],
                limit=arguments.get("limit", 15),
                sort=arguments.get("sort", "relevance"),
                time_filter=arguments.get("time_filter", "all")
            )

        elif name == "reddit_inbox":
            result = await client.async_inbox(
                limit=arguments.get("limit", 25),
                unread_only=arguments.get("unread_only", False)
            )

        elif name == "reddit_comment":
            result = await client.async_comment(
                arguments["thing_id"],
                arguments["text"],
                check_existing=arguments.get("check_existing", True)
            )

        elif name == "reddit_submit":
            result = await client.async_submit(
                arguments["subreddit"],
                arguments["title"],
                text=arguments.get("text"),
                url=arguments.get("url")
            )

        elif name == "reddit_vote":
            result = await client.async_vote(
                arguments["thing_id"],
                arguments["direction"]
            )

        elif name == "reddit_delete":
            result = await client.async_delete(arguments["thing_id"])

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.exception(f"Error in {name}")
        return [TextContent(
            type="text",
            text=json.dumps({"success": False, "error": str(e)}, indent=2)
        )]


async def _run():
    """Run the MCP server (async)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Entry point for the MCP server."""
    import asyncio
    asyncio.run(_run())


if __name__ == "__main__":
    main()
