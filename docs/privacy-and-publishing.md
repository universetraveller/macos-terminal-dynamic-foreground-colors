# Privacy and publishing

## What this archive contains

The repository is a fresh, latest-build-only release with **one root commit on
`main`**. It does not carry previous commits, branches, tags, reflogs, unreachable
objects, or old session recordings.

Public content is limited to original code/prose, generic model examples, and
Terminal 2.15 (488.9) build identifiers and scalar-check results. No captured
palette, profile export, actual runtime OS version, session date/timezone,
account name, home path, hostname, IP address, credential, or remote URL is
bundled. Reference colors in `data/examples.json` are explicit illustrative
inputs, not a record of a local profile.

The executable hash, Mach-O slice UUIDs, CPU subtypes, and SDK/minimum-OS values
identify the application being studied. The UUID fields are Mach-O UUIDs, not a
Mac hardware UUID. Input paths and the full Info.plist are not copied into the
archived check result.

The root commit uses the generic identity `Project Contributors
<contributors@example.invalid>` and a fixed UTC timestamp. ZIP entry times are
also fixed, and owner-specific ZIP extra fields are absent. The distributed Git
index has no recorded working-tree timestamps, device/inode values, UID, or GID.
Git configuration contains no account settings or remotes. These choices avoid
carrying local author or filesystem metadata in the downloadable repository.

The live probe only prints to stdout. Running it locally does not automatically
publish anything. Its output includes current color settings; `local-evidence/`
and `local-probe*` are ignored by Git. Review anything you choose to share.
This audit describes the supplied archive, not future files or commits added to it.

## Use the supplied repository

Extract the ZIP into a **new directory** and use its included `.git` directory.
Do not copy an old `.git` directory into it or merge an old repository's history.
Confirm the local state:

```sh
git rev-list --count HEAD
# 1

git log --format=fuller --max-count=1
git remote -v
# no remotes configured
```

There is no need to initialize Git again or make another initial commit.

## Publish to a new empty GitHub repository

Create the remote repository without an initial README/license commit. From the
extracted project directory, substitute your actual repository URL:

```sh
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

## Replace an existing GitHub main branch

Use the fresh local repository, not the earlier checkout. These commands replace
the remote `main` history with the single supplied commit. First set the remote
URL, then read its current main commit without fetching old objects:

```sh
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git ls-remote --exit-code origin refs/heads/main
```

Copy the commit hash printed by the last command and replace `OLD_MAIN_COMMIT`
in the following command:

```sh
git push --force-with-lease=refs/heads/main:OLD_MAIN_COMMIT -u origin main:main
```

The explicit lease rejects the update if remote `main` moved since that hash
was read. If it rejects, inspect the new remote state before retrying. Reading
with `ls-remote` avoids downloading previous history into this clean local repo.
If the repository uses a different default branch, adapt the branch target
accordingly.

Replacing `main` does not remove other remote branches or tags. List them with
`git ls-remote --heads --tags origin`, review them, and remove old references
separately if you want the remote to expose only this history. Collaborators
should use a fresh clone rather than merge previous history back in.

Rewriting a branch does not erase prior downloads, other people's clones/forks,
or every cached view and pull-request reference. GitHub documents these limits
and additional cleanup steps in
[Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
