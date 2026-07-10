import logging
import time
from typing import Any, Optional

import httpx

MERCARI_GRAPHQL_URL = "https://www.mercari.com/graphql/search"

logger = logging.getLogger(__name__)

SEARCH_QUERY = """
query SearchItems($query: String!, $pageSize: Int, $cursor: String, $status: String) {
  searchItems(query: $query, pageSize: $pageSize, cursor: $cursor, status: $status) {
    totalCount
    pageInfo {
      hasNextPage
      endCursor
    }
    items {
      id
      name
      price
      description
      condition
      status
      buyer {
        id
      }
      shippingPayer
      shippingFromArea
      createdAt
      updatedAt
      photos {
        id
        url
      }
      seller {
        id
        name
      }
      category {
        id
        name
      }
      sizes {
        id
        name
      }
      brand {
        id
        name
      }
    }
  }
}
"""


async def search_mercari(
    query: str,
    max_pages: int = 10,
    page_size: int = 100,
    status: str = "on_sale",
) -> list[dict]:
    all_items: list[dict] = []
    cursor: Optional[str] = None
    pages = 0

    async with httpx.AsyncClient(
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.mercari.com",
            "Referer": "https://www.mercari.com/search/",
        },
        timeout=15,
    ) as client:
        while pages < max_pages:
            variables: dict[str, Any] = {
                "query": query,
                "pageSize": page_size,
                "status": status,
            }
            if cursor:
                variables["cursor"] = cursor

            try:
                resp = await client.post(
                    MERCARI_GRAPHQL_URL,
                    json={"query": SEARCH_QUERY, "variables": variables},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Mercari search error: {e}")
                break

            if "error" in data:
                logger.error(f"Mercari API error: {data['error']}")
                break

            result = data.get("data", {}).get("searchItems", {})
            items = result.get("items", [])
            if not items:
                break

            all_items.extend(items)
            pages += 1

            page_info = result.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

            time.sleep(0.5)

    return all_items
