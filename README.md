# mybabysdays-gallery-downloader

Python image scraper for mybabysdays.com

Super simple script to scrape the website (after logging in with your credentials) and downloading all the galery images it finds. One can use the bulk download option built into the website but this will allow getting just the latest images quickly.

## Usage
To use this, set your credentials in: `config.json`

```
pip install -r requirements.txt

python mybabysdays-gallery-downloader.py
```

To control/limit how far back the script goes, use these variables (whichever is hit first stops the process):
 * `MAX_DAYS_BACK` = how many calendar days back to fetch (0 to just keep going until MIN_DATE is hit)
 * `MIN_DATE` = date of the last date to fetch (`dd/mm/yyyy`)

To choose how files are laid out on disk:
 * `DOWNLOAD_MODE` = `"latest"` (default) puts everything in `<DOWNLOAD_ROOT_FOLDER>/<LATEST_FOLDER_NAME>/` with filenames prefixed `YYYY-MM-DD_`. `"per_day"` keeps the older one-folder-per-date layout (`<DOWNLOAD_ROOT_FOLDER>/YYYY-MM-DD/`).
 * `LATEST_FOLDER_NAME` = name of the flat folder used when `DOWNLOAD_MODE="latest"` (default `"latest"`).
 * `ARCHIVE_OLD` = when `DOWNLOAD_MODE="latest"`, after each run move files older than `MAX_DAYS_BACK` days out of `<LATEST_FOLDER_NAME>/` into `<ARCHIVE_FOLDER_NAME>/` so the latest folder only contains recent items. Default `true`. Skipped when `MAX_DAYS_BACK=0` (unbounded crawl).
 * `ARCHIVE_FOLDER_NAME` = sibling folder used for archived files (default `"archive"`).

To choose what to download (all `true` by default):
 * `DOWNLOAD_IMAGES` = fetch gallery images.
 * `DOWNLOAD_VIDEOS` = fetch videos hosted on `videovm*.mybabysdays.com`.
 * `DOWNLOAD_NOTES` = save each "A 'Daily Note' was added." entry — including the full text behind `Show more...` — into `YYYY-MM-DD_notes.txt` (latest mode) or `<YYYY-MM-DD>/notes.txt` (per-day mode). Multiple notes for the same day are appended; re-runs skip notes already written.

# Tracking Config

Git doesn't allow for files to be frozen globaly (tried using `.gitignore`). The best thing is to prevent local changes being tracked:
```
git update-index --assume-unchanged config.json
```
