# honest-failure

Use whenever a tool call fails, is blocked, times out, or is denied.

## Rules
1. Quote the tool's exact result text (first line is enough). Never paraphrase it into a cause you did not see.
2. Classify the failure using ONLY what the text says:
   - "Blocked by safety rule ..." -> the agent's own text filter fired. It is not an OS policy and not Windows security. Rephrase the command without that text, or use a typed tool.
   - "took longer than N seconds" -> timeout. Retry once with a lighter command, or say it needs a longer limit.
   - "not found" / "False" -> the path or name is wrong. Search for the real one before concluding it is missing.
   - "Skipped" / "not run" -> the user denied it or STOP was pressed. Do not retry.
3. Allowed words for a cause: only ones that appear in the tool result. Never write "security policy", "restricted", "cannot interact with the GUI", or "system is blocking" unless that text is in the result.
4. Try up to 3 DIFFERENT approaches. A different approach changes the method, not the wording. A more complicated check is not a new approach.
5. A check is not the action. If the user asked to open or run something, do that. Do not replace it with Test-Path or an existence check.

## Final report format (when still failing)
- Tried: 1) <command> -> <exact result>  2) ... 3) ...
- Cause (only if shown by the result): ...
- Needs from user: <one specific thing, or "nothing">
