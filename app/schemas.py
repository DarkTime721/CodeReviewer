from pydantic import BaseModel
from typing import Literal
import requests
import os
from dotenv import load_dotenv
import base64
from urllib.parse import urlparse
import time
import groq
import re

load_dotenv()

github_token = os.getenv("GITHUB_TOKEN", None)

class InvalidRequestError(Exception):
    pass

class ConfigurationError(Exception):
    pass

class GitHubAPIError(Exception):
    def __init__(self, message: str, status_code: int, url: str):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        
class GitHubRateLimitError(GitHubAPIError):
    def __init__(self, message: str, status_code: int, url: str, error_secs: int):
        super().__init__(message, status_code, url)
        self.error_secs = error_secs

class GitHubPermanentError(GitHubAPIError):
    def __init__(self, message, status_code, url):
        super().__init__(message, status_code, url)

# Fetches the Github tree [returns every file path in the repo in a single call]
def fetch_repo_tree(owner: str, repo: str, sha: str) -> set[str]:
    """Fetch the full recursive file tree once per PR. Returns the set of 
    all blob (file) paths in the repo at this ref, repo-root-relative."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}?recursive=1"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json"
        }
    
    data = fetch_with_retry(url, headers)

    return {
        entry['path']
        for entry in data.get('tree', [])
        if entry.get('type') == 'blob'
    }

def check_response(response: requests.Response) -> dict:
    status_code = response.status_code

    if status_code == 200:
        return response.json()
    
    try:
        body = response.json()
    except ValueError:
        body = {}

    message = body.get(
        "message",
        "Unknown GitHub API error"
    )

    url = response.url
    
    if status_code in (401, 404):
        raise GitHubPermanentError(message, status_code, url)
    
    elif status_code in (403, 429):
        if response.headers.get('Retry-After'):
            error_secs = int(response.headers.get('Retry-After'))
            raise GitHubRateLimitError(message, status_code, url, error_secs)
        
        elif response.headers.get('x-ratelimit-remaining') == '0':
            error_secs = int(response.headers.get('x-ratelimit-reset')) - time.time()
            raise GitHubRateLimitError(message, status_code, url, error_secs)
        else:
            raise GitHubRateLimitError(message, status_code, url, 60)
        
    elif status_code in (500, 502, 503):
        raise GitHubRateLimitError(message, status_code, url, 120)
    
    else:
        raise GitHubPermanentError(message, status_code, url)
    

def fetch_with_retry(url: str, headers: dict):
    MAX_RETRIES = 4
    last_error = None
    for _ in range(MAX_RETRIES):
        response = requests.get(url=url, headers=headers)
        try:
            return check_response(response)
        except GitHubRateLimitError as e:
            last_error = e
            time.sleep(e.error_secs)
            continue
        except GitHubPermanentError as e:
            raise 
    
    raise last_error

# Added for Groq API cooldown errors so that the findings don't return empty
def invoke_with_retry_llm(llm, messages, max_attempts=4):
    for attempt in range(max_attempts):
        try:
            result = llm.invoke(messages)
            return result
        except groq.RateLimitError as e:
            last_error = e

            # As sleeping on the final attempt will achieve nothing, the loop is exited and error is raised immediately
            if attempt == max_attempts - 1:
                break

            error_time = e.response.headers.get('retry-after', None)

            if error_time:
                error_time = float(error_time)
            else:
                # No header, parsing the raw error message for wait time
                message = e.body['error']['message']
                match = re.search(r"try again in ([\d.]+)(ms|s|m|h)", message)
                if match:
                    value = float(match.group(1))
                    unit = match.group(2)
                    multiplier = {"ms": 1/1000, "s": 1, "m": 60, "h": 3600}
                    error_time = value * multiplier.get(unit, 1)

                # Failed regex match, waits for a default time of 5s
                else:
                    error_time = 5
                    print("Error time failed to extract")
                

            time.sleep(error_time)
    
    # All attempts exhausted thus raise the last real RateLimitError so the
    # caller's own except Exception block handles the node-specific fallback
    raise last_error


class GitReviewInfo(BaseModel):
    github_url: str
    pull_number: str

class FileEntry(BaseModel):
    version: Literal['new', 'old']
    content: str
    file: str

class ReviewRequest(BaseModel):
    repo_id: str
    input: list[FileEntry]
    failed_files: dict
    repo_url_fetch: str
    repo_tree: set[str]
    head_sha: str

def fetch_pr_files(owner: str, repo: str, pull_number: str) -> tuple[list[FileEntry], dict[str, GitHubAPIError]]:

    skeleton_url = "https://api.github.com/repos"

    files: list[FileEntry] = []
    failed_files = {}

    if github_token:
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json"
        }

        # Gives a json consisting of file changes which happened during a particular pull request with their names
        data = fetch_with_retry(
            url=f"{skeleton_url}/{owner}/{repo}/pulls/{pull_number}/files",
            headers=headers
        )

        if data:
            # Gives a json consisting of metadata about the Pull request itself
            commits = fetch_with_retry(
                url=f"{skeleton_url}/{owner}/{repo}/pulls/{pull_number}",
                headers=headers
            )

            # SHAs are used to refer to retrieve old and new files which were changed
            head_sha = commits['head']['sha']
            base_sha = commits['base']['sha']

            for d in data:

                try:

                    if d['status'] == "added":
                        # Gives the json consisting of metadata of changed files with it's content encoded in base64
                        new = fetch_with_retry(
                            url=f"{skeleton_url}/{owner}/{repo}/contents/{d['filename']}?ref={head_sha}",
                            headers=headers
                        )

                        # Decode required as the content is base64 encoded
                        new_decoded = base64.b64decode(
                            new['content']
                        ).decode("utf-8")

                        files.append(
                            FileEntry(
                                version="new",
                                content=new_decoded,
                                file=d['filename']
                            )
                        )
                        
                    
                    elif d['status'] == "removed" or d['status'] == "deleted":

                        old = fetch_with_retry(
                            url=f"{skeleton_url}/{owner}/{repo}/contents/{d['filename']}?ref={base_sha}",
                            headers=headers
                        )

                        old_decoded = base64.b64decode(
                            old['content']
                        ).decode("utf-8")

                        new_decoded = ""

                        files.append(
                            FileEntry(
                                version="old",
                                content=old_decoded,
                                file=d['filename']
                            )
                        )

                        files.append(
                            FileEntry(
                                version="new",
                                content=new_decoded,
                                file=d['filename']
                            )
                        )
                    
                    else:

                        new = fetch_with_retry(
                            url=f"{skeleton_url}/{owner}/{repo}/contents/{d['filename']}?ref={head_sha}",
                            headers=headers
                        )

                        if d['status'] == "renamed":

                            old = fetch_with_retry(
                            url=f"{skeleton_url}/{owner}/{repo}/contents/{d['previous_filename']}?ref={base_sha}",
                            headers=headers
                        )

                        else:

                            old = fetch_with_retry(
                            url=f"{skeleton_url}/{owner}/{repo}/contents/{d['filename']}?ref={base_sha}",
                            headers=headers
                        )

                        new_decoded = base64.b64decode(
                            new['content']
                        ).decode("utf-8")

                        old_decoded = base64.b64decode(
                            old['content']
                        ).decode("utf-8")

                        files.append(
                            FileEntry(
                                version="old",
                                content=old_decoded,
                                file=d['filename']
                            )
                        )

                        files.append(
                            FileEntry(
                                version="new",
                                content=new_decoded,
                                file=d['filename']
                            )
                        )
                except GitHubAPIError as e:
                    failed_files[e.url] = e
                    continue
        
        else:
            print("No files changed for this commit")

        # Returning the Head SHA instead of the Base SHA as Head SHA tracks the latest changes 
        # so we can get the present file structure (tree) from GitHub API
        return files, failed_files, head_sha
    
    else:
        raise ConfigurationError("GitHub token is not configured")

def parse_github_url(url: str):

    # SSH format
    if url.startswith("git@github.com:"):
        path = url.split(":")[1]

    else:
        parsed = urlparse(url)
        path = parsed.path.lstrip("/")

    # remove .git
    if path.endswith(".git"):
        path = path[:-4]
    
    parts = path.split("/")

    if len(parts) < 2:
        raise InvalidRequestError("Invalid GitHub pull request URL")
    
    owner = parts[0]
    repo = parts[1]

    return owner, repo

def construct_review_req(url: str, pull_number: str) -> ReviewRequest:

    owner, repo = parse_github_url(url)

    # Using this URL to fetch files from the taint-tracker to check dependency instead of the previous function relying on the location where code is run
    # The main disadvantage of that method that you need the code to be present on the disk (does not work with GitHub URL fetching)
    repo_url_fetch = f"https://api.github.com/repos/{owner}/{repo}/contents"

    input, failed_files, sha = fetch_pr_files(owner=owner, repo=repo, pull_number=pull_number)

    repo_tree = fetch_repo_tree(owner=owner, repo=repo, sha=sha)

    return ReviewRequest(
        repo_id=repo,
        input=input,
        failed_files=failed_files,
        repo_url_fetch=repo_url_fetch,
        repo_tree=repo_tree,
        head_sha = sha
    )
