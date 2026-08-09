import shlex

from app.services.postman_parse import path_from_raw_url, path_to_template

# Flags that consume the following token as a value (so it isn't
# mis-detected as the URL) but don't otherwise affect method/URL detection.
_VALUE_FLAGS = {
    "-H", "--header", "-b", "--cookie", "-u", "--user", "-A", "--user-agent",
    "-e", "--referer", "-o", "--output", "-x", "--proxy", "-T", "--upload-file",
    "--connect-timeout", "--max-time", "-w", "--write-out", "--cacert", "--cert",
}
# Flags that both consume a value AND imply curl will send the request as
# POST if -X/--request wasn't given (matches curl's real default behavior).
_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form"}


def parse_curl_command(command: str) -> tuple[str, str] | None:
    """Parse one `curl ...` command line into (METHOD, path template).

    Best-effort: handles -X/--request, --url, quoted/unquoted bare URLs,
    and the common data/header flags (skipping their values so they're
    never mistaken for the URL). Returns None if no URL could be found.
    """
    command = command.strip()
    if command.startswith("curl"):
        command = command[len("curl") :].strip()
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None

    method: str | None = None
    url: str | None = None
    has_data = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 2
            continue
        if tok == "--url" and i + 1 < len(tokens):
            url = tokens[i + 1]
            i += 2
            continue
        if tok in _DATA_FLAGS:
            has_data = True
            i += 2 if i + 1 < len(tokens) else 1
            continue
        if tok in _VALUE_FLAGS:
            i += 2 if i + 1 < len(tokens) else 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if url is None and "://" in tok:
            url = tok
        i += 1

    if url is None:
        return None
    if method is None:
        method = "POST" if has_data else "GET"
    return method.upper(), path_to_template(path_from_raw_url(url))


def extract_paths_from_curl_text(text: str) -> list[tuple[str, str]]:
    """One or more `curl ...` commands, one per (possibly backslash-continued)
    line. Non-curl lines (blank lines, comments, shell prompts pasted in by
    accident) are skipped rather than rejected outright."""
    joined = text.replace("\\\r\n", " ").replace("\\\n", " ")
    seen: set[tuple[str, str]] = set()
    results: list[tuple[str, str]] = []
    for line in joined.splitlines():
        line = line.strip()
        if not line.startswith("curl"):
            continue
        parsed = parse_curl_command(line)
        if parsed and parsed not in seen:
            seen.add(parsed)
            results.append(parsed)
    return results
