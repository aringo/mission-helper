import os
import re
import logging

logger = logging.getLogger(__name__)

def parse_template(template_str):
    """
    Parse a template string into sections.
    
    Args:
        template_str: The template content as a string
        
    Returns:
        Dict containing the parsed sections
    """
    # Define the sections we are interested in
    sections = {}
    section_names = ['Introduction', 'Testing', 'Documentation', 'conclusion-fail', 'conclusion-pass', 'Scripts']

    # Regex to match sections
    pattern = re.compile(r'^\[(Introduction|Testing|Documentation|conclusion-fail|conclusion-pass|Scripts)\]', re.MULTILINE)

    matches = list(pattern.finditer(template_str))
    for i, match in enumerate(matches):
        section_name = match.group(1).lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(template_str)
        content = template_str[start:end].strip()
        
        if section_name == 'scripts':
            # Scripts can be multiple lines; store them as a list
            scripts = content.split('\n') if content else []
            sections[section_name] = scripts
        else:
            sections[section_name] = content

    return sections

def determine_category(asset_types=None):
    """Determine the category based solely on asset types.

    Args:
        asset_types: List of asset types (optional)

    Returns:
        String representing the category (web, sv2m, host, mobile, api)
    """

    if asset_types:
        for asset_type in asset_types:
            asset_type = asset_type.lower()
            if 'host' in asset_type:
                return 'host'
            if 'web' in asset_type:
                return 'web'
            if 'mobile' in asset_type:
                return 'mobile'
            if 'api' in asset_type:
                return 'api'
            if 'sv2m' in asset_type:
                return 'sv2m'

    # Default to web when asset type does not indicate a specific category
    return 'web'

def get_available_scripts(app_root_path, category):
    """
    Get list of available scripts for a given category.
    
    Args:
        app_root_path: The root path of the application
        category: The category to get scripts for
        
    Returns:
        List of script names
    """
    scripts_dir = os.path.join(app_root_path, 'static', 'scripts', category)
    if os.path.exists(scripts_dir):
        return [f for f in os.listdir(scripts_dir) if os.path.isfile(os.path.join(scripts_dir, f))]
    return []

def default_template_structure(category, needs_template_selection=False, show_default_templates=False):
    """
    Return the default template structure with empty sections.
    
    Args:
        category: The category of the template
        needs_template_selection: Whether template selection is needed
        show_default_templates: Whether to show the default templates for selection
        
    Returns:
        Dict containing the default template structure
    """
    return {
        'sections': {
            'introduction': '',
            'testing_methodology': '',
            'documentation': '',
            'conclusion-pass': '',
            'conclusion-fail': '',
            'conclusion_type': 'pass'
        },
        'scripts': [],
        'category': category,
        'template_path': None,
        'needs_template_selection': needs_template_selection,
        'show_default_templates': show_default_templates
    }

def get_default_templates(app_root=None, user_templates_dir=None):
    """
    Get list of available default templates.
    
    Args:
        app_root: The application root directory for absolute paths (optional)
    
    Returns:
        List of template names and their paths
    """
    # Get the application root directory for absolute paths
    if app_root is None:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Prefer user-provided default templates directory when available
    default_templates_dir = None
    if user_templates_dir:
        cand = os.path.join(user_templates_dir, 'default')
        if os.path.isdir(cand):
            default_templates_dir = cand
    if not default_templates_dir:
        default_templates_dir = os.path.join(app_root, 'text_templates', 'default')
    templates = []
    
    if os.path.exists(default_templates_dir):
        for filename in os.listdir(default_templates_dir):
            if filename.endswith('.txt'):
                # Return relative path for consistency
                # Expose a path hint that can be posted back to server; prefer absolute path for user dir
                if user_templates_dir and default_templates_dir.startswith(user_templates_dir):
                    template_path = os.path.join(default_templates_dir, filename)
                else:
                    template_path = os.path.join('text_templates', 'default', filename)
                template_name = os.path.splitext(filename)[0]
                templates.append({
                    'name': template_name,
                    'path': template_path,
                    'display_name': template_name.replace('_', ' ').title()
                })
    
    return templates 