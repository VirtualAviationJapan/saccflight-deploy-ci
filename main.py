"""check update of the submodule
if any newer release is found, write the oldest newer release tag to GITHUB_OUTPUT like `next_release=X.Y.Z`
otherwise write `next_release=` to GITHUB_OUTPUT
Errors out if the version in package.json does not match the tag name or if the version is not a valid semantic version.
"""

import configparser
import json
import os
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from github import Auth, Github
from github.Repository import Repository
from loguru import logger
from semver import Version

ROOT = Path(__file__).resolve().parent
GITMODULES = ROOT / ".gitmodules"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OUTPUT = os.getenv("GITHUB_OUTPUT")


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
    m = re.match(r"https://github\.com/([^/]+)/([^/.]+)(?:\.git)?", url)
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"not a GitHub URL: {url}")


def get_submodule(name: str) -> Submodule:
    parser = configparser.ConfigParser()
    parser.read(GITMODULES)
    section = f'submodule "{name}"'
    path = parser.get(section, "path")
    submodule_path = ROOT / path
    url = parser.get(section, "url")
    hash = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=submodule_path, text=True
    ).strip()
    tag_name = subprocess.check_output(
        ["git", "describe", "--tags", "--exact-match"], cwd=submodule_path, text=True
    ).strip()

    logger.info(f"Checking {path} ({url})...")
    logger.info(f"current: {hash} ({tag_name})")

    return Submodule(name=name, path=path, url=url, hash=hash, tag_name=tag_name)


def get_version(repo: Repository, ref: str):
    content = repo.get_contents("package.json", ref=ref)
    if isinstance(content, list):
        raise RuntimeError("package.json resolved to a directory unexpectedly")
    package_json = json.loads(content.decoded_content.decode("utf-8"))
    version = package_json["version"]
    logger.debug(f"version in package.json: {version}")
    return version


def get_newer_releases(sm: Submodule, g: Github) -> Iterator[Release]:
    owner, repo_name = github_repo(sm.url)
    repo = g.get_repo(f"{owner}/{repo_name}")
    current_release = repo.get_release(sm.tag_name)
    current_published_at = current_release.published_at
    newer_releases = [
        release
        for release in repo.get_releases()
        if current_published_at and release.published_at and release.published_at > current_published_at
    ]
    for r in newer_releases:
        logger.debug(f"checking release {r.tag_name} published at {r.published_at}...")
        tag_name = r.tag_name
        hash = repo.get_git_ref(f"tags/{tag_name}").object.sha
        version = get_version(repo, ref=hash)
        if version != tag_name:
            raise ValueError(
                f"version in package.json ({version}) does not match tag name ({tag_name})"
            )
        if not Version.is_valid(version):
            raise ValueError(f"version {version} is not a valid semantic version")
        yield Release(
            tag_name=tag_name,
            version=version,
            commit_hash=hash,
            published_at=r.published_at,
        )


def main():
    auth = Auth.Token(GITHUB_TOKEN) if GITHUB_TOKEN else None
    if auth is None:
        logger.warning("GITHUB_TOKEN not set, API rate limit may apply.")
    g = Github(auth=auth)

    ## Check each submodule for newer releases
    sm = get_submodule("Packages/io.github.sacchan-vrc.sacc-flight-and-vehicles")
    newer_releases = sorted(get_newer_releases(sm, g), key=lambda r: r.published_at)
    gh_output_text = "next_release="
    if len(newer_releases) > 0:
        gh_output_text += f"{newer_releases[0].tag_name}\n"
    else:
        gh_output_text += "\n"
    logger.info(gh_output_text)
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(gh_output_text)


if __name__ == "__main__":
    main()
