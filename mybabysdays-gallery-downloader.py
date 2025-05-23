import os
import re
import requests
import json
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# Load configuration from config.json
with open('config.json', 'r') as f:
    config = json.load(f)

DOMAIN = config['DOMAIN']
USERNAME = config['USERNAME']
PASSWORD = config['PASSWORD']

# set to 0 for all
MAX_DAYS_BACK = 10
MIN_DATE = '01/01/2025'

DOWNLOAD_ROOT_FOLDER = 'downloaded_images'

# Global Configuration
LOGIN_URL = 'https://' + DOMAIN + '.mybabysdays.com/user/home'
IMAGE_BASE = '/images/sted/gallery_image/'
HOME_PAGE_URL = 'https://' + DOMAIN + '.mybabysdays.com/component/sted_parent/diary/main'

session = requests.Session()

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
    # Get the login page first to get any hidden form fields
    login_page = session.get(LOGIN_URL)
    soup = BeautifulSoup(login_page.text, 'html.parser')

    # Find the login form, adapt as needed
    form = soup.find('form')
    action = form.get('action')
    login_action_url = urljoin(LOGIN_URL, action)

    payload = {
        'username': USERNAME,
        'passwd': PASSWORD,
    }

    # Include hidden inputs if present
    for hidden in form.find_all('input', {'type': 'hidden'}):
        payload[hidden.get('name')] = hidden.get('value')

    response = session.post(login_action_url, data=payload)

    # Basic login success check
    if "logout" not in response.text.lower():
        raise Exception("Login failed. Check credentials or login mechanism.")

    return response


def download_images_from_page(url):
    print(f"Processing: {url}")
    response = session.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    title = soup.title.string if soup.title else "Untitled"
    formatted_date = extract_and_reformat_date(title.strip())
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
        if href.startswith(IMAGE_BASE):
            img_url = urljoin(url, href)
            filename = os.path.basename(urlparse(img_url).path)
            filepath = os.path.join(download_location, filename)

            #Create dir if not exists
            os.makedirs(download_location, exist_ok=True)

            if not os.path.exists(filepath):
                img_data = session.get(img_url).content
                with open(filepath, 'wb') as f:
                    f.write(img_data)
                count += 1
    print(f"Downloaded {count} images to {folder_name}")

    # Find "Prev" button, get URL
    prev_link = soup.find('a', title="View the Previous Month.")
    if prev_link and 'href' in prev_link.attrs:
        next_page_url = urljoin(url, prev_link['href'])
        return next_page_url

    return None

def crawl_images(start_url):
    next_url = start_url
    hit_min_date = False
    days_back = 0
    while (next_url
           and (days_back <= MAX_DAYS_BACK
                or MAX_DAYS_BACK == 0
           )
    ):
        if MIN_DATE in next_url: hit_min_date = True

        next_url = download_images_from_page(next_url)
        days_back += 1

        if hit_min_date:
            print(f"Hit MIN_DATE: {MIN_DATE}")
            break

if __name__ == '__main__':
    login()
    crawl_images(HOME_PAGE_URL)
