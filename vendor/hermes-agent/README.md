# Hermes Vendor Materialization

This directory stores the reproducibility metadata for the customized Hermes
runtime used by this distribution.

## Strategy

The full local Hermes worktree is too large to vendor directly, so this repo
ships:

- upstream commit lock
- local patch bundle
- overlay files for untracked runtime additions
- bootstrap script

## Files

- `UPSTREAM.lock`
  pinned upstream commit to materialize from
- `patches/0001-hermes-local-customizations.patch`
  local patch bundle generated from the current customized Hermes tree
- `overlay/`
  runtime files that must be copied verbatim after patch apply
  (used for untracked additions like new modules)

## Materialization

Use:

```bash
./scripts/setup_host_runtime.sh
```

That flow clones the upstream Hermes repo at the locked commit, applies the
patch bundle into `runtime/hermes-agent`, creates a virtualenv, and installs the
host runtime dependencies needed for the semi-containerized server layout.
