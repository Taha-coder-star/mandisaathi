#!/bin/sh
# Render plan3/src/<name>.html to plan3/pdf/<name>.pdf with headless Chrome. Usage: sh render.sh 01_Name [02_Name ...]
CH="/c/Program Files/Google/Chrome/Application/chrome.exe"
for f in "$@"; do
  "$CH" --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf="D:/fyp/plan3/pdf/$f.pdf" "file:///D:/fyp/plan3/src/$f.html" >/dev/null 2>&1
  python -c "import pypdf,sys;print(sys.argv[1], len(pypdf.PdfReader('D:/fyp/plan3/pdf/'+sys.argv[1]+'.pdf').pages),'pages')" "$f"
done
