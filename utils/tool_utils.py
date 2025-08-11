import os
import re
import logging

logger = logging.getLogger(__name__)

def parse_tools(content):
    """Parse tools from a text file using [tool-name] delimiters."""
    tools = {}
    pattern = re.compile(r'^\[(.+?)\]', re.MULTILINE)
    matches = list(pattern.finditer(content))
    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(content)
        tools[name] = content[start:end].strip()
    return tools


def load_tools(app_root=None, user_templates_dir=None):
    """Load tool definitions from the tools directory with precedence.

    Precedence:
    - If user_templates_dir is provided, prefer <user_templates_dir>/tools/tools.txt
    - Otherwise fallback to <app_root>/text_templates/tools/tools.txt
    """
    if app_root is None:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates = []
    if user_templates_dir:
        candidates.append(os.path.join(user_templates_dir, 'tools', 'tools.txt'))
    candidates.append(os.path.join(app_root, 'text_templates', 'tools', 'tools.txt'))

    tools_file = next((p for p in candidates if os.path.exists(p)), None)
    if not tools_file:
        logger.warning('Tools file not found in any known location: %s', candidates)
        return {}
    with open(tools_file, 'r') as f:
        content = f.read()
    return parse_tools(content)
