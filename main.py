from dataclasses import dataclass
import datetime
import os
import re
import subprocess
from pathlib import Path
from github import Github
from github import Auth, Repository
from loguru import logger

ROOT = Path(__file__).resolve().parent
GITMODULES = ROOT / ".gitmodules"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
THIS_REPO = os.getenv("THIS_REPO")  # e.g. "owner/repo"


@dataclass
class Submodule:
    name: str
    path: str
    url: str
    hash: str


@dataclass
class Release:
    tag_name: str
    commit_hash: str
    published_at: datetime


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def github_repo(url):
    patterns = [
        r"https://github\.com/([^/]+)/([^/.]+)(?:\.git)?",
        r"git@github\.com:([^/]+)/([^/.]+)(?:\.git)?",
        r"ssh://git@github\.com/([^/]+)/([^/.]+)(?:\.git)?",
    ]
    for pattern in patterns:
        m = re.match(pattern, url)
        if m:
            return m.group(1), m.group(2)
    raise RuntimeError(f"not a GitHub URL: {url}")


def submodules():
    out = git(
        "config",
        "--file",
        str(GITMODULES),
        "--get-regexp",
        r"^submodule\..*\.path$",
    )

    for line in out.splitlines():
        key, path = line.split(maxsplit=1)
        name = key[len("submodule.") : -len(".path")]
        url = git(
            "config",
            "--file",
            str(GITMODULES),
            "--get",
            f"submodule.{name}.url",
        )
        yield Submodule(
            name=name,
            path=path,
            url=url,
            hash=git("ls-tree", "HEAD", path).split()[2],
        )


def get_newer_releases(sm: Submodule, g: Github) -> list[Release]:
    owner, repo_name = github_repo(sm.url)
    origin_releases = [
        Release(
            tag_name=release.tag_name,
            commit_hash=g.get_repo(f"{owner}/{repo_name}")
            .get_git_ref(f"tags/{release.tag_name}")
            .object.sha,
            published_at=release.published_at,
        )
        for release in g.get_repo(f"{owner}/{repo_name}").get_releases()
    ]
    current_release_published_at = next(
        (r.published_at for r in origin_releases if r.commit_hash == sm.hash),
        None,
    )
    if current_release_published_at is None:
        logger.error("current commit hash not found in releases.")
        return []
    return [r for r in origin_releases if r.published_at > current_release_published_at]

def main():
    auth = Auth.Token(GITHUB_TOKEN) if GITHUB_TOKEN else None
    if auth is None:
        logger.warning("GITHUB_TOKEN not set, API rate limit may apply.")
    g = Github(auth=auth)

    ## Check each submodule for newer releases
    for sm in submodules():
        logger.info(f"Checking {sm.path} ({sm.url})...")
        logger.info(f"current: {sm.hash}")

        newer_releases = get_newer_releases(sm, g)
        if newer_releases:
            logger.success("newer releases:")
            for r in newer_releases:
                logger.info(f"- {r.tag_name} (published at {r.published_at})")
        else:
            logger.success("no newer releases.")

    issue_body = "## Submodule Update List\n\n" + "\n".join(
        f"- **{sm.path}**: {sm.url}\n  - current: {sm.hash}\n  - newer releases:\n    " + "\n    ".join(
            f"- {r.tag_name} ({r.commit_hash}) (published at {r.published_at})" for r in get_newer_releases(sm, g)
        ) if get_newer_releases(sm, g) else "- no newer releases."
        for sm in submodules()
    )
    logger.info(issue_body)


if __name__ == "__main__":
    main()
