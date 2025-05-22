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
 * `MAX_DAYS_BACK` = how many days back to fetch (0 to just keep going until MIN_DATE is hit)
 * `MIN_DATE` = date of the last date to fetch

# Tracking Config

Git doesn't allow for files to be frozen globaly (tried using `.gitignore`). The best thing is to prevent local changes being tracked:
```
git update-index --assume-unchanged config.json
```
