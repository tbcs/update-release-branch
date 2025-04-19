# update-release-branch

[update-release-branch](https://github.com/tbcs/update-release-branch) is a Git
tool for managing a single, continuous release branch with release-specific
changes.

## Use Case

This tool is for software repositories that build and reference their own
versioned artifacts. It supports a release workflow where the Git repository
acts as a distribution channel for versioned artifacts that are built from the
repository itself. By automating the update and tagging of a release branch,
this tool ensures a clean, auditable history of releases.

It is useful when:

- the repository produces artifacts (Docker images, scripts, …) that are meant
  to be versioned
- these artifacts are referenced from within the same repository
- you want to support both:
  - referencing the main branch for the latest artifact version
  - referencing a specific tag on the release branch for a _stable_, _versioned_
    release

This setup is typical for:

- [pre-commit](https://pre-commit.com/) hooks that run a tool built from the
  same repo (e.g. via a Docker image)
- reusable GitHub Actions that refer to their own Docker image or other
  versioned content

If the repository in question doesn't produce versioned artifacts that it _also_
consumes, this tool likely isn't needed.

## Usage

Designed to run inside a CI pipeline — such as GitHub Actions or GitLab CI —
update-release-branch automates the process of updating a release branch by
merging in changes from the main branch and tagging the result.

Before invoking the tool, any release-specific changes must be prepared and
staged using Git. These staged changes will be included in the merge commit on
the release branch. Unstaged changes are not included and will cause the tool to
fail.

A typical usage flow looks like this:

1. Check out the main branch.
2. Perform your build as usual: compile, run tests, build artifacts, etc.
3. Apply any release-specific changes (e.g. version bumps, metadata updates).
4. Stage those changes using `git add`.
5. Run this tool to update the release branch and tag the release.

Running the tool involves calling the `update` subcommand. In CI environments
where the Git remote requires authentication, you also need to run the
`setup-remote` subcommand beforehand to configure push access. You'll find
examples and CI-specific patterns in the sections below.

For a complete list of available options and subcommands, run:

```sh
update-release-branch --help
```

### Using update-release-branch with GitHub

To integrate `update-release-branch` into a GitHub-hosted project, add the
`tbcs/update-release-branch` action — provided by this repository — to your
GitHub Actions workflow.

See below for required permissions, inputs, and a full example GitHub Actions
workflow.

#### Required Permissions

| Scope            | Why it's needed                   |
| ---------------- | --------------------------------- |
| `contents:write` | to push changes to the repository |

#### Inputs

| Name              | Description                                                                          | Required | Default                                                                                                                                         |
| ----------------- | ------------------------------------------------------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `version`         | The version of the release                                                           | yes      |                                                                                                                                                 |
| `release-branch`  | The name of the release branch                                                       | no       | "release"                                                                                                                                       |
| `repository-path` | The location of the repository                                                       | no       | `$GITHUB_WORKSPACE`                                                                                                                             |
| `git-user-name`   | The author/committer name to use for the merge commit on the release branch          | no       | "github-actions\[bot\]" (as [suggested](https://github.com/actions/checkout/pull/1707) by `actions/checkout`)                                   |
| `git-user-email`  | The author/committer email address to use for the merge commit on the release branch | no       | "41898282+github-actions\[bot\]@users.noreply.github.com" (as [suggested](https://github.com/actions/checkout/pull/1707) by `actions/checkout`) |

#### Example GitHub Actions workflow

```yaml
name: Release

on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  release:
    name: Release
    runs-on: ubuntu-24.04
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set version
        run: |
          commit_sha="$(echo ${{ github.sha }} | cut -c1-8)"
          version="$(date -u +%Y%m%d%H%M%S).${commit_sha}"
          echo "VERSION=$version" >> "$GITHUB_ENV"

      # [ … perform build, publish versioned artifacts … ]

      - name: Prepare release
        run: |
          # make release-specific changes
          sed -i "s foobar:latest foobar:${VERSION} g" versions.txt
          git add versions.txt

      - name: Update release branch
        uses: tbcs/update-release-branch@v1
        with:
          version: "${{ env.VERSION }}"
          release-branch: "release"

      - name: Create GitHub Release
        run: |
          curl -fsSL \
            -X POST \
            -H "Accept: application/vnd.github+json" \
            -H "Authorization: Bearer ${{ secrets.GITHUB_TOKEN }}" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            https://api.github.com/repos/${{ github.repository }}/releases \
            -d '{
              "tag_name": "${{ env.VERSION }}"
            }'
```

### Using update-release-branch with GitLab

When using update-release-branch for a repository that's hosted on GitLab,
integration requires defining a job in your GitLab CI pipeline. That job should
use the `tibi/update-release-branch` Docker image and invoke the included tool
as follows:

1. `update-release-branch setup-remote` — configures Git authentication so the
   CI job can push changes
2. `update-release-branch update` — performs the actual update to the release
   branch and creates a Git tag

#### Configuring Git authentication

`update-release-branch` requires an authentication token in order to push
changes to the repository. The following types are supported:

- [Project access token](https://docs.gitlab.com/ee/user/project/settings/project_access_tokens.html)
- [Personal access token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html)
- [`CI_JOB_TOKEN`](https://docs.gitlab.com/17.10/ci/jobs/ci_job_token/#allow-git-push-requests-to-your-project-repository)

##### Using project and personal access tokens

To push to a repository, GitLab requires at least the `Developer` role. Use this
role when creating a _project access token_ for use with update-release-branch.
When using a _personal access token_, ensure the user has the `Developer` role
or higher in the respective project.

The token should have the following scopes:

| Scope              | Why it's needed                                |
| ------------------ | ---------------------------------------------- |
| `write_repository` | to push changes to the repository              |
| `api` (optional)   | to create a GitLab Release using `release-cli` |

Make the token accessible to the job by configuring it as a CI/CD variable (e.g.
`GIT_REMOTE_ACCESS_TOKEN`). Then configure Git authentication as follows:

```sh
update-release-branch setup-remote \
  --repository-url "$CI_REPOSITORY_URL" \
  --access-token "$GIT_REMOTE_ACCESS_TOKEN" \
  --user "git"
```

##### Using `CI_JOB_TOKEN`

> ⚠️ As of April 2025, this feature only works on self-managed GitLab instances.
> See:
> [gitlab-org/gitlab#389060](https://gitlab.com/gitlab-org/gitlab/-/issues/389060)

If you're using the built-in `CI_JOB_TOKEN`, configure the Git authentication
like this:

```sh
update-release-branch setup-remote \
  --repository-url "$CI_REPOSITORY_URL" \
  --access-token "$CI_JOB_TOKEN" \
  --user "gitlab-ci-token"
```

#### Example GitLab CI pipeline

```yaml
variables:
  RELEASE_BRANCH: "release"

stages:
  - build
  - release

workflow:
  rules:
    - if: $CI_COMMIT_BRANCH == $RELEASE_BRANCH
      when: never
    - if: $CI_COMMIT_TAG
      when: never
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH

set-version:
  stage: build
  rules:
    - if: "$CI_COMMIT_BRANCH == 'main'"
  image: library/alpine:3.21
  script:
    - echo "VERSION=$(date -u +%Y%m%d%H%M%S).${CI_COMMIT_SHORT_SHA}" >>
      variables.env
  artifacts:
    reports:
      dotenv: variables.env

# [ … perform build, publish versioned artifacts … ]

prepare-release:
  stage: release
  rules:
    - if: "$CI_COMMIT_BRANCH == 'main'"
  resource_group: release
  needs:
    - job: set-version
  image: library/alpine:3.21
  script:
    # make release-specific changes
    - sed -i "s foobar:latest foobar:${VERSION} g" versions.txt
  artifacts:
    paths:
      - versions.txt
    expire_in: 1h

update-release-branch:
  stage: release
  rules:
    - if: "$CI_COMMIT_BRANCH == 'main'"
      when: manual
  resource_group: release
  needs:
    - job: set-version
    - job: prepare-release
      artifacts: true
  image: tibi/update-release-branch:latest
  # prettier-ignore
  script:
    - git add versions.txt
    # with project or personal access token:
    - update-release-branch setup-remote
      --repository-url "$CI_REPOSITORY_URL"
      --access-token "$GIT_REMOTE_ACCESS_TOKEN"
      --user "git"
    # with CI Job Token:
    - update-release-branch setup-remote
      --repository-url "$CI_REPOSITORY_URL"
      --access-token "$CI_JOB_TOKEN"
      --user "gitlab-ci-token"
    - update-release-branch update
      --version "$VERSION"
      --release-branch "$RELEASE_BRANCH"
      --git-user-name "GitLab CI"
      --git-user-email "gitlab-ci@${CI_SERVER_HOST}"

release:
  stage: release
  rules:
    - if: "$CI_COMMIT_BRANCH == 'main'"
  resource_group: release
  needs:
    - job: set-version
    - job: update-release-branch
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  script:
    - echo "Creating release"
  release:
    tag_name: "$VERSION"
    description: "$VERSION"
```

### Using update-release-branch in other environments

While update-release-branch was designed primarily for use with GitHub Actions
and GitLab CI, it can also be used in other CI environments or run manually on a
local machine — as long as Git authentication is correctly configured using the
`setup-remote` subcommand.

> ⚠️ **Caution when running locally:** The `update` subcommand performs a
> destructive `git clean` operation. To avoid accidental data loss when running
> outside of CI, the tool checks for the presence of the `CI` environment
> variable and will refuse to run if it's not set.
>
> If you're certain you want to run it locally, you can set `CI=true` in your
> environment before invocation — but use this with care.
