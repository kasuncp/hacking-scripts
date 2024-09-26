#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse, unquote
from tqdm import tqdm
import pickle
from colorama import init, Fore, Style
import concurrent.futures
import sys
import json
import shutil
import time
import random
import queue

# Initialize colorama for cross-platform color support
init()

VERSION = "1.2.0"

def print_banner():
    banner = f"""{Fore.CYAN}
███████╗██╗  ██╗██╗  ██╗██████╗  ██████╗ ██╗    ██╗                                   
██╔════╝██║  ██║██║  ██║██╔══██╗██╔═████╗██║    ██║                                   
███████╗███████║███████║██║  ██║██║██╔██║██║ █╗ ██║                                   
╚════██║██╔══██║╚════██║██║  ██║██║  ██║██║███╗██║                                   
███████║██║  ██║     ██║██████╔╝╚██████╔╝╚███╔███╔╝                                   
╚══════╝╚═╝  ╚═╝     ╚═╝╚═════╝  ╚═════╝  ╚══╝╚══╝                                    
                                                                                      
██████╗  ██████╗ ██╗    ██╗███╗   ██╗██╗      ██████╗  █████╗ ██████╗ ███████╗██████╗ 
██╔══██╗██╔═══██╗██║    ██║████╗  ██║██║     ██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
██║  ██║██║   ██║██║ █╗ ██║██╔██╗ ██║██║     ██║   ██║███████║██║  ██║█████╗  ██████╔╝
██║  ██║██║   ██║██║███╗██║██║╚██╗██║██║     ██║   ██║██╔══██║██║  ██║██╔══╝  ██╔══██╗
██████╔╝╚██████╔╝╚███╔███╔╝██║ ╚████║███████╗╚██████╔╝██║  ██║██████╔╝███████╗██║  ██║
╚═════╝  ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝
{Fore.GREEN}[ Segmented File Downloader with Detailed Progress Bars ]{Style.RESET_ALL}
{Fore.YELLOW}Version: {VERSION}{Style.RESET_ALL}
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
    max_retries = 5
    base_sleep_time = 1
    
    for attempt in range(max_retries):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=30) as response:
                response.raise_for_status()
                chunk_size = 8192
                with open(output, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            progress_bar.update(len(chunk))
                            overall_progress.update(len(chunk))
            return True
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                sleep_time = base_sleep_time * (2 ** attempt) + random.uniform(0, 1)
                print(f"\nError downloading segment {start}-{end}: {str(e)}")
                print(f"Retrying in {sleep_time:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(sleep_time)
            else:
                print(f"\nError downloading segment {start}-{end}: {str(e)}")
                print(f"Max retries reached. Segment download failed.")
                return False
    return False

def update_status_line(message):
    sys.stdout.write('\r' + ' ' * 100 + '\r')  # Clear the line
    sys.stdout.write(message)
    sys.stdout.flush()

def download_file(url, base_url, download_folder, session, executor):
    try:
        dir_path, filename = create_directory_structure(url, base_url, download_folder)
        local_filename = os.path.join(dir_path, filename)
        
        if os.path.exists(local_filename):
            update_status_line(f"{Fore.YELLOW}Skipping: {filename} (already downloaded){Style.RESET_ALL}")
            return local_filename

        response = session.head(url, timeout=30)
        file_size = int(response.headers.get('content-length', 0))

        if file_size == 0:
            update_status_line(f"{Fore.RED}Unable to determine file size for {filename}{Style.RESET_ALL}")
            return None

        num_threads = min(executor._max_workers, max(1, file_size // (1024 * 1024)))  # 1 thread per MB, max of available workers
        segment_size = file_size // num_threads
        segments = [(i * segment_size, (i + 1) * segment_size - 1) for i in range(num_threads)]
        segments[-1] = (segments[-1][0], file_size - 1)  # Adjust last segment

        segment_files = [f"{local_filename}.part{i}" for i in range(num_threads)]
        
        print(f"\n{Fore.CYAN}Downloading: {filename}{Style.RESET_ALL}")
        
        terminal_width = shutil.get_terminal_size().columns
        overall_bar_width = terminal_width - 1  # Full width of the console
        thread_bar_width = min(terminal_width - 30, 100)  # Keep thread bar width as before
        
        overall_progress = tqdm(total=file_size, unit='iB', unit_scale=True, desc=f"Overall - {filename}", 
                                position=0, bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.GREEN, Style.RESET_ALL),
                                ncols=overall_bar_width)
        
        thread_progress_bars = [
            tqdm(total=end-start+1, unit='iB', unit_scale=True, desc=f"Thread {i+1}", 
                 position=i+1, bar_format="{l_bar}%s{bar}%s{r_bar}" % (Fore.BLUE, Style.RESET_ALL),
                 miniters=1, mininterval=0.1, ncols=thread_bar_width)
            for i, (start, end) in enumerate(segments)
        ]

        futures = [
            executor.submit(download_segment, url, start, end, output, progress_bar, overall_progress)
            for (start, end), output, progress_bar in zip(segments, segment_files, thread_progress_bars)
        ]
        
        # Wait for all futures to complete
        failed_segments = []
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if not future.result():
                failed_segments.append((segments[i], segment_files[i]))

        for bar in thread_progress_bars:
            bar.close()

        # Clear the thread progress bars
        for _ in range(num_threads):
            sys.stdout.write("\033[F")  # Move cursor up one line
            sys.stdout.write("\033[K")  # Clear the line

        if failed_segments:
            print(f"{Fore.YELLOW}Some segments failed to download for {filename}. Adding to retry queue.{Style.RESET_ALL}")
            return (url, local_filename, failed_segments)

        print(f"{Fore.CYAN}Combining segments for {filename}{Style.RESET_ALL}")
        with open(local_filename, 'wb') as outfile:
            for segment_file in segment_files:
                if os.path.exists(segment_file):
                    with open(segment_file, 'rb') as infile:
                        outfile.write(infile.read())
                    os.remove(segment_file)

        overall_progress.set_description(f"Completed - {filename}")
        overall_progress.refresh()

        return local_filename
    except Exception as e:
        print(f"{Fore.RED}Error downloading {filename}: {str(e)}{Style.RESET_ALL}")
        return None

def retry_failed_downloads(failed_queue, session, executor):
    print(f"\n{Fore.CYAN}Retrying failed downloads...{Style.RESET_ALL}")
    while not failed_queue.empty():
        url, local_filename, failed_segments = failed_queue.get()
        print(f"\n{Fore.CYAN}Retrying: {os.path.basename(local_filename)}{Style.RESET_ALL}")
        
        futures = [
            executor.submit(download_segment, url, start, end, output, tqdm(total=end-start+1, unit='iB', unit_scale=True, desc=f"Retry Segment {i+1}"), tqdm(total=end-start+1, unit='iB', unit_scale=True, desc="Overall Retry"))
            for i, ((start, end), output) in enumerate(failed_segments)
        ]
        
        all_succeeded = True
        for future in concurrent.futures.as_completed(futures):
            if not future.result():
                all_succeeded = False
                break
        
        if all_succeeded:
            print(f"{Fore.CYAN}Combining segments for {os.path.basename(local_filename)}{Style.RESET_ALL}")
            with open(local_filename, 'wb') as outfile:
                for _, segment_file in failed_segments:
                    if os.path.exists(segment_file):
                        with open(segment_file, 'rb') as infile:
                            outfile.write(infile.read())
                        os.remove(segment_file)
            print(f"{Fore.GREEN}Successfully retried and completed: {os.path.basename(local_filename)}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}Failed to download {os.path.basename(local_filename)} even after retry.{Style.RESET_ALL}")

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
    failed_queue = queue.Queue()
    
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
                update_status_line(f"{Fore.CYAN}Visiting: {current_url}{Style.RESET_ALL}")

                try:
                    response = session.get(current_url, timeout=30)
                    soup = BeautifulSoup(response.text, 'html.parser')

                    for link in soup.find_all('a'):
                        href = link.get('href')
                        if href:
                            full_url = urljoin(current_url, href)
                            if is_valid_url(full_url, base_url):
                                if any(full_url.endswith(ext) for ext in extensions):
                                    if full_url not in downloaded_files:
                                        result = download_file(full_url, base_url, download_folder, session, executor)
                                        if isinstance(result, tuple):
                                            failed_queue.put(result)
                                        elif result:
                                            downloaded_files.add(full_url)
                                    else:
                                        update_status_line(f"{Fore.YELLOW}Skipping: {full_url} (already processed){Style.RESET_ALL}")
                                elif full_url not in visited:
                                    to_visit.append(full_url)

                except Exception as e:
                    print(f"{Fore.RED}Error processing {current_url}: {str(e)}{Style.RESET_ALL}")

                with open(progress_file, 'wb') as f:
                    pickle.dump((visited, to_visit, downloaded_files), f)

            # Retry failed downloads
            if not failed_queue.empty():
                retry_failed_downloads(failed_queue, session, executor)

        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Crawling interrupted. Progress saved.{Style.RESET_ALL}")
    
    os.remove(progress_file)

def load_or_get_parameters():
    param_file = 'downloader_params.json'
    if os.path.exists(param_file):
        with open(param_file, 'r') as f:
            params = json.load(f)
        print(f"{Fore.MAGENTA}Previous parameters found:{Style.RESET_ALL}")
        print(f"Base URL: {params['base_url']}")
        print(f"Extensions: {', '.join(params['extensions'])}")
        print(f"Download folder: {params['download_folder']}")
        print(f"Number of threads: {params['num_threads']}")
        
        use_previous = input(f"{Fore.CYAN}Do you want to use these parameters? (Y/n): {Style.RESET_ALL}").lower()
        
        if use_previous != 'n':
            return params
    
    # If no previous parameters or user wants new ones, ask for input
    base_url = input(f"{Fore.CYAN}Enter the base URL: {Style.RESET_ALL}")
    extensions_input = input(f"{Fore.CYAN}Enter the file extensions to download (comma-separated, e.g., .pdf,.txt,.docx): {Style.RESET_ALL}")
    extensions = [ext.strip() for ext in extensions_input.split(',')]
    download_folder = input(f"{Fore.CYAN}Enter the download folder path (default is './downloads'): {Style.RESET_ALL}") or "./downloads"
    num_threads = int(input(f"{Fore.CYAN}Enter the number of download threads per file (default is 5): {Style.RESET_ALL}") or "5")
    
    params = {
        'base_url': base_url,
        'extensions': extensions,
        'download_folder': download_folder,
        'num_threads': num_threads
    }
    
    with open(param_file, 'w') as f:
        json.dump(params, f)
    
    return params

if __name__ == "__main__":
    print_banner()
    
    params = load_or_get_parameters()
    
    if not os.path.exists(params['download_folder']):
        os.makedirs(params['download_folder'])

    crawl_and_download(params['base_url'], params['extensions'], params['download_folder'], params['num_threads'])
    print(f"\n{Fore.GREEN}Crawling and downloading completed.{Style.RESET_ALL}")