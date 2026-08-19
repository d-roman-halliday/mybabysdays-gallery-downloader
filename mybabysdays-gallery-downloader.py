import os
import re
import shutil
import requests
import json
from datetime import datetime, date
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
DOWNLOAD_MODE = config.get('DOWNLOAD_MODE', 'latest')  # 'latest' (single flat folder, YYYY-MM-DD_ prefix) or 'per_day' (one folder per date)
LATEST_FOLDER_NAME = config.get('LATEST_FOLDER_NAME', 'latest')  # Override the 'latest/' folder name when DOWNLOAD_MODE='latest'
ARCHIVE_OLD = config.get('ARCHIVE_OLD', True)  # When DOWNLOAD_MODE='latest', move files older than MAX_DAYS_BACK to ARCHIVE_FOLDER_NAME after crawling
ARCHIVE_FOLDER_NAME = config.get('ARCHIVE_FOLDER_NAME', 'archive')  # Sibling of LATEST_FOLDER_NAME under DOWNLOAD_ROOT_FOLDER
DOWNLOAD_IMAGES = bool(config.get('DOWNLOAD_IMAGES', True))
DOWNLOAD_VIDEOS = bool(config.get('DOWNLOAD_VIDEOS', True))
DOWNLOAD_NOTES = bool(config.get('DOWNLOAD_NOTES', True))

if DOWNLOAD_MODE not in ('per_day', 'latest'):
    raise SystemExit(f"Invalid DOWNLOAD_MODE: {DOWNLOAD_MODE!r}. Must be 'per_day' or 'latest'.")

if DOWNLOAD_MODE == 'latest' and ARCHIVE_OLD and LATEST_FOLDER_NAME == ARCHIVE_FOLDER_NAME:
    raise SystemExit("LATEST_FOLDER_NAME and ARCHIVE_FOLDER_NAME must differ when ARCHIVE_OLD is enabled.")

try:
    MIN_DATE_PARSED = datetime.strptime(MIN_DATE, '%d/%m/%Y').date()
except ValueError as e:
    raise SystemExit(f"Invalid MIN_DATE: {MIN_DATE!r}. Expected format dd/mm/yyyy. Error: {e}")

# Global Configuration (these remain hardcoded as they're not intended for config file)
LOGIN_URL = 'https://' + DOMAIN + '.mybabysdays.com/user/home'
IMAGE_BASE = '/images/sted/gallery_image/'
VIDEO_BASE = f'mybabysdays.com/video_path/'
HOME_PAGE_URL = 'https://' + DOMAIN + '.mybabysdays.com/component/sted_parent/feed/main'
AJAX_ROWS_URL = 'https://' + DOMAIN + '.mybabysdays.com/index.php?components=com_sted&option=com_sted_parent&controller=feed&task=ajax_rows'

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


def media_destination(media_url, date_str):
    """Return (folder, filepath) for a given media URL and ISO date, honouring DOWNLOAD_MODE."""
    filename = os.path.basename(urlparse(media_url).path)
    if DOWNLOAD_MODE == 'latest':
        folder = os.path.join(DOWNLOAD_ROOT_FOLDER, clean_folder_name(LATEST_FOLDER_NAME))
        filepath = os.path.join(folder, f"{date_str}_{filename}")
    else:
        folder = os.path.join(DOWNLOAD_ROOT_FOLDER, clean_folder_name(date_str))
        filepath = os.path.join(folder, filename)
    return folder, filepath


def notes_destination(date_str):
    """Return (folder, filepath) for the daily-notes file for an ISO date, honouring DOWNLOAD_MODE."""
    if DOWNLOAD_MODE == 'latest':
        folder = os.path.join(DOWNLOAD_ROOT_FOLDER, clean_folder_name(LATEST_FOLDER_NAME))
        filepath = os.path.join(folder, f"{date_str}_notes.txt")
    else:
        folder = os.path.join(DOWNLOAD_ROOT_FOLDER, clean_folder_name(date_str))
        filepath = os.path.join(folder, "notes.txt")
    return folder, filepath


_NOTE_ID_MARKER_RE = re.compile(r'^# Daily Note (\d+)\b', re.MULTILINE)


def save_notes_for_date(date_str, notes):
    """Append any not-yet-recorded notes for `date_str` to its notes file.

    Each note is delimited by a `# Daily Note <id>` marker line so subsequent runs can
    skip notes already on disk. Returns the number of notes newly written.
    """
    if not notes:
        return 0
    folder, filepath = notes_destination(date_str)

    existing_ids = set()
    file_exists = os.path.exists(filepath)
    if file_exists:
        with open(filepath, 'r', encoding='utf-8') as f:
            existing_ids = set(_NOTE_ID_MARKER_RE.findall(f.read()))

    new_notes = [n for n in notes if n.get('id') and n['id'] not in existing_ids]
    if not new_notes:
        return 0

    os.makedirs(folder, exist_ok=True)
    with open(filepath, 'a' if file_exists else 'w', encoding='utf-8') as f:
        for i, note in enumerate(new_notes):
            if file_exists or i > 0:
                f.write('\n\n')
            f.write(f"# Daily Note {note['id']}")
            if note.get('posted'):
                f.write(f" — {note['posted']}")
            f.write('\n\n')
            f.write(note['body'])
            f.write('\n')
            file_exists = True
    return len(new_notes)


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
        # The site may interpose a "verify your email" two-factor step after login.
        # It ships a "Skip" link that isn't server-side gated (the countdown/disabled
        # state is JS-only), so following it directly completes the login.
        skip_link = response_soup.find('a', id='skipBtn')
        if skip_link and skip_link.get('href'):
            skip_url = urljoin(response.url, skip_link.get('href'))
            try:
                response = session.get(skip_url, timeout=10)
                response.raise_for_status()
            except requests.exceptions.ConnectionError as e:
                raise ConnectionError(f"Failed to connect to {skip_url} while bypassing two-factor verification. Error: {e}")
            except requests.exceptions.HTTPError as e:
                raise Exception(f"HTTP error while bypassing two-factor verification: {e}")
            except requests.exceptions.Timeout:
                raise ConnectionError(f"Connection to {skip_url} timed out while bypassing two-factor verification.")
            response_soup = BeautifulSoup(response.text, 'html.parser')

    if "logout" not in response.text.lower() and "dashboard" not in response.text.lower():
        # If the login form is still present, it likely means login failed
        if response_soup.find('form') and response_soup.find('form').find('input', {'name': 'username'}):
            raise CredentialError("Login failed. Incorrect username or password, or an issue with the login process.")
        else:
            raise Exception("Login failed. Could not confirm successful login. The website structure might have changed.")

    # Re-scope host-only cookies to root domain for cross-subdomain media hosts.
    ensure_cross_subdomain_cookies()

    print("Login successful.")
    return response


def _extract_note_from_block(block):
    """Return {'id', 'posted', 'body'} for a 'Daily Note was added' block, or None.

    Only matches the "added" event (not edits/comments). The body is taken from the
    hidden .extraBlock div (full text behind 'Show more...'); falls back to the visible
    .extraInfo if extraBlock is missing.
    """
    h2 = block.find('h2')
    if not h2:
        return None
    h2_text = h2.get_text(' ', strip=True)
    if "'Daily Note'" not in h2_text or 'was added' not in h2_text:
        return None

    note_id = block.get('data-id') or ''

    target = block.find('div', class_='extraBlock')
    if target is None:
        target = block.find('div', class_='extraInfo')
        if target is not None:
            for a in target.find_all('a', class_='showMore'):
                a.decompose()
    if target is None:
        body = ''
    else:
        for br in target.find_all('br'):
            br.replace_with('\n')
        body = target.get_text()
    body = re.sub(r'[ \t]+\n', '\n', body)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()

    posted = ''
    vd = block.find('span', class_='vertical-date')
    if vd:
        posted = vd.get_text(' ', strip=True)

    return {'id': note_id, 'posted': posted, 'body': body}


def parse_feed_chunk(html, page_url):
    """
    Parse a feed page or AJAX-rows response.

    Returns (by_date, cursor):
      - by_date: dict {YYYY-MM-DD: {'media': [url, ...], 'notes': [{...}, ...]}}, in document order.
        Media collection respects DOWNLOAD_IMAGES / DOWNLOAD_VIDEOS; notes only present when
        DOWNLOAD_NOTES is enabled.
      - cursor: dict with 'lastDate', 'lastid', 'rowCount', 'itemCount' from the
        last hidden inputs in the chunk (empty if none)
    """
    soup = BeautifulSoup(html, 'html.parser')

    by_date = {}

    def entry_for(date_str):
        return by_date.setdefault(date_str, {'media': [], 'notes': []})

    if DOWNLOAD_IMAGES or DOWNLOAD_VIDEOS:
        def media_match(h):
            if not h:
                return False
            if DOWNLOAD_IMAGES and h.startswith(IMAGE_BASE):
                return True
            if DOWNLOAD_VIDEOS and VIDEO_BASE in h:
                return True
            return False

        for link in soup.find_all('a', href=media_match):
            row = link.find_previous('div', class_='feed-date-row')
            if not row or not row.has_attr('data-date'):
                # AJAX responses may start with timeline blocks belonging to a previous date,
                # but the script always issues the request from a fresh feed page so the
                # initial-page case is what matters here. Skip orphaned blocks.
                continue
            href = link['href']
            media_url = urljoin(page_url, href) if href.startswith(IMAGE_BASE) else href
            entry_for(row['data-date'])['media'].append(media_url)

    if DOWNLOAD_NOTES:
        for block in soup.find_all('div', class_='vertical-timeline-block'):
            note = _extract_note_from_block(block)
            if not note:
                continue
            row = block.find_previous('div', class_='feed-date-row')
            if not row or not row.has_attr('data-date'):
                continue
            entry_for(row['data-date'])['notes'].append(note)

    cursor = {}
    for name in ('lastDate', 'lastid', 'rowCount', 'itemCount'):
        inputs = soup.find_all('input', {'name': name})
        if inputs:
            cursor[name] = inputs[-1].get('value')

    return by_date, cursor


def download_for_date(date_str, entry):
    media_urls = entry.get('media', [])
    notes = entry.get('notes', [])

    count = 0
    skipped = 0
    for media_url in media_urls:
        folder, filepath = media_destination(media_url, date_str)
        if os.path.exists(filepath):
            skipped += 1
            continue
        os.makedirs(folder, exist_ok=True)
        if download_media_file(media_url, filepath, HOME_PAGE_URL):
            count += 1

    notes_written = save_notes_for_date(date_str, notes) if notes else 0

    parts = []
    if media_urls:
        parts.append(f"media: downloaded {count}, already had {skipped}")
    if notes:
        parts.append(f"notes: wrote {notes_written}, already had {len(notes) - notes_written}")
    if parts:
        print(f"{date_str}: " + "; ".join(parts))


def process_chunk(by_date):
    """Download media for each date. Returns True if a stop condition was hit."""
    today = date.today()
    for date_str in sorted(by_date.keys(), reverse=True):
        try:
            row_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            print(f"Info: row date '{row_date}'")
        except ValueError:
            print(f"Warning: unexpected date value '{date_str}', skipping.")
            continue

        if row_date < MIN_DATE_PARSED:
            print(f"Hit MIN_DATE ({MIN_DATE}). Stopping.")
            return True

        days_back = (today - row_date).days
        if MAX_DAYS_BACK and days_back > MAX_DAYS_BACK:
            print(f"Reached MAX_DAYS_BACK ({MAX_DAYS_BACK} days). Stopping. Next day with items is {row_date} ({days_back} days back).")
            return True

        download_for_date(date_str, by_date[date_str])
    return False


def crawl_media():
    print(f"Fetching {HOME_PAGE_URL}")
    try:
        response = session.get(HOME_PAGE_URL, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Fatal: failed to load feed page: {e}")
        return

    by_date, cursor = parse_feed_chunk(response.text, HOME_PAGE_URL)
    if not by_date:
        print("Warning: no items found on the initial feed page.")
        return

    if process_chunk(by_date):
        return

    # Walk back via the same AJAX endpoint the "Load More" button uses.
    while cursor.get('lastDate') and cursor.get('lastid'):
        try:
            row_count = int(cursor.get('rowCount', 0))
            item_count = int(cursor.get('itemCount', 0))
        except (TypeError, ValueError):
            break
        if row_count and item_count and row_count <= item_count:
            print("Reached end of feed.")
            break

        payload = {
            'action': '',
            'lastDate': cursor['lastDate'],
            'lastID': cursor['lastid'],
            'rowCount': cursor.get('rowCount', ''),
        }
        try:
            response = session.post(
                AJAX_ROWS_URL,
                data=payload,
                timeout=15,
                headers={
                    'Referer': HOME_PAGE_URL,
                    'X-Requested-With': 'XMLHttpRequest',
                },
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Warning: failed to load more rows: {e}")
            break

        if not response.text.strip():
            print("Empty AJAX response. Stopping.")
            break

        by_date, cursor = parse_feed_chunk(response.text, HOME_PAGE_URL)
        if not by_date:
            print("No more items in feed. Stopping.")
            break

        if process_chunk(by_date):
            return


_LATEST_PREFIX_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})_')


def archive_old_from_latest():
    """Move files in <root>/<LATEST_FOLDER_NAME>/ whose YYYY-MM-DD_ prefix is older than
    MAX_DAYS_BACK days into <root>/<ARCHIVE_FOLDER_NAME>/. No-op when DOWNLOAD_MODE!='latest',
    when archiving is disabled, or when MAX_DAYS_BACK==0 (unbounded crawl)."""
    if DOWNLOAD_MODE != 'latest' or not ARCHIVE_OLD or not MAX_DAYS_BACK:
        return

    latest_folder = os.path.join(DOWNLOAD_ROOT_FOLDER, clean_folder_name(LATEST_FOLDER_NAME))
    if not os.path.isdir(latest_folder):
        return

    archive_folder = os.path.join(DOWNLOAD_ROOT_FOLDER, clean_folder_name(ARCHIVE_FOLDER_NAME))
    today = date.today()
    moved = 0
    for filename in os.listdir(latest_folder):
        src = os.path.join(latest_folder, filename)
        if not os.path.isfile(src):
            continue
        match = _LATEST_PREFIX_RE.match(filename)
        if not match:
            continue
        try:
            file_date = datetime.strptime(match.group(1), '%Y-%m-%d').date()
        except ValueError:
            continue
        if (today - file_date).days <= MAX_DAYS_BACK:
            continue

        os.makedirs(archive_folder, exist_ok=True)
        dst = os.path.join(archive_folder, filename)
        if os.path.exists(dst):
            # Already in archive (e.g. ran twice) — drop the duplicate from latest.
            os.remove(src)
        else:
            shutil.move(src, dst)
        moved += 1

    if moved:
        print(f"Archived {moved} file(s) older than {MAX_DAYS_BACK} day(s) into {archive_folder}")


if __name__ == '__main__':
    try:
        login()
        crawl_media()
        archive_old_from_latest()
    except ConnectionError as e:
        print(f"Fatal Connection Error: {e}")
    except CredentialError as e:
        print(f"Authentication Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
