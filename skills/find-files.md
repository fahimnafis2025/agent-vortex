# find-files

Use for "where is my <file>", "find the PDF I downloaded", "what did I change today".

## Method
1. Scope first. Start with Desktop, Documents, Downloads, then the project folder. Ask before scanning whole drives.
2. By name (use -Filter, it is much faster than -Include):
   `Get-ChildItem -Path "$HOME\Documents","$HOME\Downloads","$HOME\Desktop" -Recurse -File -Filter "*KEYWORD*" -ErrorAction SilentlyContinue | Select-Object -First 20 FullName, Length, LastWriteTime`
3. By type: add -Filter "*.pdf" (one extension per call).
4. Recent files:
   `... | Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName, LastWriteTime`
5. By content (text files only, small scope):
   `Select-String -Path "<folder>\*.txt","<folder>\*.md" -Pattern "TEXT" -List | Select-Object -First 10 Path`
6. Drive-wide search only on request, on one drive at a time, and tell the user it may be slow.

## Rules
- Always cap output (Select-Object -First N).
- 0 results: widen the scope or loosen the keyword before saying "not found". State what you searched.
- Return full paths. Offer to open the folder with `Start-Process explorer.exe "/select,<full path>"`.
- Deleting or moving found files needs approval, per desktop-tasks-router.
