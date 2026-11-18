# First real coding adapter update — 2026-11-18

Accepted and loaded for local inference. Base: MLX Qwen2.5-Coder-1.5B-Instruct, 4-bit, revision `b3252a2f97102b1fb1571fec2c9b27219a8536be`. Base weights frozen; last four layers' attention q/v LoRA weights trained.

| Measurement | Result |
|---|---:|
| Trainable adapter parameters | 77,824 |
| Changed tensors | 16 |
| Adapter delta L2 | 0.414547 |
| Optimization steps | 100 |
| Training tokens | 12,800 |
| Peak MLX memory | 1.1465 GB |
| Validation text loss | 2.109371 → 2.096664 (~0.60% lower) |
| Audit text loss | 1.802803 → 1.790877 (~0.66% lower) |
| Eight executable Python programs | 7/8 → 7/8 |

The merge_intervals program still failed. The previous general-purpose model passed 5/8; switching to the coding base produced the earlier improvement to 7/8. Do not attribute that gain to this LoRA update.

29 original licensed files from eight official repositories; 23 whole files assigned training, three validation and three audit. Training samples bounded token windows rather than learning every token in every file. Source commits, URLs, hashes, splits and license notices accompany the adapter. No community lessons have yet been received/trained. No synthetic answers/private chats were used.

Gates were fixed before this run: >=0.5% validation-loss improvement, <=1% audit-loss regression, no coding-score decline and actual changed weights. All passed. The small text/Python checks show a modest measured improvement, not broad coding competence or guaranteed future gains. The pretrained base may already know these public files.

Initial adapter SHA-256: `78e24bb06bce408d50534f51505c6602bc878f586f5aefaea25697be7fd78f77`.

Trained/served adapter SHA-256: `249d9bc6666911476cab65d0ee7415c9a2cba1c993940e09a13bdfc076f8e9bf`.

Raw report: `evaluations/coding-weight-update.json`. Actual weights are in the GitHub Release archive with provenance/notices. Later unattended training is configured but has not yet been observed.
