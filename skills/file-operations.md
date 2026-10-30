# Windows File and Folder Operations

## Scope
Use for opening folders/files, copying, moving, renaming, creating, or deleting local items. Project file tools only access the agent's project directory; system-wide paths require an appropriate Windows tool such as the approval-gated shell.

## Open a known folder or file
- For common shell folders, prefer Windows known-folder namespaces, such as `Start-Process -FilePath 'explorer.exe' -ArgumentList 'shell:Downloads'` for Downloads.
- For a file, resolve the exact full path before opening it with its registered default application.
- Distinguish “the path exists,” “the open request was issued,” and “the app visibly opened the target.” Only claim the strongest state that the tools verify.

## Copy, move, rename
1. Resolve and verify the source path.
2. Resolve the exact destination and check whether it already exists.
3. Avoid wildcard sources/destinations unless the user explicitly requests a batch operation and the match set is shown or clearly bounded.
4. Ask before overwriting, replacing, or moving multiple ambiguous items.
5. Perform one operation, then verify source/destination state independently.
6. Report the full destination path and any items skipped or failed.

## Delete
- Treat deletion as a high-impact operation. Confirm the target and obtain approval required by the host policy.
- Prefer moving to Recycle Bin when supported. Avoid permanent deletion by default.
- Never broaden a single-file delete into a wildcard or parent-directory deletion.
- Do not use `Remove-Item -Recurse`, `rd /s`, or equivalent destructive commands as a fallback to a failed normal delete.

## Downloads and browser downloads
- Do not assume Downloads is `%USERPROFILE%\Downloads`; the folder can be relocated. Use the shell namespace to open it or a known-folder API for the actual path.
- Distinguish downloading a file from opening a file already downloaded.
- Do not open unexpected downloaded executables or scripts automatically. Verify the name, source, and file type; ask before executing them.

## Verification
A successful command exit code alone may not prove the requested file operation completed correctly. Check the expected source/destination state, and state what remains unverified.
