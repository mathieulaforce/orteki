# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "av<19",  # faster-whisper 1.2.1 passes metadata_errors, which PyAV 19 removed
#     "faster-whisper>=1.2",
#     "huggingface-hub",
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
"""Check the CUDA setup from cuda-setup.md: dictate, transcribe on the GPU, rewrite on the GPU.

Run with: uv run docs/research/cuda-check.py [--seconds 5] [--audio file.wav] [--compare-cpu]
The first run downloads about 2.5 GB of wheels and about 1.5 GB of models.
"""

import argparse
import ctypes
import os
import subprocess
import tempfile
import time


def vram() -> str:
    import pynvml

    pynvml.nvmlInit()
    try:
        mem = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0))
        return f"{mem.used // 2**20} MiB used, {mem.free // 2**20} MiB free"
    finally:
        pynvml.nvmlShutdown()


def report_gpu() -> None:
    import pynvml

    pynvml.nvmlInit()
    try:
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        driver_cuda = pynvml.nvmlSystemGetCudaDriverVersion_v2()
        print(f"GPU:     {pynvml.nvmlDeviceGetName(h)}")
        print(f"Compute: {'.'.join(map(str, pynvml.nvmlDeviceGetCudaComputeCapability(h)))}")
        print(f"Driver:  {pynvml.nvmlSystemGetDriverVersion()} (CUDA {driver_cuda // 1000}.{driver_cuda % 1000 // 10})")
    finally:
        pynvml.nvmlShutdown()
    print(f"VRAM:    {vram()}")


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


def record(seconds: float) -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="orteki-cuda-check-"), "dictation.wav")
    input(f"\nPress Enter, then speak for {seconds:g} seconds...")
    proc = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1", path])
    time.sleep(seconds)
    proc.terminate()
    proc.wait()
    print("Recorded.")
    return path


def transcribe(audio: str, model_name: str, device: str) -> tuple[str, object]:
    from faster_whisper import WhisperModel

    compute_type = "float16" if device == "cuda" else "int8"
    start = time.perf_counter()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    loaded = time.perf_counter()
    segments, info = model.transcribe(audio)
    text = " ".join(s.text.strip() for s in segments)
    done = time.perf_counter()
    print(
        f"Whisper {model_name} on {device} ({compute_type}): load {loaded - start:.1f}s, "
        f"transcribe {done - loaded:.1f}s for {info.duration:.1f}s of audio, language {info.language}"
    )
    return text, model


def rewrite(text: str, gpu: bool) -> object:
    import llama_cpp
    from huggingface_hub import hf_hub_download

    print(f"\nllama_supports_gpu_offload: {llama_cpp.llama_supports_gpu_offload()}")
    gguf = hf_hub_download("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf")
    start = time.perf_counter()
    llm = llama_cpp.Llama(gguf, n_gpu_layers=-1 if gpu else 0, n_ctx=2048, verbose=False)
    loaded = time.perf_counter()
    out = llm.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": "Clean up this dictated text: fix punctuation and capitalisation, "
                "remove filler words. Keep the language. Reply with the text only.",
            },
            {"role": "user", "content": text},
        ],
        max_tokens=256,
        temperature=0.2,
    )
    done = time.perf_counter()
    tokens = out["usage"]["completion_tokens"]
    print(
        f"Qwen2.5 1.5B on {'GPU' if gpu else 'CPU'}: load {loaded - start:.1f}s, "
        f"{tokens} tokens in {done - loaded:.1f}s ({tokens / (done - loaded):.0f} tok/s)"
    )
    print(f"Rewritten:   {out['choices'][0]['message']['content'].strip()}")
    return llm


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", help="audio file to use instead of recording")
    parser.add_argument("--seconds", type=float, default=5, help="how long to record")
    parser.add_argument("--whisper", default="small", help="faster-whisper model name")
    parser.add_argument("--compare-cpu", action="store_true", help="also run both on CPU")
    args = parser.parse_args()

    report_gpu()
    preload_cuda_libs()
    audio = args.audio or record(args.seconds)

    text, whisper = transcribe(audio, args.whisper, "cuda")
    print(f"Transcript:  {text}")
    llm = rewrite(text, gpu=True)
    print(f"\nVRAM with both loaded: {vram()}")
    del whisper, llm

    if args.compare_cpu:
        print("\n--- CPU, for comparison ---")
        transcribe(audio, args.whisper, "cpu")
        rewrite(text, gpu=False)


if __name__ == "__main__":
    main()
