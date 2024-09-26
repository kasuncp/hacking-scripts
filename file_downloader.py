#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse, unquote
from tqdm import tqdm

def create_directory_structure(url, base_url, download_folder):
    parsed_url = urlparse(url)
    parsed_base_url = urlparse(base_url)
    relative_path = unquote(parsed_url.path.lstrip('/'))
    
    if parsed_url.netloc != parsed_base_url.netloc:
        relative_path = os.path.join(parsed_url.netloc, relative_path)
    
    # Split the path into directory and filename
    dir_path, filename = os.path.split(relative_path)
    
    # Create the full directory path
    full_dir_path = os.path.join(download_folder, dir_path)
    os.makedirs(full_dir_path, exist_ok=True)
    
    return full_dir_path, filename

def download_file(url, base_url, download_folder):
    try:
        dir_path, filename = create_directory_structure(url, base_url, download_folder)
        local_filename = os.path.join(dir_path, filename)
        
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            with open(local_filename, 'wb') as f, tqdm(
                desc=filename,
                total=total_size,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
            ) as progress_bar:
                for data in r.iter_content(chunk_size=1024):
                    size = f.write(data)
                    progress_bar.update(size)
        return local_filename
    except Exception as e:
        print(f"Error downloading {url}: {str(e)}")
        return None

def crawl_and_download(base_url, extensions, download_folder):
    visited = set()
    to_visit = [base_url]

    while to_visit:
        current_url = to_visit.pop(0)
        if current_url in visited:
            continue

        visited.add(current_url)
        print(f"Visiting: {current_url}")

        try:
            response = requests.get(current_url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find and download files with the specified extensions
            for link in soup.find_all('a'):
                href = link.get('href')
                if href:
                    full_url = urljoin(current_url, href)
                    if any(full_url.endswith(ext) for ext in extensions):
                        print(f"Downloading: {full_url}")
                        download_file(full_url, base_url, download_folder)

            # Add new links to visit
            for link in soup.find_all('a'):
                href = link.get('href')
                if href:
                    full_url = urljoin(current_url, href)
                    if urlparse(full_url).netloc == urlparse(base_url).netloc and full_url not in visited:
                        to_visit.append(full_url)

        except Exception as e:
            print(f"Error processing {current_url}: {str(e)}")

if __name__ == "__main__":
    base_url = input("Enter the base URL: ")
    extensions_input = input("Enter the file extensions to download (comma-separated, e.g., .pdf,.txt,.docx): ")
    extensions = [ext.strip() for ext in extensions_input.split(',')]
    download_folder = input("Enter the download folder path: ")

    if not os.path.exists(download_folder):
        os.makedirs(download_folder)

    crawl_and_download(base_url, extensions, download_folder)
    print("Crawling and downloading completed.")
