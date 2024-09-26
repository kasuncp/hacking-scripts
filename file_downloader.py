#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse, unquote
from tqdm import tqdm
import pickle
from colorama import init, Fore, Style
import threading
from queue import Queue

# Initialize colorama for cross-platform color support
init()

def print_banner():
    banner = f"""{Fore.CYAN}
███████╗██╗  ██╗██╗  ██╗██████╗  ██████╗ ██╗    ██╗                                   
██╔════╝██║  ██║██║  ██║██╔══██╗██╔═████╗██║    ██║                                   
███████╗███████║███████║██║  ██║██║██╔██║██║ █╗ ██║                                   
╚════██║██╔══██║╚════██║██║  ██║████╔╝██║██║███╗██║                                   
███████║██║  ██║     ██║██████╔╝╚██████╔╝╚███╔███╔╝                                   
╚══════╝╚═╝  ╚═╝     ╚═╝╚═════╝  ╚═════╝  ╚══╝╚══╝                                    
                                                                                      
██████╗  ██████╗ ██╗    ██╗███╗   ██╗██╗      ██████╗  █████╗ ██████╗ ███████╗██████╗ 
██╔══██╗██╔═══██╗██║    ██║████╗  ██║██║     ██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
██║  ██║██║   ██║██║ █╗ ██║██╔██╗ ██║██║     ██║   ██║███████║██║  ██║█████╗  ██████╔╝
██║  ██║██║   ██║██║███╗██║██║╚██╗██║██║     ██║   ██║██╔══██║██║  ██║██╔══╝  ██╔══██╗
██████╔╝╚██████╔╝╚███╔███╔╝██║ ╚████║███████╗╚██████╔╝██║  ██║██████╔╝███████╗██║  ██║
╚═════╝  ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝
{Fore.GREEN}[ Multi-threaded Path-Respecting Edition ]{Style.RESET_ALL}
    """
    print(banner)

def create_directory_structure(url, base_url, download_folder):
    parsed_url = urlparse(url)
    parsed_base_url = urlparse(base_url)
    relative_path = unquote(parsed_url.path.lstrip('/'))
    
    if parsed_url.netloc != parsed_base_url.netloc:
        relative_path = os.path.join(parsed_url.netloc, relative_path)
    
    dir_path, filename = os.path.split(relative_path)
    full_dir_path = os.path.join(download_folder, dir_path)
    os.makedirs(full_dir_path, exist_ok=True)
    
    return full_dir_path, filename

def download_file(url, base_url, download_folder, session):
    try:
        dir_path, filename = create_directory_structure(url, base_url, download_folder)
        local_filename = os.path.join(dir_path, filename)
        
        if os.path.exists(local_filename):
            r = session.head(url)
            remote_size = int(r.headers.get('content-length', 0))
            local_size = os.path.getsize(local_filename)
            if local_size == remote_size:
                print(f"{Fore.YELLOW}Skipping {filename} (already downloaded){Style.RESET_ALL}")
                return local_filename
        
        mode = 'ab' if os.path.exists(local_filename) else 'wb'
        headers = {}
        if os.path.exists(local_filename):
            local_size = os.path.getsize(local_filename)
            headers['Range'] = f'bytes={local_size}-'
        
        with session.get(url, stream=True, headers=headers) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            if 'Range' in headers:
                total_size += local_size
            
            with open(local_filename, mode) as f, tqdm(
                desc=filename,
                initial=local_size if 'Range' in headers else 0,
                total=total_size,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
                bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.GREEN, Style.RESET_ALL)
            ) as progress_bar:
                for data in r.iter_content(chunk_size=8192):
                    size = f.write(data)
                    progress_bar.update(size)
        return local_filename
    except Exception as e:
        print(f"{Fore.RED}Error downloading {url}: {str(e)}{Style.RESET_ALL}")
        return None

def download_worker(queue, base_url, download_folder, session):
    while True:
        url = queue.get()
        if url is None:
            break
        download_file(url, base_url, download_folder, session)
        queue.task_done()

def is_valid_url(url, base_url):
    parsed_url = urlparse(url)
    parsed_base_url = urlparse(base_url)
    
    # Check if the URL is from the same domain
    if parsed_url.netloc != parsed_base_url.netloc:
        return False
    
    # Check if the URL path starts with the base URL path
    if not parsed_url.path.startswith(parsed_base_url.path):
        return False
    
    return True

def crawl_and_download(base_url, extensions, download_folder, num_threads=5):
    session = requests.Session()
    visited = set()
    to_visit = [base_url]
    downloaded_files = set()
    download_queue = Queue()
    
    progress_file = os.path.join(download_folder, 'crawl_progress.pkl')
    if os.path.exists(progress_file):
        with open(progress_file, 'rb') as f:
            visited, to_visit, downloaded_files = pickle.load(f)
        print(f"{Fore.MAGENTA}Resuming from previous session{Style.RESET_ALL}")

    # Start worker threads
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=download_worker, args=(download_queue, base_url, download_folder, session))
        t.start()
        threads.append(t)

    try:
        while to_visit:
            current_url = to_visit.pop(0)
            if current_url in visited or not is_valid_url(current_url, base_url):
                continue

            visited.add(current_url)
            print(f"{Fore.CYAN}Visiting: {current_url}{Style.RESET_ALL}")

            try:
                response = session.get(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                for link in soup.find_all('a'):
                    href = link.get('href')
                    if href:
                        full_url = urljoin(current_url, href)
                        if is_valid_url(full_url, base_url):
                            if any(full_url.endswith(ext) for ext in extensions):
                                if full_url not in downloaded_files:
                                    print(f"{Fore.GREEN}Queueing: {full_url}{Style.RESET_ALL}")
                                    download_queue.put(full_url)
                                    downloaded_files.add(full_url)
                                else:
                                    print(f"{Fore.YELLOW}Skipping: {full_url} (already processed){Style.RESET_ALL}")
                            elif full_url not in visited:
                                to_visit.append(full_url)

            except Exception as e:
                print(f"{Fore.RED}Error processing {current_url}: {str(e)}{Style.RESET_ALL}")

            with open(progress_file, 'wb') as f:
                pickle.dump((visited, to_visit, downloaded_files), f)

    except KeyboardInterrupt:
        print(f"{Fore.YELLOW}Crawling interrupted. Finishing remaining downloads...{Style.RESET_ALL}")
    
    # Wait for all downloads to complete
    download_queue.join()
    
    # Stop worker threads
    for _ in range(num_threads):
        download_queue.put(None)
    for t in threads:
        t.join()

    os.remove(progress_file)

if __name__ == "__main__":
    print_banner()
    
    base_url = input(f"{Fore.CYAN}Enter the base URL: {Style.RESET_ALL}")
    extensions_input = input(f"{Fore.CYAN}Enter the file extensions to download (comma-separated, e.g., .pdf,.txt,.docx): {Style.RESET_ALL}")
    extensions = [ext.strip() for ext in extensions_input.split(',')]
    download_folder = input(f"{Fore.CYAN}Enter the download folder path (default is './downloads'): {Style.RESET_ALL}") or "./downloads"
    num_threads = int(input(f"{Fore.CYAN}Enter the number of download threads (default is 5): {Style.RESET_ALL}") or "5")

    if not os.path.exists(download_folder):
        os.makedirs(download_folder)

    crawl_and_download(base_url, extensions, download_folder, num_threads)
    print(f"{Fore.GREEN}Crawling and downloading completed.{Style.RESET_ALL}")

