# CUDA / GPU setup for orteki

Date: 2026-10-26. Versions checked: ctranslate2 4.8.4 (2026-10-24), faster-whisper 1.2.1 (PyPI; master active to 2026-10-16), llama-cpp-python 0.3.36 (2026-10-01), uv 0.13.5, nvidia-ml-py 13.615.71.

## Summary / recommendation

- **Use one CUDA 12 userspace set, from pip wheels.** Ship `nvidia-cublas-cu12` (12.9.x) and `nvidia-cuda-runtime-cu12` (12.9.x) in a `cuda` extra. You do not need cuDNN: the CTranslate2 PyPI wheels have been built with `WITH_CUDNN=OFF` since 4.6.3. For llama.cpp, use the prebuilt **`cu124`** llama-cpp-python wheel, so the CUDA major (12) matches CTranslate2's. The user needs only the NVIDIA driver, which provides `libcuda.so.1` and `libnvidia-ml.so.1`.
- **Preload the pip-installed libs yourself.** Neither library finds `site-packages/nvidia/*/lib` on its own. Before you import `llama_cpp` or create any CUDA `WhisperModel`, call `ctypes.CDLL(<abs path>, RTLD_GLOBAL)` on `libcudart.so.12`, `libcublasLt.so.12` and `libcublas.so.12`. Do not touch `LD_LIBRARY_PATH`. **I tested this on the dev machine:** with the preload, faster-whisper (float16) and llama.cpp (full offload) both ran on the GPU in one process. Without it, both failed.
- **Express it in uv** with two mutually exclusive extras (`cpu` and `cuda`) that pin `llama-cpp-python` to explicit indexes through `[tool.uv.sources]` (`uv lock` validated, see Q4). faster-whisper/ctranslate2 come from PyPI in both cases: the same wheel does CPU and CUDA.
- **For fit, use NVML (`nvidia-ml-py`, pure Python, 58 KB)** for free and total VRAM and compute capability. Use `ctranslate2.get_cuda_device_count()` and `llama_cpp.llama_supports_gpu_offload()` as "can this backend actually use the GPU" checks. On any failure, fall back to CPU.
- **Caveats:**
  - The CUDA llama wheel is about **1.78 GB**, plus about 554 MB for cuBLAS.
  - The CUDA llama wheel is built **without AVX2/FMA/F16C**, so CPU-side work in that build is slower.
  - It hard-links `libcuda.so.1`, so `import llama_cpp` fails outright on machines without the NVIDIA driver. That is why `cpu` must be a separate extra, not a runtime switch.
  - `[tool.uv.sources]` is uv-only and is not seen by people who install orteki from PyPI. The distribution story is an open question.

## 1. faster-whisper / CTranslate2

- **CUDA version.** The Linux x86-64 wheels are built against **CUDA 12.8** (nvcc 12.8.93, cuBLAS 12.8.4.1), with `-DWITH_CUDA=ON -DWITH_CUDNN=OFF -DCUDA_DYNAMIC_LOADING=ON -DCUDA_ARCH_LIST="Common"` ([prepare_build_environment_linux.sh](https://github.com/OpenNMT/CTranslate2/blob/master/python/tools/prepare_build_environment_linux.sh)). CUDA 12.8 support was added in v4.6.3 ([CHANGELOG](https://github.com/OpenNMT/CTranslate2/blob/master/CHANGELOG.md)).
- **cuDNN is no longer needed.** v4.6.3 (2026-01-06) added a "Conv1d pure CUDA implementation (#1949), makes cuDNN an optional dependency" ([CHANGELOG](https://github.com/OpenNMT/CTranslate2/blob/master/CHANGELOG.md)), and the wheel build sets `WITH_CUDNN=OFF`. I confirmed both points:
  - The 4.8.4 cp312 wheel's `libctranslate2` contains no cuDNN reference (`strings`/`readelf`).
  - Whisper-tiny ran on the GPU with no cuDNN installed (see Local machine).
- **Stale upstream docs.** The [faster-whisper README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md) still says "cuBLAS for CUDA 12" plus "cuDNN 9 for CUDA 12". CTranslate2's own [installation.md](https://github.com/OpenNMT/CTranslate2/blob/master/docs/installation.md) still says cuDNN 8. Both are stale with respect to the build script.
- **The only CUDA lib needed at runtime is `libcublas.so.12`, plus its `libcublasLt.so.12`.** The CUDA runtime is linked statically: the wheel's only CUDA references are `libcublas.so.12` and `libcuda.so.1`. cuBLAS is `dlopen`ed lazily by bare SONAME: `dlopen("libcublas.so." STR(CUBLAS_VER_MAJOR), RTLD_LAZY)` in [src/cuda/cublas_stub.cc](https://github.com/OpenNMT/CTranslate2/blob/master/src/cuda/cublas_stub.cc). On failure it throws `Library libcublas.so.12 is not found or cannot be loaded`. On Linux the Python `__init__` does no path setup; the Windows-only DLL logic is in [python/ctranslate2/__init__.py](https://github.com/OpenNMT/CTranslate2/blob/master/python/ctranslate2/__init__.py).
- **Pip wheels for the libs work, but are not found automatically.**
  - faster-whisper documents `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*` plus an `LD_LIBRARY_PATH` that "must be set before launching Python" ([README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md#install-with-pip-linux-only)).
  - Preloading with `ctypes.CDLL(abs_path, RTLD_GLOBAL)` is a working alternative that needs no re-exec. glibc's `dlopen` returns an already-loaded object with a matching SONAME. I verified this here.
  - `nvidia-cublas-cu12` 12.9.2.10 ships `libcublas.so.12` with `RUNPATH $ORIGIN`, so its `libcublasLt.so.12` resolves by itself (checked with `readelf`).
- **Gotchas:**
  - CUDA 13 is not supported by the PyPI wheels: they `dlopen` `.so.12` only.
  - Errors are lazy: `get_cuda_device_count()` returns 1 even when cuBLAS is missing. The failure only appears on the first GPU op. Treat "model loaded and one tiny inference succeeded" as the real GPU check.
  - The RTX 2070 (cc 7.5) reports compute types `int8, int8_float16, int8_float32, float16, float32`, with no bf16.
  - **PyAV 19 breaks decoding of audio files.** faster-whisper 1.2.1 declares only `av>=11`, but its `decode_audio` calls `av.open(..., metadata_errors="ignore")`. With PyAV 19.0.2 that raises `TypeError: open() got an unexpected keyword argument 'metadata_errors'`. Pin `av<19` until faster-whisper adapts. Found when running `cuda-check.py`; not triggered when passing a NumPy array instead of a file.
- **Other:** faster-whisper 1.2.1 pins `ctranslate2>=4.0,<5` and also pulls `onnxruntime` (used for Silero VAD) ([PyPI metadata](https://pypi.org/project/faster-whisper/1.2.1/)). That is CPU onnxruntime, and it does not conflict with the CUDA libs.

## 2. llama-cpp-python

- **Prebuilt CUDA wheels exist** ([README, Installation → CUDA](https://github.com/abetlen/llama-cpp-python/blob/main/README.md)):
  - `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/<cu118|cu121|cu122|cu123|cu124|cu125|cu130|cu132>`.
  - Supported compute capability: 6.0+ for CUDA 12 wheels, 7.5+ for CUDA 13 wheels. Python 3.10–3.12.
  - All of those indexes carry **0.3.36** (checked 2026-10-26). There are also `cpu`, `metal`, `rocm72` and `vulkan` indexes.
  - The wheels are `py3-none-manylinux_2_35_x86_64` (interpreter-agnostic, glibc ≥ 2.35).
  - On PyPI, 0.3.36 is **sdist only** (76 MB), so a plain install compiles from source.
- **Wheel build details** ([build-wheels-cuda.yaml](https://github.com/abetlen/llama-cpp-python/blob/main/.github/workflows/build-wheels-cuda.yaml)):
  - CUDA 12 archs are `60;61;70;75;80;86;89;90-real` plus `90-virtual`. CUDA 13 archs start at 75; the workflow comment says "CUDA 13 dropped offline compilation support for pre-Turing targets".
  - Build flags are `-DGGML_CUDA_FORCE_MMQ=ON -DGGML_AVX2=off -DGGML_FMA=off -DGGML_F16C=off -DGGML_OPENMP=OFF`. The CPU path in the CUDA wheel is therefore built for the lowest common denominator, which matters for partial offload and CPU fallback.
- **Runtime libs are not bundled** (from `readelf` on the cu124 0.3.36 wheel, 1,776,573,061 bytes):
  - `libggml-cuda.so` has `NEEDED libcudart.so.12, libcublas.so.12, libcuda.so.1` and `RUNPATH $ORIGIN:/home/runner/miniconda3/envs/llamacpp/lib`, a leftover CI path.
  - `libggml.so` hard-`NEEDED`s `libggml-cuda.so`, so this is not a dynamic-backend build.
  - Consequence: `import llama_cpp` raises `RuntimeError: Failed to load shared library ... libcudart.so.12: cannot open shared object file` unless the libs are preloaded or on the loader path. Observed here.
  - The loader is a plain `ctypes.CDLL` of `llama_cpp/lib/libllama.so`, overridable with `LLAMA_CPP_LIB_PATH` ([_ctypes_extensions.py](https://github.com/abetlen/llama-cpp-python/blob/main/llama_cpp/_ctypes_extensions.py), [llama_cpp.py](https://github.com/abetlen/llama-cpp-python/blob/main/llama_cpp/llama_cpp.py)).
- **Building from source** (`CMAKE_ARGS="-DGGML_CUDA=on"`, from the README):
  - It needs the CUDA toolkit with nvcc ([llama.cpp build.md → CUDA](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda)).
  - The CUDA 13.4 Linux guide lists **Fedora 44 (GCC 16.0.1) as supported**, with host GCC "6.x – 16.x" ([CUDA install guide 13.4](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html)). RPM Fusion's CUDA how-to says the toolkit comes from NVIDIA's `fedora44` repo with the Fedora-provided gcc16 ([rpmfusion.org/Howto/CUDA](https://rpmfusion.org/Howto/CUDA), edited 2026-09-25).
  - llama.cpp also documents a toolbox-container route for Fedora ([CUDA-FEDORA.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/CUDA-FEDORA.md)).
  - Building from source contradicts "user installs nothing else", so it is a dev or advanced option only.
- **Maintenance:**
  - The repo is not archived, was last pushed 2026-10-01 and has about 700 open issues (GitHub API).
  - Releases track upstream roughly monthly: 0.3.35 (2026-08-17) and 0.3.36 (2026-10-01).
  - 0.3.36 vendors llama.cpp `0c1e57098` (committed 2026-10-01). Upstream's latest release is `v0.7.0` (2026-10-15) ([commits](https://github.com/abetlen/llama-cpp-python/commits/main), [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)).
  - Expect a lag of a few weeks for new model architectures.

## 3. Coexistence in one process

- **Yes, with one CUDA 12 set.** CTranslate2 needs `libcublas.so.12` (built against 12.8). The llama cu124 wheel needs `libcudart.so.12` and `libcublas.so.12` (built against 12.4). A single `nvidia-cublas-cu12` 12.9.2.10 plus `nvidia-cuda-runtime-cu12` 12.9.79 satisfied both.
- **Verified on this machine:** whisper-tiny on CUDA float16 and Qwen2.5-0.5B Q4_K_M with `n_gpu_layers=-1`, in the same process, both produced output (see Local machine).
- **Constraint: keep cuBLAS ≥ the highest build minor (12.8).** Same-SONAME minor versions are expected to be backward compatible. I verified this only empirically with 12.9 and found no NVIDIA statement specific to cuBLAS minor versions.
- **Avoid mixing majors.** Using llama `cu130`/`cu132` would require `libcudart.so.13` and `libcublas.so.13` *in addition to* cu12 cuBLAS for CTranslate2. The SONAMEs differ, so loading both should be possible, but it would add about 420 MB and is not tested.

## 4. uv / pyproject

Validated with `uv lock` (uv 0.13.5) in a scratch project. It resolves `llama-cpp-python` 0.3.36 from the `cpu` index for `--extra cpu` and from the `cu124` index for `--extra cuda`:

```toml
[project.optional-dependencies]
cpu  = ["llama-cpp-python==0.3.36"]
cuda = [
    "llama-cpp-python==0.3.36",
    "nvidia-cublas-cu12>=12.8,<13; sys_platform == 'linux'",
    "nvidia-cuda-runtime-cu12>=12.4,<13; sys_platform == 'linux'",
]

[tool.uv]
conflicts = [[{ extra = "cpu" }, { extra = "cuda" }]]

[tool.uv.sources]
llama-cpp-python = [
    { index = "llama-cpp-cpu",   extra = "cpu" },
    { index = "llama-cpp-cu124", extra = "cuda" },
]

[[tool.uv.index]]
name = "llama-cpp-cpu"
url = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
explicit = true

[[tool.uv.index]]
name = "llama-cpp-cu124"
url = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
explicit = true
```

- **Where the pattern comes from:** it mirrors uv's documented PyTorch recipe: `explicit = true` indexes, `extra`-scoped sources and `conflicts` ([uv PyTorch guide](https://docs.astral.sh/uv/guides/integration/pytorch/), [uv indexes](https://docs.astral.sh/uv/concepts/indexes/)). `explicit = true` means the index is "only usable via `tool.uv.sources`". uv's default `first-index` strategy exists to prevent dependency confusion.
- **No extra selected means no llama-cpp-python.** Do not put it in base `dependencies`: without an extra, uv would fall back to the PyPI sdist and compile.
- **Possible addition:** `nvidia-ml-py` can go in base deps. It is pure Python, and on non-NVIDIA machines it simply raises at `nvmlInit()`.
- **CPU fallback for non-NVIDIA users:** install `--extra cpu`. ctranslate2 from PyPI runs on CPU unchanged (MKL/oneDNN built in).
- **CI:** GitHub runners have no NVIDIA driver, so CI must use `uv sync --extra cpu` (never `cuda`: its llama wheel fails to import without `libcuda.so.1`). Tests that need a GPU should be marked and skipped when NVML init fails.
- **Caveats:**
  - "Sources are only respected by uv" ([uv dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/)). Anyone installing orteki from PyPI (pip, or probably `uv tool install orteki[cuda]`) gets neither the index pins nor the conflicts. Not verified for `uv tool install`.
  - The abetlen index serves static HTML without separate metadata files. `uv lock` took about 1.5 min, probably fetching wheels to read metadata (not confirmed).

## 5. Runtime detection for fit

| Check | What it tells you | Cost |
|---|---|---|
| `pynvml.nvmlInit()` → `nvmlDeviceGetMemoryInfo(h)`, `nvmlDeviceGetCudaComputeCapability(h)`, `nvmlSystemGetCudaDriverVersion_v2()` | driver present, free/total VRAM, cc, max CUDA the driver supports (13030 = 13.3 here) | `nvidia-ml-py`, pure Python, dlopens the driver's `libnvidia-ml.so.1` ([PyPI](https://pypi.org/project/nvidia-ml-py/)) |
| `ctranslate2.get_cuda_device_count()` | CUDA devices visible to CTranslate2 (0 with `CUDA_VISIBLE_DEVICES=""`) | already a dependency; does **not** prove cuBLAS loads |
| `llama_cpp.llama_supports_gpu_offload()` | GPU backend compiled in **and** a device found (returned `False` with `CUDA_VISIBLE_DEVICES=""` on the CUDA wheel) | requires `import llama_cpp` to succeed first |

- **Suggested order:**
  1. NVML. If it fails, the fit is CPU-only.
  2. Preload the cu12 libs. If they are missing, the fit is CPU-only.
  3. `import llama_cpp`, catching `RuntimeError`/`OSError`.
  4. Backend checks.
  5. Judge fit from NVML free VRAM minus the model size estimates of everything to be loaded together.
- **Free VRAM is shared.** The desktop already uses about 1.5 GB here (kwin, plasmashell, browser), so read it live, not just at startup.
- **A finer-grained memory query exists only in C:** llama.cpp has `ggml_backend_dev_memory(dev, &free, &total)` in [ggml-backend.h](https://github.com/ggml-org/llama.cpp/blob/master/ggml/include/ggml-backend.h), but llama-cpp-python 0.3.36 does not bind it.
- **If a GPU path fails:**
  - **CTranslate2:** reload the model with `device="cpu"`.
  - **llama.cpp, CUDA wheel installed:** use `n_gpu_layers=0`. The CUDA wheel still runs on CPU when no device is present (verified), but slower because AVX2 is off.

## 6. Driver and forward compatibility; Fedora notes

- **A CUDA 13.x driver runs CUDA 12.x userspace.** NVIDIA: "Backwards compatibility ensures that a newer NVIDIA driver can be used with an older CUDA Toolkit" ([why CUDA compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/why-cuda-compatibility.html)). The minor-version table lists CUDA 12.x as needing driver ≥ 525, and CUDA 13.x as needing ≥ 580 ([minor version compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html), page updated 2026-09-09). Confirmed in practice on driver 610.57.04.
- **Choosing cu12 over cu13 widens support** to older drivers (≥ 525) and older GPUs (cc 6.0+).
- **Fedora specifics:**
  - With RPM Fusion's `akmod-nvidia`, `libcuda.so.1`, `libnvidia-ml.so.1` and `libnvidia-ptxjitcompiler.so.1` come from `xorg-x11-drv-nvidia-cuda-libs` (RPM Fusion), installed here.
  - The CUDA *toolkit* is not provided by RPM Fusion; it comes from NVIDIA's repo ([rpmfusion.org/Howto/CUDA](https://rpmfusion.org/Howto/CUDA)).
  - The pip-wheel approach needs no toolkit.
  - If a user has only `akmod-nvidia` without the `-cuda` subpackage, `libcuda.so.1` will be missing. Detect this and explain it, since NVML would then also be missing. That this subpackage split applies to all setups is unverified.
  - Kernel updates rebuild the module via akmod. A just-updated kernel can briefly have no module, so NVML fails and the fit is CPU-only.
- **Wayland is irrelevant:** CUDA compute does not touch the display server.

## 7. AMD / Intel (what we are leaving out)

- **CTranslate2:**
  - ROCm/HIP support was added in v4.7.0 (2026-02-03). ROCm wheels are attached to GitHub releases (`rocm-python-wheels-Linux.zip` on v4.8.4), not PyPI ([CHANGELOG](https://github.com/OpenNMT/CTranslate2/blob/master/CHANGELOG.md), [README](https://github.com/OpenNMT/CTranslate2#readme), [releases](https://github.com/OpenNMT/CTranslate2/releases)).
  - There is no Vulkan or Intel GPU backend, so Whisper runs on CPU on Intel/AMD-without-ROCm.
- **llama-cpp-python:** prebuilt `rocm72` (Linux) and `vulkan` wheel indexes exist ([README](https://github.com/abetlen/llama-cpp-python/blob/main/README.md)). Vulkan would cover AMD and Intel iGPUs/dGPUs for the LLM. Not evaluated.

## Local machine (observed 2026-10-26)

- **Hardware and driver:** RTX 2070, 8192 MiB; about 6.4 GiB free at idle with the Plasma session running. Driver 610.57.04; `nvidia-smi` reports "CUDA UMD Version: 13.3"; NVML `nvmlSystemGetCudaDriverVersion_v2` = 13030; compute capability (7, 5).
- **Packages:** `akmod-nvidia-610.57.04`, `xorg-x11-drv-nvidia-cuda(-libs)-610.57.04` from RPM Fusion (`rpmfusion-nonfree-nvidia-driver` repo).
- **CUDA libs:** `ldconfig` shows only `libcuda.so.1` and `libnvidia-ml.so.1`. There is **no** system cuBLAS, cuDNN, cudart, nvcc or `/usr/local/cuda`.
- **Toolchain:** gcc 16.1.1. System `python3` is 3.14.7. `uv` 0.13.5 is in `~/.local/bin`.
- **Experiment** (scratch venv on Python 3.14; ctranslate2 4.8.4, faster-whisper 1.2.1, llama-cpp-python 0.3.36 cu124 wheel, nvidia-cublas-cu12 12.9.2.10, nvidia-cuda-runtime-cu12 12.9.79, no cuDNN):

  | Condition | Result |
  |---|---|
  | No preload | `WhisperModel(device="cuda")` → `Library libcublas.so.12 is not found or cannot be loaded`; `import llama_cpp` → `libcudart.so.12: cannot open shared object file` |
  | Preload (`ctypes.CDLL(..., RTLD_GLOBAL)` of cudart, cublasLt, cublas from `nvidia.*` package dirs) | whisper-tiny float16 transcription OK (0.37 s incl. load); `llama_supports_gpu_offload()` True; Qwen2.5-0.5B Q4_K_M fully offloaded generates text; NVML free VRAM fell 6438 → 5506 MiB with both loaded |
  | Preload + `CUDA_VISIBLE_DEVICES=""` | `get_cuda_device_count()` 0, `llama_supports_gpu_offload()` False, llama still runs on CPU |

- **Re-run on Python 3.12** with [`cuda-check.py`](cuda-check.py) (`uv run docs/research/cuda-check.py --audio speech.wav --compare-cpu`, same package versions, `av` 18), on 6.1 s of espeak-ng speech:

  | | GPU | CPU (same wheels) |
  |---|---|---|
  | Whisper `small` transcribe | 0.7 s (float16), load 0.8 s | 3.5 s (int8) |
  | Qwen2.5-1.5B-Instruct Q4_K_M | 44 tok/s, load 0.5 s | 19 tok/s |
  | VRAM used, both loaded | 2472 → 4197 MiB (+1.7 GB) | – |

  The CPU llama figure is the CUDA wheel with `n_gpu_layers=0` (AVX2 off), not the `cpu` wheel.

## Open questions

1. **Distribution.** How do end users get the `cuda` extra with the right indexes, given that `[tool.uv.sources]` is uv-only? Options:
   - A documented `uv tool install` command with `--index` flags.
   - An installer script.
   - orteki downloading the llama wheel itself.

   The ADR's goal that users "install nothing else" implies orteki owns this.
2. **Download size.** The llama cu124 wheel is about 1.78 GB, of which about 1.1 GB is duplicate `.so` copies (`lib/`, `llama_cpp/lib/`, `llama_cpp_python.libs/`). Plus cuBLAS is about 554 MB. Is that acceptable, or should orteki build its own slimmer sm_75+ wheel?
3. **CPU speed in the CUDA wheel.** Its CPU path has AVX2 off. How much slower is partial offload or CPU fallback than in the `cpu` wheel? Not measured.
4. **cuBLAS compatibility.** Is there an NVIDIA statement guaranteeing cuBLAS 12.x minor backward compatibility? I verified it only empirically.
5. **CUDA 13 in CTranslate2.** Will it move to CUDA 13 (`libcublas.so.13`)? If so, re-evaluate switching llama to `cu130`. No announcement found.
6. **Missing driver library.** Behaviour when `libcuda.so.1` is absent (no NVIDIA driver) but the `cuda` extra is installed: expect an import failure of `llama_cpp`. This follows from the `NEEDED` entries; not tested.
7. ~~**Python 3.12.**~~ Resolved: `cuda-check.py` re-ran the setup on Python 3.12 with the same result (see Local machine).

## Sources

- CTranslate2: [CHANGELOG](https://github.com/OpenNMT/CTranslate2/blob/master/CHANGELOG.md), [Linux wheel build script](https://github.com/OpenNMT/CTranslate2/blob/master/python/tools/prepare_build_environment_linux.sh), [cublas_stub.cc](https://github.com/OpenNMT/CTranslate2/blob/master/src/cuda/cublas_stub.cc), [CMakeLists.txt](https://github.com/OpenNMT/CTranslate2/blob/master/CMakeLists.txt), [python/ctranslate2/__init__.py](https://github.com/OpenNMT/CTranslate2/blob/master/python/ctranslate2/__init__.py), [installation.md](https://github.com/OpenNMT/CTranslate2/blob/master/docs/installation.md), [releases](https://github.com/OpenNMT/CTranslate2/releases), [PyPI ctranslate2 4.8.4](https://pypi.org/project/ctranslate2/4.8.4/)
- faster-whisper: [README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md), [PyPI 1.2.1](https://pypi.org/project/faster-whisper/1.2.1/)
- llama-cpp-python: [README](https://github.com/abetlen/llama-cpp-python/blob/main/README.md), [build-wheels-cuda.yaml](https://github.com/abetlen/llama-cpp-python/blob/main/.github/workflows/build-wheels-cuda.yaml), [_ctypes_extensions.py](https://github.com/abetlen/llama-cpp-python/blob/main/llama_cpp/_ctypes_extensions.py), [llama_cpp.py](https://github.com/abetlen/llama-cpp-python/blob/main/llama_cpp/llama_cpp.py), [wheel index cu124](https://abetlen.github.io/llama-cpp-python/whl/cu124/llama-cpp-python/), [PyPI 0.3.36](https://pypi.org/project/llama-cpp-python/0.3.36/)
- llama.cpp: [build.md (CUDA)](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda), [CUDA-FEDORA.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/CUDA-FEDORA.md), [llama.h](https://github.com/ggml-org/llama.cpp/blob/master/include/llama.h), [ggml-backend.h](https://github.com/ggml-org/llama.cpp/blob/master/ggml/include/ggml-backend.h), [releases](https://github.com/ggml-org/llama.cpp/releases)
- NVIDIA: [CUDA compatibility: why](https://docs.nvidia.com/deploy/cuda-compatibility/why-cuda-compatibility.html), [minor version compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html), [CUDA 13.4 Linux install guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html), PyPI [nvidia-cublas-cu12](https://pypi.org/project/nvidia-cublas-cu12/), [nvidia-cuda-runtime-cu12](https://pypi.org/project/nvidia-cuda-runtime-cu12/), [nvidia-ml-py](https://pypi.org/project/nvidia-ml-py/)
- uv: [PyTorch integration guide](https://docs.astral.sh/uv/guides/integration/pytorch/), [indexes](https://docs.astral.sh/uv/concepts/indexes/), [project dependencies / sources](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- RPM Fusion: [Howto/CUDA](https://rpmfusion.org/Howto/CUDA)
- Local inspection: `nvidia-smi`, `ldconfig -p`, `rpm -qa`/`rpm -ql`, `readelf -d` on the ctranslate2 4.8.4 cp312 and llama-cpp-python 0.3.36 cu124 wheels, and the scratch-venv experiment above.
