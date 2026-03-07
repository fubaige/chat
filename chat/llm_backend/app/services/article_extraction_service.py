"""
Article extraction service for summarizing web articles.

Based on the article-summary-skill project:
https://github.com/AleksChen/article-summary-skill
"""

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class ExtractedArticle:
    """Extracted article data"""
    url: str
    title: str
    author: str
    publish_time: str
    content: str
    source_type: str
    extraction_method: str
    fetched_at: str


def _fetch_html(url: str, timeout: int = 20) -> str:
    """Fetch HTML content from URL"""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def _normalize_text(text: str) -> str:
    """Normalize extracted text"""
    import html
    text = html.unescape(text)
    text = text.replace("\u200b", "").replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_html_tags(raw: str) -> str:
    """Remove HTML tags while preserving structure"""
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|h[1-6]|li|section|article|blockquote)>", "\n", raw)
    raw = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    return _normalize_text(raw)


def _extract_meta(html_text: str, prop: str) -> str:
    """Extract meta tag content"""
    patterns = [
        rf'(?is)<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
        rf'(?is)<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']{re.escape(prop)}["\']',
        rf'(?is)<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
        rf'(?is)<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']{re.escape(prop)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            return _normalize_text(match.group(1))
    return ""


def _extract_title(html_text: str) -> str:
    """Extract page title"""
    title = _extract_meta(html_text, "og:title")
    if title:
        return title
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    if match:
        return _normalize_text(match.group(1))
    return ""


def _extract_largest_block(html_text: str, patterns: List[str]) -> str:
    """Extract the largest text block matching patterns"""
    blocks: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html_text, flags=re.IGNORECASE | re.DOTALL):
            group_index = match.lastindex or 1
            text = _remove_html_tags(match.group(group_index))
            if len(text) > 80:
                blocks.append(text)
    if not blocks:
        return ""
    return max(blocks, key=len)


def _extract_js_string(html_text: str, key: str) -> str:
    """Extract JavaScript variable value"""
    patterns = [
        rf"""(?is)\b{re.escape(key)}\b\s*[:=]\s*["'](.*?)["']\s*[;,]""",
        rf"""(?is)\bvar\s+{re.escape(key)}\s*=\s*["'](.*?)["']\s*;""",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            return _normalize_text(match.group(1))
    return ""


def _extract_js_numeric_time(html_text: str) -> str:
    """Extract Unix timestamp from JavaScript"""
    match = re.search(r"(?is)\b(?:publish_time|ct)\b\s*[:=]\s*['\"]?(\d{10})['\"]?\s*[;,]", html_text)
    if not match:
        return ""
    try:
        ts = int(match.group(1))
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except Exception:
        return ""


def _extract_tag_text(html_text: str, tag: str, attr: str, attr_keyword: str) -> str:
    """Extract text from specific HTML tag"""
    pattern = (
        rf'(?is)<{tag}[^>]+{attr}=["\'][^"\']*{re.escape(attr_keyword)}[^"\']*["\'][^>]*>'
        rf"(.*?)</{tag}>"
    )
    match = re.search(pattern, html_text)
    if not match:
        return ""
    return _remove_html_tags(match.group(1))


def _extract_wechat(html_text: str, url: str) -> ExtractedArticle:
    """Extract article from WeChat MP (微信公众号)"""
    title = _extract_meta(html_text, "og:title") or \
            _extract_js_string(html_text, "msg_title") or \
            _extract_tag_text(html_text, "h1", "id", "activity-name") or \
            _extract_title(html_text)

    author = _extract_js_string(html_text, "nickname") or \
             _extract_js_string(html_text, "user_name") or \
             _extract_tag_text(html_text, "strong", "id", "js_name")

    publish_time = _extract_js_numeric_time(html_text) or \
                   _extract_js_string(html_text, "publish_time") or \
                   _extract_tag_text(html_text, "em", "id", "publish_time")

    content = _extract_largest_block(
        html_text,
        patterns=[
            r'(?is)<div[^>]+id=["\']js_content["\'][^>]*>(.*?)</div>',
            r'(?is)<section[^>]+class=["\'][^"\']*rich_media_content[^"\']*["\'][^>]*>(.*?)</section>',
        ],
    )

    method = "wechat-dom"
    if not content:
        content = _extract_generic_content(html_text)
        method = "generic-fallback"

    return _build_article(
        url=url,
        title=title,
        author=author,
        publish_time=publish_time,
        content=content,
        source_type="wechat",
        extraction_method=method,
    )


def _extract_generic_content(html_text: str) -> str:
    """Extract content from generic web pages"""
    content = _extract_largest_block(
        html_text,
        patterns=[
            r"(?is)<article[^>]*>(.*?)</article>",
            r'(?is)<main[^>]*>(.*?)</main>',
            r'(?is)<div[^>]+class=["\'][^"\']*(?:content|article|post|entry|rich-text)[^"\']*["\'][^>]*>(.*?)</div>',
            r'(?is)<section[^>]+class=["\'][^"\']*(?:content|article|post)[^"\']*["\'][^>]*>(.*?)</section>',
        ],
    )
    if content:
        return content
    body = _extract_largest_block(html_text, patterns=[r"(?is)<body[^>]*>(.*?)</body>"])
    return body


def _extract_generic(html_text: str, url: str) -> ExtractedArticle:
    """Extract article from generic web page"""
    title = _extract_title(html_text)

    author = _extract_meta(html_text, "author") or \
             _extract_meta(html_text, "article:author")

    publish_time = _extract_meta(html_text, "article:published_time") or \
                   _extract_meta(html_text, "publishdate") or \
                   _extract_meta(html_text, "pubdate")

    content = _extract_generic_content(html_text)

    return _build_article(
        url=url,
        title=title,
        author=author,
        publish_time=publish_time,
        content=content,
        source_type="generic",
        extraction_method="generic-dom",
    )


def _build_article(
    url: str,
    title: str,
    author: str,
    publish_time: str,
    content: str,
    source_type: str,
    extraction_method: str,
) -> ExtractedArticle:
    """Build ExtractedArticle dataclass"""
    return ExtractedArticle(
        url=url,
        title=title or "Untitled",
        author=author or "",
        publish_time=publish_time or "",
        content=_normalize_text(content),
        source_type=source_type,
        extraction_method=extraction_method,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
    )


def extract_from_url(url: str, timeout: int = 20) -> ExtractedArticle:
    """Extract article from URL

    Args:
        url: Article URL
        timeout: HTTP timeout in seconds

    Returns:
        ExtractedArticle with title, content, etc.
    """
    html_text = _fetch_html(url, timeout=timeout)
    host = (urlparse(url).hostname or "").lower()
    if "mp.weixin.qq.com" in host:
        return _extract_wechat(html_text, url)
    return _extract_generic(html_text, url)


def extract_articles(urls: List[str], timeout: int = 20) -> tuple[List[ExtractedArticle], List[str]]:
    """Extract articles from multiple URLs

    Args:
        urls: List of article URLs
        timeout: HTTP timeout in seconds

    Returns:
        Tuple of (successful extractions, errors)
    """
    articles: List[ExtractedArticle] = []
    errors: List[str] = []

    for url in urls:
        try:
            article = extract_from_url(url, timeout=timeout)
            articles.append(article)
        except HTTPError as err:
            errors.append(f"{url} -> fetch failed: {err}")
        except (URLError, TimeoutError) as err:
            errors.append(f"{url} -> fetch failed: {err}")
        except Exception as err:
            errors.append(f"{url} -> parse failed: {err}")

    return articles, errors


def extract_article_content(url: str, timeout: int = 20) -> Optional[dict]:
    """Extract article and return as dictionary

    Args:
        url: Article URL
        timeout: HTTP timeout in seconds

    Returns:
        Dictionary with article data or None if extraction fails
    """
    try:
        article = extract_from_url(url, timeout=timeout)
        return asdict(article)
    except Exception as e:
        logger.error(f"Failed to extract article from {url}: {e}")
        return None


def format_article_summary(article: ExtractedArticle) -> str:
    """Format extracted article for embedding in user message

    Args:
        article: Extracted article

    Returns:
        Formatted markdown string
    """
    parts = [
        f"## {article.title}",
        f"- 来源：{article.url}",
        f"- 作者：{article.author or '未知'}",
        f"- 发布时间：{article.publish_time or '未知'}",
        "",
        "### 文章内容",
        article.content or "(empty)",
    ]
    return "\n".join(parts)
