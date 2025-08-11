## Missions Helper


### Overview

A lightweight Flask web app to manage Synack missions with structured text templates, a curated toolbin, and AI prompt presets. It supports drafts, default templates, sectioned content, and a user‑overrides directory so you can keep your changes outside the repo.

### Features

- **Mission Management**: View and manage missions fetched from the Synack API with caching to `data/tasks.json`.
- **Template Handling**: Sectioned markdown templates with `[Introduction]`, `[Testing]`, `[Documentation]`, `[Scripts]`, `[conclusion-pass]`, `[conclusion-fail]`.
- **Dynamic Conclusions**: Select a conclusion type and dynamically load only the relevant section.
  - **Non‑SV2M**: Pass / Fail / Not Testable → `structuredResponse` mapped to `no` / `yes` / omitted.
  - **SV2M**: Vulnerable / Not Exploitable / Out of Threshold → exact value passed as `structuredResponse`.
- **Script Integration**: Link scripts by path to show them as plain text in the browser.
- **Drafts and Templates**: Save drafts locally; save templates (non‑SV2M) with overwrite prompts.
- **Toolbin and AI Prompts**: Centralized lists editable via Settings → Config.
- **Logging**: Console and rotating file logging with CLI flags or env var.

### Directory Structure

```
For_Rel/
├── app.py
├── config.json
├── data/
├── routes/
│   └── mission_routes.py
├── static/
│   ├── css/
│   ├── js/
│   ├── scripts/
│   │   └── web/
│   │       └── cookieaudit.py # just a script I forgot to remove :)
│   └── styles-*.css
├── templates/
│   ├── base.html
│   ├── index.html
│   └── mission_form.html
├── text_templates/
│   ├── default/
│   ├── host/
│   ├── tools/
│   │   └── tools.txt
│   └── web/
├── utils/
│   ├── ai_generator.py
│   ├── api.py
│   ├── config.py
│   ├── mission_helpers.py
│   ├── template_loader.py
│   ├── template_utils.py
│   └── tool_utils.py
└── README.md
```

## Quickstart

### 1) Prerequisites

- Python 3.9+
- macOS/Linux recommended, at least until someone else uses it.
- Being able to get a Synack API auth token into a file
- Google AI key if you don't like to type

### 2) Install

You really, really , really dont need a venv it's installing flask for the most part. If you want one though. 
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Configure

Edit `config.json` (defaults shown):

```json
{
  "platform": "https://platform.synack.com",
  "working_folder": "data",
  "token_file": "/tmp/synacktoken",
  "user_templates_dir": "/directory/for/your/templates",
  "ai_key": "",
  "ai_model": ""
}
```
- **platform**: Base URL for Synack. All API URLs are derived from this.
- **working_folder**: Where cached missions (`tasks.json`) are stored. Relative paths are resolved under the app root.
- **token_file**: File path where your Synack Bearer token is stored. The app reads this value on each Synack API call.
- **user_templates_dir**: Your personal templates folder. When set, it is used preferentially for reads and always for writes; the app scaffolds `default/`, `web/`, `host/`, `ai_prompts/global/`, and `tools/` under it at startup.
- **ai_key / ai_model**: Optional Google AI key and model for AI features (see below).

You can supposedly also override any field via environment variables with `MH_` prefix, for example:

```bash
export MH_TOKEN_FILE=/path/to/token
export MH_AI_KEY=your_google_ai_key
export MH_AI_MODEL=gemini-1.5-flash
```

### 4) Copy Templates

So the user_templates_dir is where your templates will be. It's important to set this so if you do a git pull you get any changes to the app without having to deal with template conflict.


### 5) Run

```bash
python3 app.py
```

- Visit `http://127.0.0.1:5000/`.
- File logging can be enabled with either the CLI flag or environment variable:

```bash
ENABLE_FILE_LOGGING=1 python3 app.py
# or
python3 app.py --enable-logging --log-file logs/missions.log --log-level INFO --file-log-level DEBUG
```

## How the Application Operates

### Startup and Configuration

- Loads configuration from `config.json`, then applies `MH_*` environment variable overrides.
- Converts relative paths (`working_folder`, `user_templates_dir`) to absolute paths under the app root.
- Ensures the following directories exist in both the app’s bundled templates (`text_templates/`) and your `user_templates_dir` (if set):
  - `default/`, `web/`, `host/`, `ai_prompts/global/`, `tools/`.
- Preloads missions from the cached file `data/tasks.json` on first access, avoiding an API call.

### Mission Data Flow and Caching

- On first load, missions are read from `data/tasks.json` if present.
- Subsequent requests use an in‑memory cache.
- A forced refresh or a manual refresh triggers Synack API calls using the Bearer token read from `token_file`.
- Successful API responses are written back to `data/tasks.json` for offline use.

### UI Flow

- `GET /` shows the mission list. If `user_templates_dir` is not configured, you are redirected to the config page.
- Selecting a mission opens the form with templated sections.
- The conclusion dropdown controls which conclusion section is loaded and saved.
- Associated scripts are displayed as plain text from `static/scripts/...` paths you reference in the template `[Scripts]` section.

### Templates, Overrides, and Saves

- Read precedence: `user_templates_dir` (if configured) takes priority over the built‑in `text_templates/` shipped with the app.
- Saves always write to `user_templates_dir` when set.
- Non‑SV2M missions can be saved as templates (with overwrite prompt). SV2M is draft‑only.

### Toolbin and AI Prompts

- Toolbin items live in `tools/tools.txt` under your `user_templates_dir` (preferred) or the app’s `text_templates/tools/tools.txt`.
- AI prompts live under `ai_prompts/` (global or section‑specific). Settings → Config provides search, preview, edit, rename, delete, and “Open Folder”.

### Syncing to Platform

- The app sends `introduction`, `testing_methodology`, `conclusion`, and optional `structuredResponse` to the Synack API endpoint for the mission.
- Success is any of HTTP 200/201/204; errors include status information and the payload that was attempted.


## Google AI Setup (Optional but Recommended)

The app integrates with Google’s Generative Language API for content generation and text rewrites.

### Get an API Key

1. Go to Google AI Studio and create an API key: [Get a Google AI API key](https://aistudio.google.com/app/apikey)
2. If prompted, enable the “Generative Language API” for your project.
3. Copy the API key.

###  Model

I tested with and use gemini flash, the context window is huge and should not run out of free to you requests:
- `gemini-2.5-flash`


Set these in `config.json` or via environment variables:

```json
{
  "ai_key": "YOUR_KEY",
  "ai_model": "gemini-2.5-flash"
}
```

or

```bash
export MH_AI_KEY=YOUR_KEY
export MH_AI_MODEL=gemini-2.5-flash
```

## AI Actual Usage

Its pretty easy to use, you highlight some text and select one of your prompts. The place highlighted can provide the input to the prompt and the highlighted section is overwritten with the response. As an example you can write SQL injection and then highlight it and select Expand to Vuln - your SQL Injection will be overwritten with a paragraph about SQL injection and also have a reference. 

* You may see a prompt while using the AI feature asking you to review. There is a script that checks for domains and IP addresses to assist in preventing leaking customer information. If you select replace it changes the domains to example.com etc or if it's something that you know is one of your references like github you can select to have it send as is. 

## Toolbox 

The Toolbox is a list of tools that you can quickly add to the tools section of the report by clicking the Hammer. It has a search feature and you can edit the flat file or use the modifier in the config. 


## Troubleshooting

- **No missions appear and API calls fail**: Ensure your token file exists and contains a valid Bearer token. Update `token_file` in `config.json` or set `MH_TOKEN_FILE`. YOU SHOULD GET A BIG RED FAIL FLASH
- **AI errors such as "AI configuration missing"**: Set both `ai_key` and `ai_model` in `config.json` or `MH_AI_KEY` and `MH_AI_MODEL` environment variables.
- **Templates not found**: Verify `user_templates_dir` exists and contains the expected `default/`, `web/`, `host/`, `ai_prompts/global/`, and `tools/` folders.
- **Changes not reflected**: Static caching is disabled, but restart the app if you changed core Python or template loader logic.
- **Logging to file isn’t working**: Use `--enable-logging` or `ENABLE_FILE_LOGGING=1`. Check that the configured log directory exists and is writable.

## Notes

- The app avoids noisy dev server logs and disables Flask debug by default for a production‑friendlier experience.
- All file paths in `config.json` can be overridden at runtime using `MH_*` environment variables.
* The scripts folder is currently in the git ignore, I might give it a path to load like templates - but you can create a symlink etc



