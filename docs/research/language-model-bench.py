# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "av<19",  # faster-whisper 1.2.1 passes metadata_errors, which PyAV 19 removed
#     "faster-whisper>=1.2",
#     "huggingface-hub",
#     "jinja2>=3.1",
#     "llama-cpp-python==0.3.36",
#     "nvidia-cublas-cu12>=12.8,<13",
#     "nvidia-cuda-runtime-cu12>=12.4,<13",
#     "nvidia-ml-py>=13",
# ]
#
# [tool.uv.sources]
# llama-cpp-python = { index = "llama-cpp-cu124" }
#
# [[tool.uv.index]]
# name = "llama-cpp-cu124"
# url = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
# explicit = true
# ///
"""Benchmark a candidate language model next to Whisper large-v3-turbo (default-language-model.md).

Loads Whisper turbo on the GPU and transcribes a short clip, then loads the language model fully
offloaded and runs every case in language-model-prompts.json. Appends one JSON line per run to
--out. Run each model in its own process so VRAM figures start clean:

    for m in qwen3.5-4b gemma4-e4b ...; do uv run docs/research/language-model-bench.py $m; done
"""

import argparse
import ctypes
import datetime
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).parent

MODELS = {
    "qwen3.5-2b": ("unsloth/Qwen3.5-2B-GGUF", "Qwen3.5-2B-Q4_K_M.gguf"),
    "qwen3.5-4b": ("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf"),
    "qwen3.5-9b": ("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf"),
    "qwen3-4b-2507": ("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
    "gemma4-e2b": ("unsloth/gemma-4-E2B-it-GGUF", "gemma-4-E2B-it-Q4_K_M.gguf"),
    "gemma4-e4b": ("unsloth/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_K_M.gguf"),
    "ministral3-3b": (
        "mistralai/Ministral-3-3B-Instruct-2512-GGUF",
        "Ministral-3-3B-Instruct-2512-Q4_K_M.gguf",
    ),
    "ministral3-8b": (
        "mistralai/Ministral-3-8B-Instruct-2512-GGUF",
        "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf",
    ),
}

# Appended to the step's instructions with --hint: a recipe knows its language (CONTEXT.md).
HINTS = {
    "nl": "The text is in Dutch. Reply in Dutch.",
    "en": "The text is in English. Reply in English.",
    "mixed": "The text mixes Dutch and English. Reply in the same mix: keep every word in the "
    "language it was written in, and do not translate the English parts.",
}

SPEECH = (
    "Okay, so for tomorrow's meeting I want to go over the release plan, the open bugs "
    "and the budget for next quarter. Please send me your notes before noon."
)


def vram_used() -> int:
    import pynvml

    pynvml.nvmlInit()
    try:
        return pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0)).used // 2**20
    finally:
        pynvml.nvmlShutdown()


class PeakVram:
    """Samples used VRAM every 50 ms in a thread and keeps the maximum."""

    def __init__(self) -> None:
        self.peak = vram_used()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(0.05):
            self.peak = max(self.peak, vram_used())

    def stop(self) -> int:
        self._stop.set()
        self._thread.join()
        return self.peak


def preload_cuda_libs() -> None:
    # Neither library finds the pip-installed CUDA libs on its own (cuda-setup.md, section 3).
    import nvidia.cublas
    import nvidia.cuda_runtime

    for pkg, names in (
        (nvidia.cuda_runtime, ["libcudart.so.12"]),
        (nvidia.cublas, ["libcublasLt.so.12", "libcublas.so.12"]),
    ):
        for name in names:
            ctypes.CDLL(os.path.join(pkg.__path__[0], "lib", name), mode=ctypes.RTLD_GLOBAL)


def load_whisper(compute_type: str) -> tuple[object, dict]:
    from faster_whisper import WhisperModel

    wav = os.path.join(tempfile.mkdtemp(prefix="orteki-lm-bench-"), "speech.wav")
    subprocess.run(["espeak-ng", "-v", "en", "-w", wav, SPEECH], check=True)
    start = time.perf_counter()
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type=compute_type)
    loaded = time.perf_counter()
    segments, _ = model.transcribe(wav, beam_size=5)
    text = " ".join(s.text.strip() for s in segments)
    done = time.perf_counter()
    return model, {
        "compute_type": compute_type,
        "load_s": round(loaded - start, 2),
        "transcribe_s": round(done - loaded, 2),
        "transcript": text,
    }


def render_prompt(llm: object, messages: list[dict]) -> str:
    """Render the GGUF's own chat template, with thinking switched off where the template has it."""
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    meta = llm.metadata  # type: ignore[attr-defined]
    vocab = llm._model  # type: ignore[attr-defined]

    def token_text(key: str) -> str:
        tid = int(meta.get(key, -1))
        return vocab.token_get_text(tid) if tid >= 0 else ""

    def raise_exception(msg: str) -> None:
        raise ValueError(msg)

    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = raise_exception
    env.globals["strftime_now"] = lambda fmt: datetime.datetime.now().strftime(fmt)
    template = env.from_string(meta["tokenizer.chat_template"])
    return template.render(
        messages=messages,
        add_generation_prompt=True,
        enable_thinking=False,
        bos_token=token_text("tokenizer.ggml.bos_token_id"),
        eos_token=token_text("tokenizer.ggml.eos_token_id"),
    )


def generate(llm: object, prompt: str, max_tokens: int) -> dict:
    # The rendered template already starts with BOS where the model wants one; tokenizing the
    # string in llm() would add a second.
    prompt_ids = llm.tokenize(prompt.encode(), add_bos=False, special=True)  # type: ignore[attr-defined]
    start = time.perf_counter()
    first = None
    pieces = []
    finish = None
    for chunk in llm(  # type: ignore[operator]
        prompt_ids, max_tokens=max_tokens, temperature=0.0, repeat_penalty=1.0, stream=True
    ):
        if first is None:
            first = time.perf_counter()
        pieces.append(chunk["choices"][0]["text"])
        finish = chunk["choices"][0]["finish_reason"] or finish
    end = time.perf_counter()
    text = "".join(pieces)
    tokens = len(llm.tokenize(text.encode(), add_bos=False, special=True))  # type: ignore[attr-defined]
    first = first or end
    return {
        "output": text,
        "finish": finish,
        "prompt_tokens": len(prompt_ids),
        "tokens": tokens,
        "first_token_s": round(first - start, 3),
        "total_s": round(end - start, 3),
        "decode_tok_s": round((tokens - 1) / (end - first), 1) if tokens > 1 else None,
    }


def check(case: dict, output: str) -> dict:
    low = output.lower()
    # "a|b" accepts either spelling; vocabulary cases must match the term's exact capitalisation.
    exact = case.get("case_sensitive", False)

    def has(s: str) -> bool:
        return any((alt in output) if exact else (alt.lower() in low) for alt in s.split("|"))

    missing = [s for s in case["must"] if not has(s)]
    present = [s for s in case["must_not"] if s.lower() in low]
    # A leaked thinking block or a chatty preamble means the step output is unusable as-is.
    preambles = ("<think", "</think", "here is", "hier is", "sure,", "natuurlijk,")
    leaked = any(t in low for t in preambles)
    return {"missing": missing, "forbidden": present, "leaked": leaked}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--whisper", default="float16", help="Whisper compute type, or 'none'")
    parser.add_argument("--n-ctx", type=int, default=4096)
    parser.add_argument("--no-flash-attn", action="store_true")
    parser.add_argument("--hint", action="store_true", help="tell the model the case's language")
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--out", default=str(HERE / "language-model-results.jsonl"))
    args = parser.parse_args()

    preload_cuda_libs()
    import llama_cpp
    from huggingface_hub import hf_hub_download

    repo, filename = MODELS[args.model]
    gguf = hf_hub_download(repo, filename)
    run: dict = {
        "model": args.model,
        "gguf": f"{repo}/{filename}",
        "gguf_mib": os.path.getsize(gguf) // 2**20,
        "n_ctx": args.n_ctx,
        "flash_attn": not args.no_flash_attn,
        "hint": args.hint,
        "llama_cpp_python": llama_cpp.__version__,
        "date": datetime.date.today().isoformat(),
    }
    run["vram_idle_mib"] = vram_used()

    whisper = None
    if args.whisper != "none":
        whisper, run["whisper"] = load_whisper(args.whisper)
    run["vram_whisper_mib"] = vram_used()

    peak = PeakVram()
    start = time.perf_counter()
    try:
        llm = llama_cpp.Llama(
            gguf,
            n_gpu_layers=-1,
            n_ctx=args.n_ctx,
            flash_attn=not args.no_flash_attn,
            verbose=False,
        )
    except Exception as e:  # a model that does not fit is a result, not a crash
        run["error"] = f"{type(e).__name__}: {e}"
        run["vram_peak_mib"] = peak.stop()
        print(json.dumps(run))
        with open(args.out, "a") as f:
            f.write(json.dumps(run, ensure_ascii=False) + "\n")
        return
    run["load_s"] = round(time.perf_counter() - start, 2)
    run["vram_loaded_mib"] = vram_used()

    prompts = json.loads((HERE / "language-model-prompts.json").read_text())
    generate(llm, render_prompt(llm, [{"role": "user", "content": "Say OK."}]), 8)  # warm-up

    run["cases"] = []
    for case in prompts["cases"]:
        system = prompts["steps"][case["step"]]
        if args.hint:
            system += " " + HINTS[case["lang"]]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": case["text"]},
        ]
        result = generate(llm, render_prompt(llm, messages), args.max_tokens)
        result |= {"id": case["id"], **check(case, result["output"])}
        run["cases"].append(result)
        flags = "".join(
            [
                f" missing={result['missing']}" if result["missing"] else "",
                f" forbidden={result['forbidden']}" if result["forbidden"] else "",
                " LEAKED" if result["leaked"] else "",
            ]
        )
        print(f"[{case['id']}] {result['decode_tok_s']} tok/s{flags}")
        print(f"  {result['output'].strip()}\n")

    run["vram_peak_mib"] = peak.stop()
    speeds = [c["decode_tok_s"] for c in run["cases"] if c["decode_tok_s"]]
    run["median_decode_tok_s"] = sorted(speeds)[len(speeds) // 2]
    run["median_case_s"] = sorted(c["total_s"] for c in run["cases"])[len(run["cases"]) // 2]
    run["checks_failed"] = sum(
        bool(c["missing"] or c["forbidden"] or c["leaked"]) for c in run["cases"]
    )
    summary = {k: v for k, v in run.items() if k != "cases"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    with open(args.out, "a") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")
    del llm, whisper


if __name__ == "__main__":
    main()
