#!/usr/bin/env python3
"""
Scrape Google OR-Tools documentation and convert to Markdown format.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import html2text
import os
import time
from pathlib import Path
import re

# Configuration
BASE_URL = "https://developers.google.com/optimization/introduction"
DOMAIN = "developers.google.com"
OUTPUT_DIR = "ortools_docs_markdown"
DELAY_BETWEEN_REQUESTS = 0.5  # Be polite to the server


def setup_html2text():
    """Configure html2text converter for clean markdown."""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.body_width = 0  # Don't wrap text
    h.skip_internal_links = False
    return h


def get_all_doc_urls(start_url):
    """Extract all documentation URLs from the navigation."""
    print(f"Fetching navigation from {start_url}...")
    response = requests.get(start_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    urls = set()
    # Find all links in the page that are documentation links
    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Only get /optimization/ links
        if href.startswith("/optimization/"):
            full_url = urljoin(start_url, href)
            # Remove fragments and query parameters
            parsed = urlparse(full_url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            urls.add(clean_url)

    print(f"Found {len(urls)} unique documentation pages")
    return sorted(urls)


def extract_main_content(soup):
    """Extract the main documentation content from the page."""
    # Try to find the main content area
    # Google Developers docs typically have a main content area
    content = soup.find("main") or soup.find("article")

    if not content:
        # Fallback: try to find divs with common content classes
        content = soup.find("div", class_=re.compile(r"content|article|documentation"))

    if not content:
        # Last resort: get body but remove navigation and footer
        content = soup.find("body")
        if content:
            # Remove navigation, header, footer elements
            for element in content.find_all(["nav", "header", "footer"]):
                element.decompose()

    return content


def clean_html_for_conversion(soup_element):
    """Clean up HTML before converting to markdown."""
    if not soup_element:
        return None

    # Remove script and style elements
    for element in soup_element.find_all(["script", "style", "noscript"]):
        element.decompose()

    # Remove common unwanted elements
    for selector in [".feedback", ".page-navigation", ".banner", ".cookie-notice"]:
        for element in soup_element.select(selector):
            element.decompose()

    return soup_element


def scrape_page(url, converter):
    """Scrape a single page and convert to markdown."""
    print(f"Scraping: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # Get the page title
        title = soup.find("title")
        title_text = title.get_text().strip() if title else "Untitled"

        # Extract main content
        content = extract_main_content(soup)
        content = clean_html_for_conversion(content)

        if not content:
            print(f"  Warning: Could not find main content for {url}")
            return None, title_text

        # Convert to markdown
        markdown = converter.handle(str(content))

        # Add title and source URL at the top
        header = f"# {title_text}\n\n"
        header += f"**Source:** {url}\n\n"
        header += "---\n\n"

        markdown = header + markdown

        return markdown, title_text

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return None, None


def url_to_filename(url, base_url):
    """Convert URL to a safe filename."""
    # Remove the base domain
    parsed = urlparse(url)
    path = parsed.path

    # Remove leading /optimization/
    if path.startswith("/optimization/"):
        path = path[len("/optimization/") :]

    # Replace slashes with underscores, or use index if empty
    if not path or path == "/":
        filename = "index.md"
    else:
        # Remove trailing slash
        path = path.rstrip("/")
        # Replace slashes with double underscores for hierarchy
        filename = path.replace("/", "__") + ".md"

    return filename


def save_markdown(markdown, filepath):
    """Save markdown content to a file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"  Saved to: {filepath}")


def create_index(urls, output_dir):
    """Create an index.md file with links to all scraped pages."""
    index_path = output_dir / "INDEX.md"

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# OR-Tools Documentation Index\n\n")
        f.write(f"Scraped from: {BASE_URL}\n\n")
        f.write("---\n\n")

        # Group URLs by section
        sections = {}
        for url in urls:
            parsed = urlparse(url)
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) > 1:
                section = path_parts[1] if len(path_parts) > 1 else "root"
            else:
                section = "root"

            if section not in sections:
                sections[section] = []
            sections[section].append(url)

        # Write organized index
        for section in sorted(sections.keys()):
            f.write(f"## {section.replace('_', ' ').title()}\n\n")
            for url in sorted(sections[section]):
                filename = url_to_filename(url, BASE_URL)
                title = url.split("/")[-1].replace("_", " ").title() or "Home"
                f.write(f"- [{title}]({filename})\n")
            f.write("\n")

    print(f"\nCreated index at: {index_path}")


def main():
    """Main scraping function."""
    print("=" * 60)
    print("OR-Tools Documentation Scraper")
    print("=" * 60)

    # Setup
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(exist_ok=True)
    converter = setup_html2text()

    # Get all URLs
    urls = get_all_doc_urls(BASE_URL)

    if not urls:
        print("No URLs found. Exiting.")
        return

    print(f"\nWill scrape {len(urls)} pages into '{OUTPUT_DIR}' directory")
    print("=" * 60)

    # Scrape each page
    successful = 0
    failed = 0

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}]")

        markdown, title = scrape_page(url, converter)

        if markdown:
            filename = url_to_filename(url, BASE_URL)
            filepath = output_dir / filename
            save_markdown(markdown, filepath)
            successful += 1
        else:
            failed += 1

        # Be polite - don't hammer the server
        if i < len(urls):
            time.sleep(DELAY_BETWEEN_REQUESTS)

    # Create index
    create_index(urls, output_dir)

    # Summary
    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE")
    print("=" * 60)
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Output directory: {output_dir.absolute()}")
    print("\nCheck INDEX.md for a complete list of scraped pages.")


if __name__ == "__main__":
    main()
