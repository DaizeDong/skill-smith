"""Validate an explicit HTTPS GitHub repository URL before selecting a remote target."""
import os
import re
from urllib.parse import urlsplit


def owner_repo_from_homepage(homepage):
    """Accept only an exact GitHub owner/repository path, optionally ending in .git or /."""
    if (not isinstance(homepage, str) or not homepage
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in homepage)):
        return None, None
    try:
        url = urlsplit(homepage)
    except ValueError:
        return None, None
    if (url.scheme != "https" or url.netloc.lower() != "github.com"
            or url.query or url.fragment):
        return None, None
    match = re.fullmatch(r"/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9._-]{1,104})/?",
                         url.path)
    if match is None:
        return None, None
    owner, repo = match.groups()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo or repo in (".", "..") or len(repo) > 100:
        return None, None
    return owner, repo


def github_environment(environ=None):
    """Bind gh to the host accepted by the repository URL validator."""
    source = os.environ if environ is None else environ
    environment = {key: value for key, value in source.items() if key.upper() != "GH_HOST"}
    environment["GH_HOST"] = "github.com"
    return environment
