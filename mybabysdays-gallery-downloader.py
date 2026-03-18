import os
import re
import requests
import json
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from requests.cookies import create_cookie

# Define a custom exception for credential errors
class CredentialError(Exception):
    pass

# Load configuration from config.json
with open('config.json', 'r') as f:
    config = json.load(f)

DOMAIN = config['DOMAIN']
USERNAME = config['USERNAME']
PASSWORD = config['PASSWORD']

# Configuration with defaults from config.json or hardcoded values
MAX_DAYS_BACK = config.get('MAX_DAYS_BACK', 10)  # Default to 10 if not in config
MIN_DATE = config.get('MIN_DATE', '01/01/2025')  # Default to '01/01/2025' if not in config
DOWNLOAD_ROOT_FOLDER = config.get('DOWNLOAD_ROOT_FOLDER', 'downloaded_images') # Default to 'downloaded_images' if not in config

# Global Configuration (these remain hardcoded as they're not intended for config file)
LOGIN_URL = 'https://' + DOMAIN + '.mybabysdays.com/user/home'
IMAGE_BASE = '/images/sted/gallery_image/'
VIDEO_BASE = f'mybabysdays.com/video_path/'
HOME_PAGE_URL = 'https://' + DOMAIN + '.mybabysdays.com/component/sted_parent/diary/main'

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


def ensure_cross_subdomain_cookies():
    """
    Copy host-only cookies to .mybabysdays.com so requests to videovm*.mybabysdays.com
    can reuse the authenticated session.
    """
    cloned = 0
    cookies_snapshot = list(session.cookies)
    for cookie in cookies_snapshot:
        if not cookie.domain:
            continue

        domain = cookie.domain.lstrip(".")
        if not domain.endswith(".mybabysdays.com"):
            continue

        # Cookie is host-only for <tenant>.mybabysdays.com. Clone it for parent domain.
        if cookie.domain == domain and domain.count(".") >= 2:
            parent_cookie = create_cookie(
                name=cookie.name,
                value=cookie.value,
                domain=".mybabysdays.com",
                path=cookie.path or "/",
                secure=cookie.secure,
                expires=cookie.expires,
                rest=getattr(cookie, "_rest", {}),
            )
            session.cookies.set_cookie(parent_cookie)
            cloned += 1

    if cloned:
        print(f"Extended {cloned} auth cookie(s) to .mybabysdays.com")


def download_media_file(media_url, filepath, page_url):
    media_headers = {
        "Accept": "video/webm,video/mp4,application/octet-stream,*/*;q=0.8",
        "Referer": page_url,
        "Origin": f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}",
    }

    try:
        media_request = session.get(media_url, headers=media_headers, timeout=30)
        media_request.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        content_type = (media_request.headers.get("Content-Type") or "").lower()
        body_prefix = media_request.content[:512].decode("utf-8", errors="ignore").lower()
        if "text/html" in content_type or "<h1>403 forbidden</h1>" in body_prefix:
            print(f"Warning: Access denied for media URL: {media_url}")
            return False

        with open(filepath, 'wb') as f:
            f.write(media_request.content)
        return True
    except requests.exceptions.ConnectionError as e:
        print(f"Warning: Failed to download {media_url}. Connection error: {e}")
    except requests.exceptions.HTTPError as e:
        print(f"Warning: HTTP error downloading {media_url}: {e}")
    except requests.exceptions.Timeout:
        print(f"Warning: Download of {media_url} timed out.")
    except Exception as e:
        print(f"Warning: An unexpected error occurred while downloading {media_url}: {e}")

    return False

def clean_folder_name(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def extract_and_reformat_date(text):
    # Match date pattern like '2nd March 2025'
    match = re.search(
        r'(\d{1,2})(st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
        text)

    if not match:
        raise ValueError("No valid date found in input")

    day, _, month, year = match.groups()
    clean_date = f"{day} {month} {year}"

    # Parse and format
    parsed_date = datetime.strptime(clean_date, '%d %B %Y')
    return parsed_date.strftime('%Y-%m-%d')

def login():
    try:
        # Get the login page first to get any hidden form fields
        login_page = session.get(LOGIN_URL, timeout=10)
        login_page.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Failed to connect to {LOGIN_URL}. Please check your internet connection and the domain name. Error: {e}")
    except requests.exceptions.HTTPError as e:
        raise Exception(f"HTTP error during login page retrieval: {e} \nCheck the domain is correct: {DOMAIN}")
    except requests.exceptions.Timeout:
        raise ConnectionError(f"Connection to {LOGIN_URL} timed out.")

    soup = BeautifulSoup(login_page.text, 'html.parser')

    # Find the login form, adapt as needed
    form = soup.find('form')
    if not form:
        raise Exception("Login form not found on the page. The website structure might have changed.")

    action = form.get('action')
    if not action:
        raise Exception("Login form action URL not found.")
    login_action_url = urljoin(LOGIN_URL, action)

    payload = {
        'username': USERNAME,
        'passwd': PASSWORD,
    }

    # Include hidden inputs if present
    for hidden in form.find_all('input', {'type': 'hidden'}):
        payload[hidden.get('name')] = hidden.get('value')

    try:
        response = session.post(login_action_url, data=payload, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Failed to connect to {login_action_url} during login attempt. Error: {e}")
    except requests.exceptions.HTTPError as e:
        # If login fails due to incorrect credentials, it often results in a redirect back to login
        # or a 200 OK with an error message on the page. We need to check the content.
        if "Incorrect username or password" in response.text or "login failed" in response.text.lower():
            raise CredentialError("Login failed. Incorrect username or password.")
        else:
            raise Exception(f"HTTP error during login submission: {e}")
    except requests.exceptions.Timeout:
        raise ConnectionError(f"Login attempt to {login_action_url} timed out.")


    # Basic login success check
    # Check for elements present on the post-login page, and absence of login form
    response_soup = BeautifulSoup(response.text, 'html.parser')
    if "logout" not in response.text.lower() and "dashboard" not in response.text.lower(): # Assuming "dashboard" appears on successful login
        # If the login form is still present, it likely means login failed
        if response_soup.find('form') and response_soup.find('form').find('input', {'name': 'username'}):
            raise CredentialError("Login failed. Incorrect username or password, or an issue with the login process.")
        else:
            raise Exception("Login failed. Could not confirm successful login. The website structure might have changed.")

    # Re-scope host-only cookies to root domain for cross-subdomain media hosts.
    ensure_cross_subdomain_cookies()

    print("Login successful.")
    return response


def download_media_from_page(url):
    print(f"Processing: {url}")
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        print(f"Warning: Failed to connect to {url}. Skipping this page. Error: {e}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"Warning: HTTP error accessing {url}. Skipping this page. Error: {e}")
        return None
    except requests.exceptions.Timeout:
        print(f"Warning: Connection to {url} timed out. Skipping this page.")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    title = soup.title.string if soup.title else "Untitled"
    try:
        formatted_date = extract_and_reformat_date(title.strip())
    except ValueError as e:
        print(f"Warning: Could not extract date from page title '{title}'. Skipping this page. Error: {e}")
        return None

    folder_name = clean_folder_name(formatted_date)
    download_location = os.path.join(DOWNLOAD_ROOT_FOLDER, folder_name)

    os.makedirs(DOWNLOAD_ROOT_FOLDER, exist_ok=True)

    # Use links as the larger sized image is linked
    all_links = soup.find_all('a')

    count = 0
    for link in all_links:
        #handle a missing href
        if not link.has_attr('href'):
            continue

        # Parse links, and download if it's a gallery image
        href = link['href']
        if (href.startswith(IMAGE_BASE) or VIDEO_BASE in href):
            if href.startswith(IMAGE_BASE):
                media_url = urljoin(url, href) # Link for images doesn't include base
            else:
                media_url = href # Link for videos has whole other subdomain

            filename = os.path.basename(urlparse(media_url).path)
            filepath = os.path.join(download_location, filename)

            #Create dir if not exists
            os.makedirs(download_location, exist_ok=True)

            if not os.path.exists(filepath):
                if download_media_file(media_url, filepath, url):
                    count += 1

    print(f"Downloaded {count} media file(s) to {folder_name}")

    # Find "Prev" button, get URL
    prev_link = soup.find('a', title="View the Previous Month.")
    if prev_link and 'href' in prev_link.attrs:
        next_page_url = urljoin(url, prev_link['href'])
        return next_page_url

    return None

def crawl_media(start_url):
    next_url = start_url
    hit_min_date = False
    days_back = 0
    while (next_url
           and (days_back <= MAX_DAYS_BACK
                or MAX_DAYS_BACK == 0
           )
    ):
        if MIN_DATE in next_url: hit_min_date = True

        next_url = download_media_from_page(next_url)
        days_back += 1

        if hit_min_date:
            print(f"Hit MIN_DATE: {MIN_DATE}")
            break

if __name__ == '__main__':
    try:
        login()
        crawl_media(HOME_PAGE_URL)
    except ConnectionError as e:
        print(f"Fatal Connection Error: {e}")
    except CredentialError as e:
        print(f"Authentication Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
