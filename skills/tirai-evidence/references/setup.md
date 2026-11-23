# Setup

1. Python 3.10+ and ffmpeg (`apt install ffmpeg`, `brew install ffmpeg`, `winget install ffmpeg`).
2. TIRAI: `pipx install "tirai[postgres] @ git+https://github.com/2tsoftwareapp/TIRAI"`
   (or `pip install` the same spec into a venv; use `[mysql]` for MySQL checks).
3. BrowserSkill CLI:
   - macOS/Linux: `curl -fsSL https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.sh | sh`
   - Windows: `irm https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.ps1 | iex`
   - add `~/.local/bin` to PATH; check `bsk --version`.
4. Browser extension (the user installs it): Chrome Web Store or Edge Add-ons "BrowserSkill", then enable the connection.
5. DBX web for database tabs (optional): `docker run -d -p 127.0.0.1:4224:4224 -e DBX_PASSWORD=... -e DBX_DISABLE_PASSWORD_VIEWER=true t8y2/dbx`.
   In DBX create a connection with a **read-only** database user.
6. `tirai doctor` must report `ready`.
