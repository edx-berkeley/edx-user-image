# edx-user-image

See this repository's [CONTRIBUTING.md](https://github.com/berkeley-dsep-infra/edx-user-image/blob/main/CONTRIBUTING.md) for instructions. That information will eventually be migrated to docs.datahub.berkeley.edu.

# Building the image locally

You should use [repo2-docker](https://repo2docker.readthedocs.io/en/latest/) to build and use/test the image on your own device before you push and create a PR.  It's better (and typically faster) to do this first before using CI/CD.  There's no need to waste Github Action minutes to test build images when you can do this on your own device!

Run `repo2docker` from inside the cloned image repo.  To run on a linux/WSL2 linux shell:
```
repo2docker . # <--- the path to the repo
```

If you are using an ARM CPU (Apple M* silicon), you will need to run `jupyter-repo2docker` with the following arguments:

```
jupyter-repo2docker --user-id=1000 --user-name=jovyan \
  --Repo2Docker.platform=linux/amd64 \
  --target-repo-dir=/home/jovyan/.cache \
  -e PLAYWRIGHT_BROWSERS_PATH=/srv/conda \
  . # <--- the path to the repo
```

If you just want to see if the image builds, but not automatically launch the server, add `--no-run` to the arguments (before the final `.`).

## Continuous Integration (CI)

### Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `yaml-lint.yaml` | `pull_request` | Lints all YAML files via the shared workflow in `berkeley-dsep-infra/update-deployment` |
| `build-test-image.yaml` | `pull_request` | Builds and tests the image via the shared workflow in `berkeley-dsep-infra/update-deployment` |
| `grader-check.yml` | `pull_request_target` | Comprehensive validation: builds the PR image, fetches ALL notebooks from all courses (88ex, 88bx, 88cx, 8x) and all assignments, and validates that student notebooks fail grader checks (solutions are stripped) while solution notebooks pass all grader checks |
| `build-push-create-pr.yaml` | Push of a version tag (`X.Y.Z`) or manual `workflow_dispatch` | Builds and pushes the image to Google Artifact Registry, tags it with the version number, and opens a PR in [edx-hub](https://github.com/edx-berkeley/edx-hub) to update the deployment image tag |

The `build-test-image.yaml` and `yaml-lint.yaml` workflows ignore changes to `README.md`, `CONTRIBUTING.md`, `LICENSE`, `.github/**`, and `images/**`. The `grader-check.yml` workflow ignores the same paths.

### Releases

Push a version tag in the format `X.Y.Z` to trigger a production release build:

```bash
git tag X.Y.Z
git push upstream X.Y.Z. <-- assuming your origin is your fork
```

CI will build the image, push it to Google Artifact Registry, and automatically open a PR in `edx-hub` to update the deployed image tag.

### Slack notifications

CI results are posted to the **#edx-hub-ci** channel in the **UCB DS External** Slack workspace. To request access, contact a team member or reach out to sean.smorris@berkeley.edu.

The following workflows post to Slack on every run (success or failure):
- `grader-check.yml` — on every PR
- `build-push-create-pr.yaml` — on every release tag build

### Repository variables and secrets

The following must be configured on the repository (or the `edx-berkeley` organization) for CI to function:

**Variables (`vars.*`):**

| Name | Description |
|---|---|
| `IMAGE` | Full image path in Google Artifact Registry (e.g., `data8x-scratch/user-images/edx-user-image`) |
| `HUB` | Deployment name used to find and update the image tag in edx-hub |
| `EDX_IMAGE_BUILDER_APP_ID` | GitHub App ID used to open PRs in edx-hub |
| `IMAGE_BUILDER_BOT_EMAIL` | Git author email for automated commits to edx-hub |
| `IMAGE_BUILDER_BOT_NAME` | Git author name for automated commits to edx-hub |
| `COURSE_CONTENT_READER_APP_ID` | GitHub App ID for reading autograder/student/solution repos |
| `COURSE_CONTENT_READER_INSTALLATION_ID` | Installation ID for the course-content-reader GitHub App |

**Secrets (`secrets.*`):**

| Name | Description |
|---|---|
| `GAR_SECRET_KEY_EDX` | GCP service account JSON key with push access to Google Artifact Registry |
| `EDX_IMAGE_BUILDER_PRIVATE_KEY` | Private key for the GitHub App that opens PRs in edx-hub |
| `COURSE_CONTENT_READER_PRIVATE_KEY` | Private key for the GitHub App that reads autograder/student/solution repos (shared with otter-service and xDevs) |
| `SLACK_WEBHOOK_URL` | Incoming webhook URL for the `#edx-hub-ci` Slack channel |
