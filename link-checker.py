#!/usr/bin/env python3

import sys
import requests
from requests.exceptions import SSLError
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import concurrent.futures
import time
import threading

REQUEST_DELAY = 1  # seconds between requests

def find_sitemap(url):
    candidates = [
        urljoin(url, '/sitemap.xml'),
        urljoin(url, '/sitemap_index.xml'),
        urljoin(url, '/sitemap/sitemap.xml'),
    ]
    for candidate in candidates:
        try:
            resp = requests.get(candidate, timeout=30)
            if resp.status_code == 200 and resp.content:
                return candidate
        except requests.RequestException:
            continue
    try:
        robots_url = urljoin(url, '/robots.txt')
        resp = requests.get(robots_url, timeout=30)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith('sitemap:'):
                    return line.split(':', 1)[1].strip()
    except requests.RequestException:
        pass
    return None

def parse_sitemap(sitemap_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; LinkChecker/1.0)'}
        resp = requests.get(sitemap_url, timeout=30, headers=headers)
        resp.raise_for_status()
        tree = ET.fromstring(resp.content)
    except Exception as e:
        print(f"Error parsing sitemap {sitemap_url}: {e}", file=sys.stderr)
        return []
    urls = []

    # Detect namespace (Yoast sometimes omits it)
    ns = ''
    if tree.tag.startswith('{'):
        ns = tree.tag.split('}')[0] + '}'

    # If sitemap index, recurse into each sitemap
    for sitemap in tree.findall(f'.//{ns}sitemap'):
        loc = sitemap.find(f'{ns}loc')
        if loc is not None and loc.text:
            urls.extend(parse_sitemap(loc.text))

    # If urlset, collect URLs
    for url in tree.findall(f'.//{ns}url'):
        loc = url.find(f'{ns}loc')
        if loc is not None and loc.text:
            urls.append(loc.text)

    return urls

def check_links(page_url):
    bad_links = []
    try:
        time.sleep(REQUEST_DELAY)  # Add delay before fetching the page
        resp = requests.get(page_url, timeout=30)
        if resp.status_code != 200:
            return bad_links
        soup = BeautifulSoup(resp.content, 'lxml')  # Use lxml parser
        for tag in soup.find_all(['a', 'img', 'link', 'script']):
            # Skip <link rel="preconnect"> and <link rel="dns-prefetch">
            if (
                tag.name == 'link'
                and tag.get('rel')
                and ('preconnect' in tag.get('rel') or 'dns-prefetch' in tag.get('rel'))
            ):
                continue
            attr = 'href' if tag.name in ['a', 'link'] else 'src'
            link = tag.get(attr)
            if link:
                # Only check http/https links
                if not (link.startswith('http://') or link.startswith('https://')):
                    continue
                # Ignore links to xmlrpc.php
                if 'xmlrpc.php' in link:
                    continue
                full_link = urljoin(page_url, link)
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (compatible; LinkChecker/1.0)'}
                    time.sleep(REQUEST_DELAY)  # Add delay before checking each link
                    start = time.time()
                    r = requests.head(full_link, allow_redirects=True, timeout=30, headers=headers)
                    elapsed = time.time() - start
                    code = r.status_code
                except SSLError:
                    continue
                except requests.RequestException as e:
                    code = 'ERR'
                    elapsed = None
                    print(f"Error checking link {full_link} on page {page_url}: {e}", file=sys.stderr)
                if code != 200 or (elapsed is not None and elapsed > 10):
                    bad_link = {
                        'code': code,
                        'page': page_url,
                        'broken_link': full_link,
                        'response_time': elapsed
                    }
                    rt = f" ({elapsed:.2f}s)" if elapsed is not None else ""
                    print(f"{code} {page_url} -> {full_link}{rt}")
                    bad_links.append(bad_link)
    except requests.RequestException:
        pass
    return bad_links

def crawl_site(start_url, max_pages=100):
    visited = set()
    to_visit = [start_url]
    found_pages = []

    headers = {'User-Agent': 'Mozilla/5.0 (compatible; LinkChecker/1.0)'}
    domain = urlparse(start_url).netloc

    while to_visit and len(found_pages) < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            resp = requests.get(url, timeout=30, headers=headers)
            if resp.status_code != 200:
                continue
            content_type = resp.headers.get('Content-Type', '')
            if 'html' not in content_type:
                continue  # Skip non-HTML pages
            found_pages.append(url)
            soup = BeautifulSoup(resp.content, 'lxml')
            for tag in soup.find_all('a'):
                link = tag.get('href')
                if link:
                    abs_link = urljoin(url, link)
                    link_domain = urlparse(abs_link).netloc
                    # Only add links with the same domain
                    if link_domain == domain and abs_link not in visited and abs_link not in to_visit:
                        to_visit.append(abs_link)
        except requests.RequestException:
            continue
    return found_pages

def main():
    try:
        if len(sys.argv) != 2:
            print("Usage: python link-checker.py <url>")
            sys.exit(1)
        url = sys.argv[1]
        sitemap_url = find_sitemap(url)
        if not sitemap_url:
            print("Sitemap not found. Crawling site for links...")
            pages = crawl_site(url)
        else:
            print(f"Using sitemap: {sitemap_url}")
            pages = parse_sitemap(sitemap_url)
        print(f"Found {len(pages)} pages to check.")

        all_bad_links = []
        # Reduce concurrency to avoid overload
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(check_links, pages)
            for bad_links in results:
                all_bad_links.extend(bad_links)

        if all_bad_links:
            print("Bad links found or slow responses:")
            for item in all_bad_links:
                rt = f" ({item['response_time']:.2f}s)" if item.get('response_time') is not None else ""
                print(f"{item['code']} {item['page']} -> {item['broken_link']}{rt}")
        else:
            print("All links returned 200 OK and responded quickly.")
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting gracefully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
