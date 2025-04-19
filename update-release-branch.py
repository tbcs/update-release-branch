#!/usr/bin/env python3

import contextlib
import logging
import logging as log
import os
import sys
from collections.abc import Callable
from typing import ParamSpec, TypeVar
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import click
import git
from git import GitCommandError, RemoteReference, Repo

P = ParamSpec("P")
R = TypeVar("R")


class Error(RuntimeError):
    pass


@click.group(
    context_settings={
        "max_content_width": 120,
        "help_option_names": ["-h", "--help"],
    }
)
@click.option(
    "--debug",
    help="Run in debug mode (verbose logging).",
    type=bool,
    is_flag=True,
    default=False,
    required=False,
)
def main(debug: bool) -> None:
    """A tool for maintaining a release branch in git repositories."""
    init(debug)


def _repository_path_option() -> Callable[[Callable[P, R]], Callable[P, R]]:
    return click.option(
        "--repository-path",
        help="""
        The path of the git repository.

        In GitLab CI jobs the CI_PROJECT_DIR variable can be used.

        In GitHub Actions the GITHUB_WORKSPACE variable can be used.

        Defaults to the current working directory.
        """,
        required=False,
        type=click.Path(
            exists=True, file_okay=False, dir_okay=True, resolve_path=True
        ),
        default=os.getcwd,
    )


@click.command()
@click.option(
    "--version",
    help="""
    The release version.

    The merge commit on the release branch is tagged with this value.
    """,
    required=True,
)
@click.option(
    "--release-branch",
    help="The name of the release branch to be updated.",
    required=True,
)
@click.option(
    "--commit-msg",
    help="""
    The commit message to use for the merge commit on the release branch.

    Defaults to "release <version>".
    """,
    required=False,
)
@click.option(
    "--update-to",
    help="""
    The commit up to which changes are to be merged into the release branch.

    In GitLab CI jobs the CI_COMMIT_SHA variable can be used.

    In GitHub Actions the GITHUB_SHA variable can be used.

    Defaults to the latest commit.
    """,
    required=False,
    metavar="COMMIT-HASH",
)
@_repository_path_option()
@click.option(
    "--git-remote-name",
    help="The name of the git remote to use for accessing the release branch.",
    required=False,
    default="origin",
    show_default=True,
)
@click.option(
    "--git-user-name",
    help="""
    The author/committer name to use for the merge commit on the release branch.
    """,
    required=False,
)
@click.option(
    "--git-user-email",
    help="""
    The author/committer email address to use for the merge commit on the
    release branch.
    """,
    required=False,
)
@click.option(
    "--dry-run",
    help="Update the release branch locally without pushing it to the remote.",
    required=False,
    type=bool,
    is_flag=True,
    default=False,
)
@click.option(
    "--prompt",
    help="Prompt for confirmation before pushing to the release branch.",
    required=False,
    type=bool,
    is_flag=True,
    default=False,
)
def update_release_branch(  # noqa: C901, PLR0912, PLR0913, PLR0915
    version: str,
    release_branch: str,
    commit_msg: str | None,
    update_to: str | None,
    repository_path: str,
    git_remote_name: str,
    git_user_name: str | None,
    git_user_email: str | None,
    dry_run: bool,
    prompt: bool,
) -> None:
    """Update the release branch."""  # noqa: DOC501
    repo = get_repo(repository_path)

    remote = repo.remote(git_remote_name)

    remote_branches = {
        f.ref.remote_head
        for f in remote.fetch()
        if isinstance(f.ref, RemoteReference)
    }

    if release_branch not in remote_branches:
        log.warning(
            "Release branch '%s' is absent on the git remote "
            "(this is normal when performing the first release)",
            release_branch,
        )

    commit_hash = update_to or repo.head.commit
    commit = repo.commit(commit_hash)

    # ensure that the specified version wasn't used previously to tag a release
    if version in repo.tags:
        tag = repo.tags[version]
        msg = (
            f"Invalid version '{version}': "
            f"this tag is already present on commit {tag.commit.hexsha}"
        )
        raise Error(msg)

    git_version_branch = str(uuid4())
    version_branch = repo.create_head(git_version_branch)

    # prepare environment variables for git commit and merge operations
    os.environ["GIT_AUTHOR_DATE"] = commit.committed_datetime.isoformat()
    if git_user_name:
        os.environ["GIT_AUTHOR_NAME"] = git_user_name
        os.environ["GIT_COMMITTER_NAME"] = git_user_name
    if git_user_email:
        os.environ["GIT_AUTHOR_EMAIL"] = git_user_email
        os.environ["GIT_COMMITTER_EMAIL"] = git_user_email

    # save local changes
    with contextlib.suppress(GitCommandError):
        repo.git.stash("push", "--staged")

    # get rid of untracked files
    repo.git.clean("-d", "-x", "-f")

    if repo.is_dirty():
        msg = (
            "Invalid state: the repository contains local changes which have "
            "not been staged.  Only staged changes can be merged into the "
            "release branch."
        )
        raise Error(msg)

    version_branch.checkout()

    release_patch_stashed = False
    try:
        repo.git.stash("pop")
        release_patch_stashed = True
    except GitCommandError:
        pass

    # commit release-specific changes on a separate branch for later use
    if release_patch_stashed:
        log.info("Applying local changes to the release…")
        repo.git.add("--all")
        repo.git.commit("--no-verify", "--message", "release")

    # checkout the release branch, creating it if necessary
    try:
        repo.git.checkout(release_branch)
    except GitCommandError:
        # starting from an orphan branch ensures that the first merge commit
        # isn't special and is consistent with later ones
        repo.git.checkout("--orphan", release_branch)
        repo.git.commit(
            "--no-verify",
            "--allow-empty",
            "--message",
            "initialize release branch",
        )

    log.info("Release version: %s", version)

    log.info("Merging changes into the release branch…")
    repo.git.merge(
        "--allow-unrelated-histories",
        "--no-ff",
        "--strategy-option",
        "theirs",
        "--message",
        "merge: upstream changes",
        commit_hash,
    )

    if release_patch_stashed:
        log.info("Merging release patch into the release branch…")
        repo.git.merge(
            "--allow-unrelated-histories",
            "--no-ff",
            "--strategy-option",
            "theirs",
            "--message",
            "merge: release patch",
            git_version_branch,
        )
        repo.git.reset("HEAD~1", "--soft")

    release_msg = f"release {version}"
    if commit_msg is None:
        commit_msg = release_msg

    repo.git.commit("--amend", "--no-verify", "--message", commit_msg)

    log.info("Tagging release…")
    repo.git.tag("--annotate", version, "--message", release_msg)

    if prompt:
        click.confirm(
            f"Push release branch '{release_branch}' to remote?",
            abort=True,
        )

    if not dry_run:
        log.info("Pushing release branch to remote…")
        repo.git.push(
            "--no-verify",
            "--follow-tags",
            "--set-upstream",
            git_remote_name,
            release_branch,
        )
    else:
        log.info("Running in dry-run mode, git push is skipped")


@click.command()
@click.option(
    "--repository-url",
    help="""
    The GitLab or GitHub URL of the repository.

    Examples:

    https://gitlab.com/foo/bar.git
    https://github.com/foo/bar.git

    In GitLab CI jobs the CI_REPOSITORY_URL variable can be used.

    In GitHub Actions the URL can be constructed from GITHUB_SERVER_URL and
    GITHUB_REPOSITORY.
    """,
    required=True,
)
@click.option(
    "--access-token",
    help="""
    The token to use when accessing the git remote.

    For GitLab a Project Access Token or Personal Access Token can be used.
    In GitLab CI jobs the CI_JOB_TOKEN can be used.

    For GitHub a Personal Access Token can be used.
    In GitHub Actions the GITHUB_TOKEN can be used.

    This value can also be provided via the GIT_REMOTE_ACCESS_TOKEN environment
    variable.
    """,
    envvar="GIT_REMOTE_ACCESS_TOKEN",
    required=True,
)
@click.option(
    "--user",
    help="""
    The user to use when accessing the git remote.

    In GitLab CI jobs using the CI_JOB_TOKEN this must be set to
    `gitlab-ci-token`.

    Defaults to "git".
    """,
    required=True,
)
@_repository_path_option()
@click.option(
    "--git-remote-name",
    help="The name of the git remote to set up (will be created if necessary).",
    default="origin",
    required=False,
)
def setup_git_remote(
    repository_url: str,
    access_token: str,
    user: str,
    repository_path: str,
    git_remote_name: str,
) -> None:
    """Configure the git remote for accessing the release branch."""
    repo = get_repo(repository_path)

    remote_url = create_git_remote_url(repository_url, access_token, user)
    create_or_update_remote(repo, git_remote_name, remote_url)


def get_repo(path: str) -> Repo:
    return git.Repo(path, search_parent_directories=False)


def create_git_remote_url(
    repository_url: str, access_token: str, user: str
) -> str:
    orig = urlparse(repository_url)
    netloc = f"{user}:{access_token}@{orig.hostname}"
    url_with_access_token = str(urlunparse(orig._replace(netloc=netloc)))
    return url_with_access_token


def create_or_update_remote(
    repo: Repo, remote_name: str, remote_url: str
) -> None:
    try:
        repo.remote(remote_name).set_url(remote_url)
        log.info("Remote '%s' already exists, URL updated", remote_name)
    except ValueError:
        repo.create_remote(remote_name, remote_url)
        log.info("New remote '%s' created", remote_name)


def init(debug: bool) -> None:
    configure_logging(debug)

    ensure_ci_environment()

    # skip the user's global git configuration ($HOME/.gitconfig) in order to
    # ensure that git operations are performed in a deterministic environment
    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"

    check_git_version(minimum_version=(2, 35))


def configure_logging(debug: bool) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(fmt)
    stdout_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    stdout_handler.addFilter(lambda record: not record.levelno > logging.INFO)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    stderr_handler.setLevel(logging.WARNING)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)


def check_git_version(minimum_version: tuple[int, int]) -> None:
    git_version_output = str(git.Git().execute(["git", "--version"]))
    version_string = git_version_output.strip().split()[-1]
    (major, minor, *rest) = map(int, version_string.split("."))

    if (major, minor) < minimum_version:
        msg = (
            f"Git version {major}.{minor} detected.  Version "
            f"{minimum_version[0]}.{minimum_version[1]} or newer is required."
        )
        raise Error(msg)


def ensure_ci_environment() -> None:
    if not os.getenv("CI"):
        msg = "This command must be run in a CI environment"
        raise Error(msg)


main.add_command(update_release_branch, name="update")
main.add_command(setup_git_remote, name="setup-remote")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Execution failed")
        sys.exit(1)
