# mybabysdays-gallery-downloader

Python image scraper for mybabysdays.com

Supersimple script to scrape the website (after logging in with your credentials) and downloading all the galery images it finds.

## Usage
To use this, set your credentials in: `config.json`

```
pip install -r requirements.txt

python mybabysdays-gallery-downloader.py
```

To control/limit how far back the script goes, use these variables (whichever is hit first stops the process):
 * `MAX_DAYS_BACK` = how many days back to fetch (0 to just keep going until MIN_DATE is hit)
 * `MIN_DATE` = date of the last date to fetch
