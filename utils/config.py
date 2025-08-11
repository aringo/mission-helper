import os
import json
import logging

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_CONFIG = {
    "platform": "https://platform.synack.com",
    "working_folder": "data",
    # Directory where user-managed text templates (defaults, web/host, ai_prompts, tools) live
    # Can be absolute; if relative, it's resolved under ROOT_DIR at load time
    "user_templates_dir": "text_templates_user",
    "token_file": "/tmp/synacktoken",
    "max_upload_size": 16 * 1024 * 1024,
    "ai_key": "",
    "ai_model": "",
}


def load_config():
    """Load configuration from file and environment variables."""
    config = DEFAULT_CONFIG.copy()

    config_path = os.path.join(ROOT_DIR, 'config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                file_config = json.load(f)
            if isinstance(file_config, dict):
                config.update({k: v for k, v in file_config.items() if v is not None})
        except Exception as e:
            logger.error(f"Error loading config.json: {e}")

    # Environment overrides prefixed with MH_
    for key in list(config.keys()):
        env_key = f"MH_{key.upper()}"
        if env_key in os.environ:
            config[key] = os.environ[env_key]

    # Convert relative working folder to absolute path under ROOT_DIR
    working_folder = config.get('working_folder', 'data')
    if not os.path.isabs(working_folder):
        config['working_folder'] = os.path.join(ROOT_DIR, working_folder)

    # Convert relative user templates dir to absolute path under ROOT_DIR
    utd = config.get('user_templates_dir', 'text_templates_user')
    if utd and not os.path.isabs(utd):
        config['user_templates_dir'] = os.path.join(ROOT_DIR, utd)

    return config

# Load once at import
CONFIG = load_config()
