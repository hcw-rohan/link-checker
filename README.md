# README
Crawls a URL for links and returns a list that have error codes or take longer than 1 second to load. Used for cleaning up bad links on websites.

Built entirely from copilot prompts in about an hour.

## How to run
create virtual environment
```
python3 -m venv link-checker
```

start virtual environment
```
source link-checker/bin/activate
```

install dependencies
```
pip3 install requests beautifulsoup4 lxml
```

check url
```
python3 link-checker.py <url>
```
