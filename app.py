import os
import logging
import argparse
from datetime import datetime
from flask import Flask, redirect, url_for, flash, session, render_template, request, jsonify
from logging.handlers import RotatingFileHandler
from utils.config import CONFIG

# Get the application root directory for absolute paths
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Parse command line arguments for logging configuration
parser = argparse.ArgumentParser(
    description='Missions Helper Application',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog='''
Logging Level Options:
  CRITICAL  Critical errors only
  ERROR     Error messages and above
  WARNING   Warning messages and above  
  INFO      Information messages and above (default)
  DEBUG     All messages including debug

Examples:
  python app.py --log-level DEBUG
  python app.py --log-level INFO --file-log-level ERROR --enable-logging
  python app.py --console-log-level WARNING --file-log-level DEBUG --enable-logging
'''
)

# Logging arguments
parser.add_argument('--enable-logging', '--enable-file-logging', 
                   action='store_true', dest='enable_logging',
                   help='Enable logging to file (backward compatibility)')

parser.add_argument('--log-level', '--console-log-level',
                   choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'],
                   default='INFO', dest='console_log_level',
                   help='Set console logging level (default: INFO)')

parser.add_argument('--file-log-level',
                   choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'],
                   default='INFO', dest='file_log_level',
                   help='Set file logging level (default: INFO, requires --enable-logging)')

parser.add_argument('--log-file',
                   default='logs/missions.log', dest='log_file',
                   help='Path to log file (default: logs/missions.log)')

parser.add_argument('--log-max-size',
                   type=int, default=102400, dest='log_max_size',
                   help='Maximum log file size in bytes (default: 102400)')

parser.add_argument('--log-backup-count',
                   type=int, default=10, dest='log_backup_count',
                   help='Number of backup log files to keep (default: 10)')

args, unknown_args = parser.parse_known_args()

# Convert string log levels to logging constants
def get_log_level(level_str):
    return getattr(logging, level_str.upper())

console_log_level = get_log_level(args.console_log_level)
file_log_level = get_log_level(args.file_log_level)

# Determine if file logging should be enabled via command line or env var
enable_file_logging = args.enable_logging or bool(os.getenv('ENABLE_FILE_LOGGING'))

# Set root logger level to the minimum of console and file levels
root_level = console_log_level
if enable_file_logging:
    root_level = min(console_log_level, file_log_level)

# Configure console logging
logging.basicConfig(
    level=root_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True  # Override any existing configuration
)

# If we need different console level, set it on the console handler
if enable_file_logging and console_log_level != root_level:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_log_level)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().handlers = []  # Clear default handlers
    logging.getLogger().addHandler(console_handler)
    logging.getLogger().setLevel(root_level)

logger = logging.getLogger(__name__)

# Tone down Werkzeug dev server logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Log the current logging configuration
logger.info(f"Console logging level set to: {args.console_log_level}")
if enable_file_logging:
    logger.info(f"File logging enabled with level: {args.file_log_level}")
    logger.info(f"Log file: {args.log_file}")
else:
    logger.info("File logging disabled (use --enable-logging to enable)")

# Import routes
from routes.mission_routes import mission_bp

# Create Flask app
app = Flask(__name__)

# Set secret key for sessions and flash messages
app.secret_key = os.urandom(24)

# Ensure templates auto-reload even when debug is off
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
# Disable static file caching so CSS/JS updates appear immediately
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configure file logging only when enabled
if enable_file_logging:
    # Ensure log directory exists
    log_dir = os.path.dirname(args.log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        logger.info(f"Created log directory: {log_dir}")
    
    # Create file handler with rotation
    file_handler = RotatingFileHandler(
        args.log_file, 
        maxBytes=args.log_max_size, 
        backupCount=args.log_backup_count
    )
    file_handler.setFormatter(
        logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        )
    )
    file_handler.setLevel(file_log_level)
    
    # Add file handler to both app logger and root logger
    app.logger.addHandler(file_handler)
    logging.getLogger().addHandler(file_handler)
    
    # Set levels
    app.logger.setLevel(min(console_log_level, file_log_level))
    
    logger.info('Missions Helper startup with file logging enabled')

# Add now() function to Jinja2 template environment
@app.context_processor
def utility_processor():
    return {'now': datetime.now}

# Load configuration from utils.config
app.config['WORKING_FOLDER'] = CONFIG.get('working_folder', 'data')
app.config['TOKEN_FILE'] = CONFIG.get('token_file', '/tmp/synacktoken')
app.config['PLATFORM'] = CONFIG.get('platform', 'https://platform.synack.com')
app.config['UPLOAD_FOLDER'] = CONFIG.get(
    'upload_folder',
    os.path.join(APP_ROOT, 'static', 'uploads')
)
app.config['MAX_CONTENT_LENGTH'] = int(CONFIG.get('max_upload_size', 16 * 1024 * 1024))
app.config['APP_ROOT'] = APP_ROOT  # Add APP_ROOT to config for other modules
app.config['USER_TEMPLATES_DIR'] = CONFIG.get('user_templates_dir')

# Ensure the working folder exists
working_folder = app.config['WORKING_FOLDER']
if not os.path.exists(working_folder):
    logger.info(f"Creating working folder: {working_folder}")
    os.makedirs(working_folder, exist_ok=True)

# Ensure template directory structures exist (both app-provided and user-managed)
def _ensure_template_scaffold(base_dir):
    if not base_dir:
        return
    subdirs = [
        os.path.join(base_dir, 'default'),
        os.path.join(base_dir, 'web'),
        os.path.join(base_dir, 'host'),
        os.path.join(base_dir, 'ai_prompts', 'global'),
        os.path.join(base_dir, 'tools'),
    ]
    for d in subdirs:
        if not os.path.exists(d):
            logger.info(f"Creating template directory: {d}")
            os.makedirs(d, exist_ok=True)

# App-bundled templates dir (read-only by convention)
_ensure_template_scaffold(os.path.join(APP_ROOT, 'text_templates'))
# User templates dir (preferred for load, used for all saves)
_ensure_template_scaffold(app.config.get('USER_TEMPLATES_DIR'))

# Initialize missions data on startup (load from tasks.json)
from utils.api import get_all_missions
logger.info("Preloading missions data from tasks.json")
missions, _ = get_all_missions()  # Initial load of missions from tasks.json

# Register blueprints - set the url_prefix to empty string since we want mission routes at root
app.register_blueprint(mission_bp, url_prefix='')

# Test CSS route
@app.route('/test_css')
def test_css():
    """Test route to verify CSS loading"""
    response = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CSS Test</title>
        <link rel="stylesheet" href="/static/css/missionform.css?v={}">
    </head>
    <body>
        <h1>CSS Test Page</h1>
        <p>This page tests if missionform.css is loading correctly.</p>
        <div class="task-section">
            <h2>This should be styled</h2>
            <p>Check if this has the correct styling.</p>
        </div>
        <div class="form-actions">
            <button class="action-button">Test Button</button>
        </div>
    </body>
    </html>
    """.format(datetime.now().timestamp())
    
    # Set headers to prevent caching
    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }
    
    return response, 200, headers

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@app.route('/')
def index():
    # If user templates dir is not configured, guide user to config setup
    utd = app.config.get('USER_TEMPLATES_DIR')
    if not utd or not str(utd).strip():
        from flask import redirect, url_for
        return redirect(url_for('mission.render_config_page'))
    return render_template('index.html')

if __name__ == '__main__':
    # Production-friendly defaults: disable Flask debug, disable reloader, and reduce Werkzeug noise
    app.run(debug=False, use_reloader=False)
