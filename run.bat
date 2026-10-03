@echo off
REM ---------------------------------------------------------------------------
REM Launch the Smart Resume Parser.
REM
REM Uses "python -m streamlit" rather than the bare "streamlit" command, so it
REM works regardless of whether Python's Scripts directory is on PATH. The
REM Microsoft Store build of Python never adds it, which is why typing
REM "streamlit" alone reports "not recognized".
REM
REM Double-click this file, or run "run" from a terminal in this folder.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo.
    echo [!] Streamlit is not installed for this Python interpreter.
    echo     Install the dependencies first:
    echo.
    echo         python -m pip install -r requirements.txt
    echo         python -m spacy download en_core_web_sm
    echo.
    pause
    exit /b 1
)

echo Starting Smart Resume Parser...
echo Press Ctrl+C in this window to stop the server.
echo.
python -m streamlit run app.py

REM Keep the window open if Streamlit exits with an error on a double-click.
if errorlevel 1 pause
