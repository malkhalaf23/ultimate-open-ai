# Ultimate Open AI

A free local **coding assistant** with internet reading, real LoRA training and opt-in community learning. Runs on Apple Silicon using MLX and a pinned 4-bit Qwen2.5-Coder-1.5B-Instruct base. No paid model API or GPU rental; hardware, electricity and connectivity are still required.

## Start

Requires Apple Silicon, Python 3.11+ and about 2 GB free disk. Setup explicitly installs pinned dependencies and downloads about 880 MB of model files:

```sh
git clone https://github.com/malkhalaf23/ultimate-open-ai.git
cd ultimate-open-ai
python3 bootstrap.py
```

Open http://127.0.0.1:8877/ or double-click Start Assistant.command after setup. Windows/Linux support is not implemented. New installations initially serve the coding base model and can train their own adapter. With the free GitHub CLI authenticated, run `python3 community.py install-release` to explicitly install the maintainer's tested adapter from GitHub Releases, with its source notices and metrics. This trusts the owner-published release, verifies the adapter hash/exact base revision, and keeps a rollback configuration; it does not independently rerun evaluation on the receiving computer.

## Actual weight learning

The quantized base stays frozen; optimization updates **77,824 LoRA parameters** that change effective model weights. This is real QLoRA fine-tuning, separate from saved article retrieval.

- Selected licensed guidance/source/tests from Microsoft TypeScript/VS Code, Google Style Guide/Go, Apple's Swift project, React, AWS SDK and OpenAI Python SDK. Root license notices are reviewed and hash-pinned. This is not every developer document or all open-source software.
- One scan/attempt per Toronto day while **Learn on its own** is enabled. Unchanged corpus skips training. Official-source requests are capped at 3.5 MB/scan; community issue/comment responses separately at 2 MB. No repository code/build/install scripts are executed.
- Default 100 steps, batch 1, 128-token sequences, learning rate 0.00001. Resumes an accepted adapter when available. Replies pause during training to fit an 8 GB Mac; pause is checked every ten optimization steps.
- Stable whole-document train/validation/audit splits. Promotion requires at least 0.5% validation-loss improvement, no >1% audit-loss regression, no decrease on eight Python programs, and actual changed tensors. Rejected candidates keep previous serving weights.
- No private files, generated assistant answers or whole chats enter training. Public pretraining may already have included the official sources; local holdouts do not establish independence from base pretraining.

**First observed round:** 29 files / 8 repositories; 23 train, 3 validation, 3 audit. 100 steps / 12,800 tokens; all 16 adapter tensors changed. Validation loss **2.1094 → 2.0967**, audit **1.8028 → 1.7909**. Python checks **7/8 → 7/8**. Small checks, not broad capability proof. The older general model scored 5/8; that earlier gain came from switching to the coding base. See [TRAINING_REPORT.md](TRAINING_REPORT.md).

The running app checks for due work. The maintainer's six-hour Codex heartbeat is machine-specific and not installed for other users. The Mac must be awake; this is not an always-on cloud service.

## Community learning

Sharing defaults **off**, independently of local training. After explicit public-sharing/MIT consent, human coding messages beginning **Correction:** or **Share lesson:** are queued automatically. At most five per UTC day are submitted as public GitHub issues using the contributor's own free GitHub CLI login. Ordinary messages and assistant answers are excluded. Secret/personal-data screening cannot guarantee detection; only mark material you own and intend to publish.

The owner reviews correctness, provenance and rights, posts an approval bound to the exact content hash, and adds training-approved. Daily sync imports approved lessons into the training corpus; stable holdouts and weight gates still apply. Editing a lesson invalidates its hash approval. Removing approval excludes it from future datasets; already-released weight influence is not erased.

Accepted adapters can become shared GitHub Releases. **More usage alone does not train the model:** more consented, reviewed lessons can grow data and improve shared weights. Parameter count does not automatically grow. No community lesson has yet been received or trained; the first adapter used official-source files only. Full instructions: [CONTRIBUTING.md](CONTRIBUTING.md).

## Internet and storage

Reading uses English/Arabic Wikipedia and explicitly supplied public HTTPS pages, not unrestricted search. Eligible Wikipedia text retains revision/attribution, limited to 12 pages/2 MB daily and 500 pages. Unknown-license pages are transient. Learn on its own persistently pauses reading and future weight jobs; community sharing has a separate pause.

Runtime/data: ~/Library/Application Support/UltimateOpenAI/. Models/cache: ~/Library/Caches/UltimateOpenAI/. Credentials stay local. App port 8877 and authenticated inference port 18879 are loopback-only. Source deployments retain separate durable snapshots. These locations are excluded from GitHub.

## Development

```sh
python3 -W error::ResourceWarning -m unittest -v
python3 deploy.py
```

Restart the existing assistant process after deploying changes. Do not overlap inference and training processes. Generated code can be wrong; test it before use. Python evaluation uses a restricted child with AST/builtin/CPU/time/memory checks, not a general security sandbox. Do not relax it to run arbitrary repository or user programs. See VALIDATION.md for observed checks.

Project code: MIT. [Pinned MLX coding base](https://huggingface.co/mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit), revision b3252a2f97102b1fb1571fec2c9b27219a8536be, Apache 2.0. Source copyrights/licenses remain with their authors; notices accompany the adapter. Historical scratch-model checkpoints were missing and have not been recovered or retrained.
