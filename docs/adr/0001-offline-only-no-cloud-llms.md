# Offline only: no cloud language models in the product

orteki never sends audio or text off the machine: every speech and language model runs locally. Cloud providers (Claude, Gemini, ChatGPT) were considered, including driving the owner's existing subscriptions through their CLIs, and deliberately left out to keep the product private and dependency-free. Don't add a cloud provider without superseding this ADR. Cloud AI is fine for *building* orteki (the software factory), just not inside it.
