# Community coding lessons

Sharing is optional and off by default. The GitHub issue inbox needs no paid server or repository write access for contributors.

1. Install the free GitHub CLI and authenticate your own account with `gh auth login`.
2. Open **Community learning · opt in**, choose public attribution, and consent to automatic public sharing/training of your own original marked lessons under MIT.
3. Write a coding message beginning `Correction:` or `Share lesson:`. Explain the rule, why it matters, and an original example if useful. The pipeline permits 80–8000 characters; the chat UI currently permits 2000. Exclude generated answers, proprietary/employer-owned code, credentials, private paths and personal/customer data. Automated screening is not a guarantee.
4. The app queues, deduplicates and automatically submits eligible lessons as public issues, at most five per UTC day. Ordinary messages and assistant answers are excluded. Authentication/network errors leave lessons queued. Pause stops future uploads until re-enabled.

No immediate training or automatic approval occurs. Code pull requests are welcome but are not automatically training data. This implementation uses structured GitHub issues for lessons rather than automatically creating forks/PRs.

## Owner approval

Review the lesson JSON for correctness, relevance, provenance and ownership. Do not execute contributor code. Calculate its current ID by passing the JSON to `community.validate()` locally. The repository owner posts exactly:

```text
Training-approved SHA256: <validated 64-character content ID>
```

Then apply the `training-approved` label. Sync requires both the label and the owner's hash-bound comment. Edited text/title/attribution changes the ID and requires a fresh approval. A label alone is insufficient. To reject, close without approval. Remove the label to exclude it from future datasets. Public copies and already-released weight influence cannot be recalled by a local pause; removing influence requires deliberate retraining/unlearning, not implemented here.

```sh
python3 community.py sync
python3 community.py inbox
```

The central daily scan syncs at most 20 approved issues / 2 MB and includes at most 100 approved lessons. Stable content-hash-based document splits reserve some lessons for validation/audit; those never enter optimization. Official-source requirements and the same weight gates remain in place. Training and measurable gains are not guaranteed for each lesson or each day.

## Publish and receive shared weights

After local evaluation accepts an adapter and inference loads its exact hash:

```sh
python3 community.py publish
```

This prepares the active adapter, manifest, source provenance and license notices locally. Package these as `coding-adapter.zip`, with `manifest.json` at the archive root, and publish via GitHub Releases. Include actual metrics and limitations in release notes. Never upload chat databases, settings, credentials, private files or the downloaded base model.

Other users can explicitly install the latest owner-published adapter:

```sh
python3 community.py install-release
```

Requires setup of the exact pinned coding base and an authenticated GitHub CLI. Installation verifies base revision and adapter SHA-256 and keeps a rollback configuration. It trusts the repository owner's release; it does not independently repeat training/evaluation on every receiving machine. No silent remote replacement is enabled.

More reviewed data can grow knowledge and improve effective weights. Model parameter count is fixed; a larger architecture is a separate hardware/training decision.
