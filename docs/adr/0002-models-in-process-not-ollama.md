# Models run in-process, not through Ollama

Both the speech model (faster-whisper) and language models (llama-cpp-python, GGUF) are loaded inside the orteki process instead of talking to a local model server such as Ollama or llama.cpp's server. This lets orteki control VRAM directly (preload when recording starts, unload after an idle timeout, fit decisions across models loaded together) and means the user installs nothing else. The cost is that orteki owns model downloading, loading and GPU setup itself.
