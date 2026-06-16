import tempfile
import json
from collections.abc import Iterator
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import configparser

from github import Auth, Github
from github.Repository import Repository
from loguru import logger

ROOT = Path(__file__).resolve().parent
GITMODULES = ROOT / ".gitmodules"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


@dataclass
class Submodule:
    name: str
    path: str
    url: str
    hash: str
    tag_name: str


@dataclass
class Release:
    tag_name: str
    version: str
    commit_hash: str
    published_at: datetime


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
    parser = configparser.ConfigParser()
    parser.read(GITMODULES)
    for section in parser.sections():
        name = section.split('"')[1]
        path = parser.get(section, "path")
        submodule_path = ROOT / path
        url = parser.get(section, "url")
        hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=submodule_path, text=True
        ).strip()
        tag_name = subprocess.check_output(
            ["git", "describe", "--tags"], cwd=submodule_path, text=True
        ).strip()
        yield Submodule(name=name, path=path, url=url, hash=hash, tag_name=tag_name)


def get_version(repo: Repository, tag_hash: str):
    # shallow clone the repo to a temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        logger.info(f"cloning {repo.full_name} at {tag_hash}...")
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                tag_hash,
                repo.clone_url,
                tmpdir,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # read version in package.json
        with open(Path(tmpdir) / "package.json") as f:
            package_json = json.load(f)
            version = package_json["version"]
            logger.debug(f"version in package.json: {version}")
            return version


def get_newer_releases(sm: Submodule, g: Github) -> Iterator[Release]:
    owner, repo_name = github_repo(sm.url)
    repo = g.get_repo(f"{owner}/{repo_name}")
    newer_releases = [
        r
        for r in repo.get_releases()
        if r.published_at > repo.get_release(sm.tag_name).published_at
    ]
    for r in newer_releases:
        logger.debug(f"checking release {r.tag_name} published at {r.published_at}...")
        tag_name = r.tag_name
        hash = repo.get_git_ref(f"tags/{tag_name}").object.sha
        yield Release(
            tag_name=tag_name,
            version=get_version(repo, hash),
            commit_hash=hash,
            published_at=r.published_at,
        )


def main():
    auth = Auth.Token(GITHUB_TOKEN) if GITHUB_TOKEN else None
    if auth is None:
        logger.warning("GITHUB_TOKEN not set, API rate limit may apply.")
    g = Github(auth=auth)

    ## Check each submodule for newer releases
    for sm in submodules():
        logger.info(f"Checking {sm.path} ({sm.url})...")
        logger.info(f"current: {sm.hash}")

        newer_releases = sorted(get_newer_releases(sm, g), key=lambda r: r.published_at)
        if newer_releases:
            logger.success("newer releases:")
            for r in newer_releases:
                logger.info(
                    f"- {r.version} ({r.tag_name} published at {r.published_at})"
                )
            print(f"next_release={newer_releases[0].version}")
        else:
            logger.success("no newer releases.")


if __name__ == "__main__":
    main()
