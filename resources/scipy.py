#!/usr/bin/env python3
"""
Scrape SciPy documentation and convert to Markdown format.
Optimized for SciPy's Sphinx-based documentation structure.
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
BASE_URL = "https://docs.scipy.org/doc/scipy/"
DOMAIN = "docs.scipy.org"
OUTPUT_DIR = "scipy_docs_markdown"
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
    SciPy has a hierarchical structure with tutorial/, reference/, building/, dev/.
    """
    print(f"Fetching navigation from {start_url}...")
    response = requests.get(start_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    urls = set()
    urls.add(start_url)  # Include the main page

    # Find all links
    for link in soup.find_all("a", href=True):
        href = link["href"]

        # Convert relative URLs to absolute
        if not href.startswith("http"):
            full_url = urljoin(start_url, href)
        else:
            full_url = href

        # Only include scipy docs
        if "docs.scipy.org/doc/scipy" not in full_url:
            continue

        # Remove fragments and query parameters
        parsed = urlparse(full_url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Skip non-HTML files
        if any(
            clean_url.endswith(ext)
            for ext in [
                ".pdf",
                ".zip",
                ".tar.gz",
                ".png",
                ".jpg",
                ".svg",
                ".py",
                ".ipynb",
            ]
        ):
            continue

        # Normalize URLs ending with /
        if clean_url.endswith("/") and clean_url != start_url:
            clean_url = clean_url.rstrip("/")

        # Only include .html files or directories
        if clean_url.endswith(".html") or "." not in clean_url.split("/")[-1]:
            urls.add(clean_url)

    # Also try to get URLs from common sections
    for section in ["tutorial", "reference", "building", "dev"]:
        section_url = urljoin(start_url, f"{section}/index.html")
        try:
            print(f"  Checking {section} section...")
            resp = requests.get(section_url, timeout=10)
            if resp.status_code == 200:
                urls.add(section_url)
                section_soup = BeautifulSoup(resp.content, "html.parser")
                for link in section_soup.find_all("a", href=True):
                    href = link["href"]
                    full_url = urljoin(section_url, href)
                    if "docs.scipy.org/doc/scipy" in full_url:
                        parsed = urlparse(full_url)
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        if (
                            clean_url.endswith(".html")
                            or "." not in clean_url.split("/")[-1]
                        ):
                            urls.add(clean_url)
                time.sleep(0.3)  # Be polite
        except Exception as e:
            print(f"  Warning: Could not fetch {section} section: {e}")

    print(f"Found {len(urls)} unique documentation pages")
    return sorted(urls)


def extract_main_content(soup):
    """Extract the main documentation content from Sphinx pages."""
    # Try common Sphinx/PyData theme content containers
    for selector in [
        "main",
        "article",
        'div[role="main"]',
        "div.bd-article",
        "div.body",
        "div.document",
        "section.bd-content",
    ]:
        content = soup.select_one(selector)
        if content:
            return content

    # Fallback
    return soup.find("body")


def clean_html_for_conversion(soup_element):
    """Clean up HTML before converting to markdown."""
    if not soup_element:
        return None

    # Remove script and style elements
    for element in soup_element.find_all(["script", "style", "noscript"]):
        element.decompose()

    # Remove common Sphinx/PyData theme elements
    for selector in [
        ".headerlink",
        ".sidebar",
        "nav",
        "header.bd-header",
        "footer",
        ".feedback",
        ".page-navigation",
        ".banner",
        ".cookie-notice",
        ".sphinxsidebar",
        ".related",
        ".bd-sidebar-primary",
        ".bd-sidebar-secondary",
        ".bd-toc",
        ".bd-footer",
        ".prev-next-area",
        "button",
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

        # Clean up title
        title_text = re.sub(r"\s*[-—|]\s*SciPy.*$", "", title_text)
        title_text = re.sub(r"\s*#\s*$", "", title_text)

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

    # Remove the base path
    base_path = "/doc/scipy/"
    if path.startswith(base_path):
        path = path[len(base_path) :]

    # Remove trailing slash
    path = path.rstrip("/")

    # If empty, use index
    if not path:
        return "index.md"

    # Remove .html and add .md
    if path.endswith(".html"):
        path = path[:-5]

    # If it ends with /index, just use the directory name
    if path.endswith("/index"):
        path = path[:-6]

    filename = path + ".md" if path else "index.md"

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

    # Organize by section
    sections = {
        "Root": [],
        "Tutorial": [],
        "Reference": [],
        "Building": [],
        "Development": [],
        "Other": [],
    }

    for url in urls:
        parsed = urlparse(url)
        path = parsed.path

        filename = url_to_filename(url, BASE_URL)

        if "/tutorial/" in path:
            sections["Tutorial"].append((url, filename))
        elif "/reference/" in path:
            sections["Reference"].append((url, filename))
        elif "/building/" in path:
            sections["Building"].append((url, filename))
        elif "/dev/" in path:
            sections["Development"].append((url, filename))
        elif path.endswith("/doc/scipy/") or path.endswith("/doc/scipy/index.html"):
            sections["Root"].append((url, filename))
        else:
            sections["Other"].append((url, filename))

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# SciPy Documentation Index\n\n")
        f.write(f"Scraped from: {BASE_URL}\n\n")
        f.write("SciPy v1.17.0 Documentation\n\n")
        f.write("---\n\n")

        for section_name in [
            "Root",
            "Tutorial",
            "Reference",
            "Building",
            "Development",
            "Other",
        ]:
            if sections[section_name]:
                f.write(f"## {section_name}\n\n")
                for url, filename in sorted(sections[section_name], key=lambda x: x[1]):
                    title = (
                        filename.replace(".md", "")
                        .replace("/", " / ")
                        .replace("_", " ")
                        .title()
                    )
                    f.write(f"- [{title}]({filename})\n")
                f.write("\n")

    print(f"\nCreated index at: {index_path}")


def create_structure_file(urls, output_dir):
    """Create a JSON file showing the documentation structure."""
    structure = {
        "base_url": BASE_URL,
        "version": "1.17.0",
        "total_pages": len(urls),
        "sections": {
            "tutorial": [],
            "reference": [],
            "building": [],
            "dev": [],
            "other": [],
        },
    }

    for url in urls:
        filename = url_to_filename(url, BASE_URL)
        entry = {"url": url, "filename": str(filename)}

        if "/tutorial/" in url:
            structure["sections"]["tutorial"].append(entry)
        elif "/reference/" in url:
            structure["sections"]["reference"].append(entry)
        elif "/building/" in url:
            structure["sections"]["building"].append(entry)
        elif "/dev/" in url:
            structure["sections"]["dev"].append(entry)
        else:
            structure["sections"]["other"].append(entry)

    structure_path = output_dir / "structure.json"
    with open(structure_path, "w", encoding="utf-8") as f:
        json.dump(structure, f, indent=2)

    print(f"Created structure file at: {structure_path}")


def main():
    """Main scraping function."""
    print("=" * 60)
    print("SciPy Documentation Scraper")
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
    print("  - INDEX.md: Complete list organized by section")
    print("  - structure.json: Machine-readable structure")
    print("\nDocumentation structure:")
    print("  - tutorial/*.md - User guide and tutorials")
    print("  - reference/*.md - Complete API reference")
    print("  - building/*.md - Build instructions")
    print("  - dev/*.md - Developer documentation")


if __name__ == "__main__":
    main()
