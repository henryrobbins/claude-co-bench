#!/usr/bin/env python3
"""
Scrape Gurobi Optimizer documentation and convert to Markdown format.
Optimized for Sphinx-based documentation (Read the Docs).
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import html2text
import os
import time
from pathlib import Path
import re
import json

# Configuration
BASE_URL = "https://docs.gurobi.com/projects/optimizer/en/current/"
DOMAIN = "docs.gurobi.com"
OUTPUT_DIR = "gurobi_docs_markdown"
DELAY_BETWEEN_REQUESTS = 0.5  # Be polite to the server


def setup_html2text():
    """Configure html2text converter for clean markdown."""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.body_width = 0  # Don't wrap text
    h.skip_internal_links = False
    h.protect_links = True
    h.unicode_snob = True
    return h


def get_all_doc_urls(start_url):
    """
    Extract all documentation URLs from the navigation.
    Sphinx docs typically have a comprehensive sidebar navigation.
    """
    print(f"Fetching navigation from {start_url}...")
    response = requests.get(start_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    urls = set()
    base_path = "/projects/optimizer/en/current/"

    # Find all links in the navigation sidebar and content
    for link in soup.find_all("a", href=True):
        href = link["href"]

        # Handle relative URLs
        if href.startswith(base_path) or href.startswith("/projects/optimizer/"):
            full_url = urljoin(start_url, href)
        elif (
            href.startswith("concepts/")
            or href.startswith("features/")
            or href.startswith("reference/")
        ):
            full_url = urljoin(start_url, href)
        elif href.startswith("./") or (
            not href.startswith("http") and not href.startswith("#")
        ):
            full_url = urljoin(start_url, href)
        else:
            continue

        # Clean up the URL
        parsed = urlparse(full_url)

        # Only include Gurobi optimizer docs
        if "docs.gurobi.com/projects/optimizer" not in full_url:
            continue

        # Remove fragments and query parameters
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Skip non-HTML pages
        if any(
            clean_url.endswith(ext)
            for ext in [".pdf", ".zip", ".tar.gz", ".png", ".jpg", ".svg"]
        ):
            continue

        # Ensure it ends with .html or is a directory
        if not clean_url.endswith(".html") and not clean_url.endswith("/"):
            if (
                "." not in clean_url.split("/")[-1]
            ):  # No extension, might be a directory
                if not clean_url.endswith("/"):
                    clean_url += "/"

        urls.add(clean_url)

    print(f"Found {len(urls)} unique documentation pages")
    return sorted(urls)


def extract_main_content(soup):
    """Extract the main documentation content from Sphinx pages."""
    # Sphinx typically uses these structures
    content = None

    # Try common Sphinx content containers
    for selector in [
        'div[role="main"]',
        "main",
        "article",
        "div.document",
        "div.body",
        "section",
    ]:
        content = soup.select_one(selector)
        if content:
            break

    if not content:
        # Fallback
        content = soup.find("body")

    return content


def clean_html_for_conversion(soup_element):
    """Clean up HTML before converting to markdown."""
    if not soup_element:
        return None

    # Remove script and style elements
    for element in soup_element.find_all(["script", "style", "noscript"]):
        element.decompose()

    # Remove common Sphinx/Read the Docs elements we don't want
    for selector in [
        ".headerlink",  # Sphinx header anchors
        ".sidebar",
        "nav",
        "header",
        "footer",
        ".feedback",
        ".page-navigation",
        ".banner",
        ".cookie-notice",
        ".sphinxsidebar",
        ".related",
        ".rtd-footer-container",
        ".ethical-rtd",
        ".rst-versions",
    ]:
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

        # Remove common suffixes from title
        title_text = re.sub(r"\s*[-—|]\s*Gurobi.*$", "", title_text)

        # Extract main content
        content = extract_main_content(soup)
        content = clean_html_for_conversion(content)

        if not content:
            print(f"  Warning: Could not find main content for {url}")
            return None, title_text

        # Convert to markdown
        markdown = converter.handle(str(content))

        # Clean up the markdown
        # Remove excessive blank lines
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)

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
    """Convert URL to a safe filename maintaining directory structure."""
    parsed = urlparse(url)
    path = parsed.path

    # Remove base path
    base_path = "/projects/optimizer/en/current/"
    if path.startswith(base_path):
        path = path[len(base_path) :]

    # Remove trailing slash
    path = path.rstrip("/")

    # If empty or just index, use index.md
    if not path or path == "index.html":
        return "index.md"

    # Remove .html extension and replace with .md
    if path.endswith(".html"):
        path = path[:-5]

    # Replace slashes with directory separators
    filename = path + ".md"

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
        f.write("# Gurobi Optimizer Documentation Index\n\n")
        f.write(f"Scraped from: {BASE_URL}\n\n")
        f.write(f"Documentation for Gurobi Optimizer Reference Manual\n\n")
        f.write("---\n\n")

        # Organize by section
        sections = {}
        for url in urls:
            parsed = urlparse(url)
            path_parts = [p for p in parsed.path.split("/") if p and p != "index.html"]

            # Find the section (concepts, features, reference, etc.)
            section = "Root"
            for part in path_parts:
                if part in ["concepts", "features", "reference", "examples"]:
                    section = part.title()
                    break

            if section not in sections:
                sections[section] = []
            sections[section].append(url)

        # Write organized index
        for section in sorted(sections.keys()):
            f.write(f"## {section}\n\n")
            for url in sorted(sections[section]):
                filename = url_to_filename(url, BASE_URL)
                # Get a nice title from the URL
                title = (
                    url.split("/")[-1]
                    .replace(".html", "")
                    .replace("_", " ")
                    .replace("-", " ")
                    .title()
                )
                if not title:
                    title = "Home"
                f.write(f"- [{title}]({filename})\n")
            f.write("\n")

    print(f"\nCreated index at: {index_path}")


def create_structure_file(urls, output_dir):
    """Create a JSON file showing the documentation structure."""
    structure = {"base_url": BASE_URL, "total_pages": len(urls), "pages": []}

    for url in urls:
        filename = url_to_filename(url, BASE_URL)
        structure["pages"].append({"url": url, "filename": str(filename)})

    structure_path = output_dir / "structure.json"
    with open(structure_path, "w", encoding="utf-8") as f:
        json.dump(structure, f, indent=2)

    print(f"Created structure file at: {structure_path}")


def main():
    """Main scraping function."""
    print("=" * 60)
    print("Gurobi Optimizer Documentation Scraper")
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

    # Create index and structure files
    create_index(urls, output_dir)
    create_structure_file(urls, output_dir)

    # Summary
    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE")
    print("=" * 60)
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Output directory: {output_dir.absolute()}")
    print("\nFiles created:")
    print("  - INDEX.md: Complete list of all pages organized by section")
    print("  - structure.json: Machine-readable documentation structure")
    print("\nDocumentation preserves directory structure:")
    print("  - concepts/*.md")
    print("  - features/*.md")
    print("  - reference/*.md")


if __name__ == "__main__":
    main()
