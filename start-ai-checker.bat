@echo off
REM Optional: starts the local "AI double-check" vision model on 127.0.0.1:8090 (Windows). Same settings as start-ai-checker.command.
REM Needs a models folder next to this file (or set GAC_MODELS) with llama-server.exe, Qwen3VL-4B-Instruct-Q4_K_M.gguf and mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf.
cd /d "%~dp0"
set M=%GAC_MODELS%
if "%M%"=="" set M=%~dp0models
if not exist "%M%\Qwen3VL-4B-Instruct-Q4_K_M.gguf" (echo Model not found in %M% - AI double-check stays off ^(scanning still works^). & pause & exit /b 0)
cd /d "%M%"
set SRV=llama-server.exe
for /d %%D in (llama-*) do if exist "%%D\llama-server.exe" set SRV=%%D\llama-server.exe
if not exist "%SRV%" (echo No llama-server.exe found in %M% - AI double-check stays off ^(scanning still works^). & pause & exit /b 0)
if "%GAC_AI_THREADS%"=="" set GAC_AI_THREADS=8
REM -np 1 one slot; -c 2048; --cache-ram 0 stops llama.cpp keeping up to 8 GB of prompt cache in RAM; --no-slots hides /slots
"%SRV%" -m Qwen3VL-4B-Instruct-Q4_K_M.gguf --mmproj mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf -c 2048 -np 1 --cache-ram 0 --no-slots -t %GAC_AI_THREADS% --host 127.0.0.1 --port 8090 --image-max-tokens 768
pause
