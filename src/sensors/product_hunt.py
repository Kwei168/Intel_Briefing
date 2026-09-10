"""
Product Hunt Sensor - Fetches trending products from Product Hunt.
Uses the official GraphQL API (requires API token for full access).
Falls back to scraping if no token available.
"""
import sys
import os
import re
import json
import html as html_mod
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

import httpx

@dataclass
class PHProduct:
    """A Product Hunt product."""
    name: str
    tagline: str
    url: str
    votes_count: int
    website: Optional[str]
    topics: List[str]
    maker_name: str = "Unknown"
    maker_twitter: Optional[str] = None
    thumbnail_url: Optional[str] = None

# Use unified config layer
from src.config import cfg


ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _parse_rss_products(xml_text: str, limit: int = 10) -> List[PHProduct]:
    """Parse Product Hunt's public Atom feed using only verified URLs."""
    root = ET.fromstring(xml_text)
    products = []
    for entry in root.findall(f".//{ATOM_NS}entry")[:limit]:
        title = entry.findtext(f"{ATOM_NS}title", default="").strip()
        summary = entry.findtext(f"{ATOM_NS}summary", default="").strip()
        # Also check <content> element as fallback for tagline
        content_text = entry.findtext(f"{ATOM_NS}content", default="").strip()
        link = ""
        for link_el in entry.findall(f"{ATOM_NS}link"):
            if link_el.get("rel", "alternate") == "alternate" and link_el.get("href"):
                link = link_el.get("href")
                break
        if not link:
            continue
        published = entry.findtext(f"{ATOM_NS}published", default="")
        # Extract tagline: strip HTML, take first meaningful line
        raw_tagline = html_mod.unescape(re.sub(r"<[^>]+>", "", summary))
        if not raw_tagline or len(raw_tagline.strip()) < 3:
            # Fallback to <content> element
            raw_tagline = html_mod.unescape(re.sub(r"<[^>]+>", "", content_text))
        # Take first line/sentence as tagline (max 200 chars)
        raw_tagline = raw_tagline.strip().split("\n")[0].strip()[:200]
        products.append(PHProduct(
            name=html_mod.unescape(title),
            tagline=raw_tagline,
            url=link,
            votes_count=0,
            website=None,
            topics=[],
            maker_name="Unknown",
            maker_twitter=None,
        ))
    return products


def _fetch_via_rss(limit: int) -> List[PHProduct]:
    """Fetch Product Hunt's official public Atom feed as a no-token fallback."""
    print("    (Using Product Hunt official Atom RSS fallback)")
    resp = httpx.get(
        "https://www.producthunt.com/feed",
        headers={"User-Agent": "Intel-Briefing/2.0"},
        timeout=15,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return _parse_rss_products(resp.text, limit)


def fetch_trending_products(limit: int = 10) -> List[PHProduct]:
    """Fetch trending products from Product Hunt."""
    print(f"  → Fetching top {limit} products from Product Hunt...")
    
    token = cfg.producthunt_token
    
    if token:
        print("    (Using Official API Token)")
        try:
            return _fetch_via_api(token, limit)
        except Exception as e:
            print(f"    ⚠️ API Fetch Failed: {e}. Falling back to hydration...")
            
    # Fallback to hydration
    print("    (No API token found or API failed, using web scraping fallback)")
    return _fetch_via_hydration(limit)

def _fetch_via_api(token: str, limit: int) -> List[PHProduct]:
    """Fetch via official GraphQL API."""
    query = """
    query {
      posts(first: %d, order: VOTES) {
        edges {
          node {
            name
            tagline
            url
            votesCount
            website
            slug
            topics {
              edges {
                node {
                  name
                }
              }
            }
            user {
              name
              twitterUsername
            }
          }
        }
      }
    }
    """ % limit
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    resp = httpx.post(
        "https://api.producthunt.com/v2/api/graphql",
        json={"query": query},
        headers=headers,
        timeout=15
    )
    
    data = resp.json()
    products = []
    
    if "data" in data and "posts" in data["data"]:
        for edge in data["data"]["posts"]["edges"]:
            node = edge["node"]
            topics = [t["node"]["name"] for t in node.get("topics", {}).get("edges", [])]
            user = node.get("user", {}) or {}
            
            slug = node.get("slug")
            ph_url = f"https://www.producthunt.com/posts/{slug}" if slug else node["url"]
            
            products.append(PHProduct(
                name=node["name"],
                tagline=node["tagline"],
                url=ph_url,
                votes_count=node["votesCount"],
                website=node.get("website"),
                topics=topics[:3],
                maker_name=user.get("name", "Unknown"),
                maker_twitter=user.get("twitterUsername")
            ))
    
    return products

def _fetch_via_hydration(limit: int) -> List[PHProduct]:
    """
    Advanced Scraping: Extracts data from Next.js hydration state.
    No API token required.
    """
    print("    (Using Next.js hydration extraction - No Token Needed)")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        resp = httpx.get("https://www.producthunt.com/", headers=headers, timeout=15, follow_redirects=True)
        html = resp.text
        
        # 1. Extract __NEXT_DATA__ JSON blob
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html)
        if not match:
            print("    [WARN] Could not find __NEXT_DATA__ on page; trying official RSS.")
            return _fetch_via_rss(limit)
            
        data = json.loads(match.group(1))
        
        # 2. Navigate to Apollo State
        apollo_state = data.get("props", {}).get("pageProps", {}).get("apolloState", {})
        
        products = []
        all_posts = []
        
        for key, value in apollo_state.items():
            if key.startswith("Post:") and isinstance(value, dict):
                if "name" in value and "votesCount" in value:
                    all_posts.append(value)
        
        all_posts.sort(key=lambda x: x.get("votesCount", 0), reverse=True)
        
        for post in all_posts[:limit]:
            maker_name = "Unknown"
            maker_twitter = None
            
            user_ref = post.get("user")
            if user_ref and "__ref" in user_ref:
                user_obj = apollo_state.get(user_ref["__ref"], {})
                maker_name = user_obj.get("name", "Unknown")
                maker_twitter = user_obj.get("twitterUsername")
            
            slug = post.get("slug")
            ph_url = f"https://www.producthunt.com/posts/{slug}" if slug else None
            
            thumbnail_url = None
            thumbnail_node = post.get("thumbnail", {})
            if thumbnail_node and "url" in thumbnail_node:
                thumbnail_url = thumbnail_node["url"]
            
            products.append(PHProduct(
                name=post.get("name", "Unknown"),
                tagline=post.get("tagline", ""),
                url=ph_url or "https://www.producthunt.com/",
                votes_count=post.get("votesCount", 0),
                website=post.get("website"), 
                topics=[], 
                maker_name=maker_name,
                maker_twitter=maker_twitter,
                thumbnail_url=thumbnail_url
            ))
            
        return products
        
    except Exception as e:
        print(f"    [WARN] Hydration extraction failed: {e}; trying official RSS.")
        try:
            return _fetch_via_rss(limit)
        except Exception as rss_error:
            print(f"    [WARN] Product Hunt RSS fallback failed: {rss_error}")
            return []

def _fetch_via_scraping_fallback(limit: int) -> List[PHProduct]:
    """Fallback: Use Grok Sensor to fetch Product Hunt data."""
    return _fetch_via_grok(limit)

def _fetch_via_grok(limit: int) -> List[PHProduct]:
    """
    Use Grok (xAI) to fetch Product Hunt trending products.
    This bypasses Cloudflare by using Grok's web access capabilities.
    """
    try:
        from .x_grok_sensor import fetch_grok_intel
    except ImportError:
        # Fallback for direct execution
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from x_grok_sensor import fetch_grok_intel
    
    print("    (Using Grok Sensor as Cloudflare bypass)")
    
    prompt = f"""Access Product Hunt (producthunt.com) and find the top {limit} trending products today.
For each product, provide:
1. Product name
2. One-line tagline/description
3. Vote count (approximate)
4. Maker name if visible

Format your response as a JSON array like this:
[
  {{"name": "ProductName", "tagline": "Short description", "votes_count": 500, "maker_name": "John Doe"}},
  ...
]

ONLY output the JSON array, no other text. If you cannot access Product Hunt, return an empty array: []"""

    try:
        response = fetch_grok_intel("Product Hunt Trending", override_prompt=prompt)
        
        # Try to parse JSON from response
        import re
        # Find JSON array in response
        json_match = re.search(r'\[[\s\S]*?\]', response)
        if json_match:
            data = json.loads(json_match.group(0))
            products = []
            for item in data[:limit]:
                # NOTE: URL is a best-guess slug, not from PH API.
                # Marked as unverified for downstream link-checker.
                slug = item.get('name', '').lower().replace(' ', '-')
                products.append(PHProduct(
                    name=item.get("name", "Unknown"),
                    tagline=item.get("tagline", ""),
                    url=f"https://www.producthunt.com/posts/{slug}",
                    votes_count=item.get("votes_count", 0),
                    website="⚠️ unverified (Grok fallback)",
                    topics=["grok-fallback"],
                    maker_name=item.get("maker_name", "Unknown"),
                    maker_twitter=None
                ))
            print(f"    ✅ Grok returned {len(products)} products")
            return products
        else:
            print("    ⚠️ Grok response did not contain valid JSON")
            return []
    except Exception as e:
        print(f"    ⚠️ Grok Sensor failed: {e}")
        return []

def print_products(products: List[PHProduct]):
    """Print products in a readable format."""
    print(f"\n{'='*60}")
    print(f"  🚀 Product Hunt Trending")
    print(f"{'='*60}\n")
    
    for i, p in enumerate(products, 1):
        print(f"{i}. {p.name}")
        print(f"   {p.tagline}")
        print(f"   ⬆️ {p.votes_count} votes | 👷 {p.maker_name} (@{p.maker_twitter or 'N/A'})")
        print(f"   🔗 {p.url}")
        print()

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    products = fetch_trending_products(limit)
    if products:
        print_products(products)
    else:
        print("No products found.")
