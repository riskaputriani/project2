from pathlib import Path
path = Path('CloudflareBypassForScraping/cf_bypasser/core/bypasser.py')
text = path.read_text(encoding='utf-8')
lines = text.splitlines()
for i in range(150, 220):
    print(i+1, lines[i].encode('unicode_escape'))
