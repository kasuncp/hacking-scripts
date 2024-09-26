#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse, unquote
from tqdm import tqdm
import pickle
from colorama import init, Fore, Style
import concurrent.futures

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
{Fore.GREEN}[ Segmented File Downloader with Detailed Progress Bars ]{Style.RESET_ALL}
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

def download_segment(url, start, end, output, progress_bar, overall_progress):
    headers = {'Range': f'bytes={start}-{end}'}
    response = requests.get(url, headers=headers, stream=True)
    chunk_size = 8192
    with open(output, 'wb') as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                progress_bar.update(len(chunk))
                overall_progress.update(len(chunk))

def download_file(url, base_url, download_folder, session, executor):
    try:
        dir_path, filename = create_directory_structure(url, base_url, download_folder)
        local_filename = os.path.join(dir_path, filename)
        
        if os.path.exists(local_filename):
            print(f"{Fore.YELLOW}Skipping {filename} (already downloaded){Style.RESET_ALL}")
            return local_filename

        response = session.head(url)
        file_size = int(response.headers.get('content-length', 0))

        if file_size == 0:
            print(f"{Fore.RED}Unable to determine file size for {url}{Style.RESET_ALL}")
            return None

        num_threads = min(executor._max_workers, max(1, file_size // (1024 * 1024)))  # 1 thread per MB, max of available workers
        segment_size = file_size // num_threads
        segments = [(i * segment_size, (i + 1) * segment_size - 1) for i in range(num_threads)]
        segments[-1] = (segments[-1][0], file_size - 1)  # Adjust last segment

        segment_files = [f"{local_filename}.part{i}" for i in range(num_threads)]
        
        print(f"{Fore.CYAN}Downloading: {filename}{Style.RESET_ALL}")
        
        overall_progress = tqdm(total=file_size, unit='iB', unit_scale=True, desc="Overall", 
                                position=0, bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.GREEN, Style.RESET_ALL))
        
        thread_progress_bars = [
            tqdm(total=end-start+1, unit='iB', unit_scale=True, desc=f"Thread {i+1}", 
                 position=i+1, bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.BLUE, Style.RESET_ALL))
            for i, (start, end) in enumerate(segments)
        ]

        futures = [
            executor.submit(download_segment, url, start, end, output, progress_bar, overall_progress)
            for (start, end), output, progress_bar in zip(segments, segment_files, thread_progress_bars)
        ]
        concurrent.futures.wait(futures)

        overall_progress.close()
        for bar in thread_progress_bars:
            bar.close()

        print(f"{Fore.CYAN}Combining segments for {filename}{Style.RESET_ALL}")
        with open(local_filename, 'wb') as outfile:
            for segment_file in segment_files:
                with open(segment_file, 'rb') as infile:
                    outfile.write(infile.read())
                os.remove(segment_file)

        print(f"{Fore.GREEN}Download completed: {filename}{Style.RESET_ALL}")
        return local_filename
    except Exception as e:
        print(f"{Fore.RED}Error downloading {url}: {str(e)}{Style.RESET_ALL}")
        return None

def is_valid_url(url, base_url):
    parsed_url = urlparse(url)
    parsed_base_url = urlparse(base_url)
    
    if parsed_url.netloc != parsed_base_url.netloc:
        return False
    
    if not parsed_url.path.startswith(parsed_base_url.path):
        return False
    
    return True

def crawl_and_download(base_url, extensions, download_folder, num_threads=5):
    session = requests.Session()
    visited = set()
    to_visit = [base_url]
    downloaded_files = set()
    
    progress_file = os.path.join(download_folder, 'crawl_progress.pkl')
    if os.path.exists(progress_file):
        with open(progress_file, 'rb') as f:
            visited, to_visit, downloaded_files = pickle.load(f)
        print(f"{Fore.MAGENTA}Resuming from previous session{Style.RESET_ALL}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
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
                                        if download_file(full_url, base_url, download_folder, session, executor):
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
            print(f"{Fore.YELLOW}Crawling interrupted. Progress saved.{Style.RESET_ALL}")
    
    os.remove(progress_file)

if __name__ == "__main__":
    print_banner()
    
    base_url = input(f"{Fore.CYAN}Enter the base URL: {Style.RESET_ALL}")
    extensions_input = input(f"{Fore.CYAN}Enter the file extensions to download (comma-separated, e.g., .pdf,.txt,.docx): {Style.RESET_ALL}")
    extensions = [ext.strip() for ext in extensions_input.split(',')]
    download_folder = input(f"{Fore.CYAN}Enter the download folder path (default is './downloads'): {Style.RESET_ALL}") or "./downloads"
    num_threads = int(input(f"{Fore.CYAN}Enter the number of download threads per file (default is 5): {Style.RESET_ALL}") or "5")

    if not os.path.exists(download_folder):
        os.makedirs(download_folder)

    crawl_and_download(base_url, extensions, download_folder, num_threads)
    print(f"{Fore.GREEN}Crawling and downloading completed.{Style.RESET_ALL}")