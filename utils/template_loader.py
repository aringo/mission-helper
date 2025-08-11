import os
import logging
import json
from utils.template_utils import parse_template, default_template_structure, determine_category
from utils.mission_helpers import find_draft_path
from utils.api import get_all_missions

logger = logging.getLogger(__name__)

def load_task_template(working_folder, listing_codename, mission_id, category=None, app_root=None, user_templates_dir=None):
    """
    Load template sections and scripts for a task based on its listing codename, ID, and category.
    
    Args:
        working_folder: The working folder where drafts are stored
        listing_codename: The codename of the listing
        mission_id: The ID of the mission
        category: The category of the mission (optional)
        app_root: The application root directory for absolute paths (optional)
        
    Returns:
        Dict containing the template data
    """
    try:
        # Get the application root directory for absolute paths
        if app_root is None:
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Normalize user templates dir (optional)
        user_templates_dir = user_templates_dir or ''
        
        # Try to load from a saved draft first (supports title-mapped filenames)
        try:
            draft_path = find_draft_path(working_folder, listing_codename, mission_id)
        except Exception as e:
            logger.error(f"Error finding draft path: {e}")
            draft_path = None

        if draft_path and os.path.exists(draft_path):
            try:
                with open(draft_path, 'r') as f:
                    draft_content = f.read()
                raw_sections = parse_template(draft_content)
                data = format_template_data(raw_sections, draft_path, category or 'web')
                data['is_draft'] = True
                data['needs_template_selection'] = False
                return data
            except Exception as e:
                logger.error(f"Error loading draft from {draft_path}: {e}")
                # Continue to JSON fallback

        # Fallback: older JSON-based draft storage
        try:
            json_draft_path = os.path.join(working_folder, listing_codename, f"{mission_id}.json")
            if os.path.exists(json_draft_path):
                with open(json_draft_path, 'r') as f:
                    draft_data = json.load(f)
                if isinstance(draft_data, dict):
                    # Map to sections expected by format_template_data
                    raw_sections = {
                        'introduction': draft_data.get('introduction', ''),
                        'testing': draft_data.get('testing_methodology', ''),
                        'documentation': draft_data.get('documentation', ''),
                        'scripts': draft_data.get('scripts', []),
                        'conclusion-pass': draft_data.get('conclusion-pass', '') or (draft_data.get('conclusion') if draft_data.get('conclusion_type') == 'pass' else ''),
                        'conclusion-fail': draft_data.get('conclusion-fail', '') or (draft_data.get('conclusion') if draft_data.get('conclusion_type') == 'fail' else ''),
                    }
                    data = format_template_data(raw_sections, json_draft_path, category or 'web')
                    data['is_draft'] = True
                    data['needs_template_selection'] = False
                    return data
        except Exception as e:
            logger.error(f"Error loading JSON draft: {e}")
        
        # We need mission title regardless, so we must fetch the mission data
        missions, _ = get_all_missions()
        
        # Find the specific mission
        task = next((task for task in missions if task.get('id') == mission_id), None)
        if not task:
            logger.error(f"Task with ID {mission_id} not found")
            return default_template_structure(category or 'web', needs_template_selection=True)
            
        # Get mission title for template naming - ALWAYS use the title from the mission
        safe_title = task['title'].replace(' ', '_').replace('/', '_').lower()
        
    # If category is not provided, determine it from the task
        if not category:
            asset_types = task.get('assetTypes', [])

            if asset_types:
                category = determine_category(asset_types)
            else:
                category = 'web'  # Default
        
        logger.info(f"Looking for template for '{safe_title}' in category: {category}")
        
    # First check for a template specific to this mission in the data directory
        mission_template_path = os.path.join(working_folder, listing_codename, f"{safe_title}.txt")
        logger.info(f"Checking for template at: {mission_template_path}")
        
        if os.path.exists(mission_template_path):
            with open(mission_template_path, 'r') as f:
                template_content = f.read()
                raw_sections = parse_template(template_content)
                return format_template_data(raw_sections, mission_template_path, category)
        
    # If no mission-specific template, check the category templates (user dir first, then app dir)
        search_paths = []
        if user_templates_dir:
            search_paths.append(os.path.join(user_templates_dir, category, f"{safe_title}.txt"))
        search_paths.append(os.path.join(app_root, 'text_templates', category, f"{safe_title}.txt"))

        for category_template_path in search_paths:
            logger.info(f"Checking for template at: {category_template_path}")
            if os.path.exists(category_template_path):
                with open(category_template_path, 'r') as f:
                    template_content = f.read()
                    raw_sections = parse_template(template_content)
                    return format_template_data(raw_sections, category_template_path, category)
        
        # Special handling for SV2M: immediately load the default SV2M template
        if category.lower() == 'sv2m':
            sv2m_candidates = []
            if user_templates_dir:
                sv2m_candidates.append(os.path.join(user_templates_dir, 'default', 'sv2m.txt'))
            sv2m_candidates.append(os.path.join(app_root, 'text_templates', 'default', 'sv2m.txt'))
            for sv2m_default_path in sv2m_candidates:
                if os.path.exists(sv2m_default_path):
                    with open(sv2m_default_path, 'r') as f:
                        template_content = f.read()
                    raw_sections = parse_template(template_content)
                    data = format_template_data(raw_sections, sv2m_default_path, 'sv2m')
                    # Do not prompt for template selection
                    data['needs_template_selection'] = False
                    data['show_default_templates'] = False
                    return data
            # If default is missing, fall back to default structure without selection
            logger.warning('Default sv2m.txt not found in text_templates/default; falling back to empty sv2m structure')
            return default_template_structure('sv2m', needs_template_selection=False, show_default_templates=False)

        # If no specific template found, indicate that user should select from default templates
        logger.info(f"No specific template found for {category}/{safe_title}, user should select from defaults")
        return default_template_structure(category, needs_template_selection=True, show_default_templates=True)
        
    except Exception as e:
        logger.error(f"Error loading template: {e}")
        return default_template_structure(category or 'web', needs_template_selection=True, show_default_templates=True)

def format_template_data(sections, template_path, category):
    """Format the raw parsed template sections into the expected structure."""
    # Extract the correct conclusion based on the conclusion type
    # We'll use 'pass' as the default conclusion type
    conclusion_type = 'pass'
    if sections.get('conclusion-fail') and not sections.get('conclusion-pass'):
        conclusion_type = 'fail'
    
    # Map the sections to the expected format
    # The 'testing' section in the file maps to 'testing_methodology' in the UI
    return {
        'sections': {
            'introduction': sections.get('introduction', ''),
            'testing_methodology': sections.get('testing', ''),
            'documentation': sections.get('documentation', ''),
            'scripts': sections.get('scripts', ''),
            'conclusion-pass': sections.get('conclusion-pass', ''),
            'conclusion-fail': sections.get('conclusion-fail', ''),
            'conclusion_type': conclusion_type,
            'conclusion': sections.get(f'conclusion-{conclusion_type}', '')
        },
        'category': category,
        'template_path': template_path,
        'needs_template_selection': False
    }

def save_template(category, filename, template_data, overwrite=False, app_root=None, user_templates_dir=None):
    """
    Save a template to a file.
    
    Args:
        category: The category of the template
        filename: The name of the template file
        template_data: The template data to save
        overwrite: Whether to overwrite an existing template
        app_root: The application root directory for absolute paths (optional)
        
    Returns:
        Dict containing the result of the operation
    """
    # Get the application root directory for absolute paths
    if app_root is None:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Prefer user templates directory for saving when provided
    base_dir = user_templates_dir or os.path.join(app_root, 'text_templates')
    directory = os.path.join(base_dir, category)
    filepath = os.path.join(directory, f"{filename}.txt")

    if not os.path.exists(directory):
        os.makedirs(directory)

    if os.path.exists(filepath) and not overwrite:
        return {"exists": True, "message": "File already exists."}

    introduction = template_data.get('introduction', 'No introduction provided.')
    testing_methodology = template_data.get('testing_methodology', 'No testing methodology provided.')
    documentation = template_data.get('documentation', 'No documentation provided.')
    conclusion_type = template_data.get('conclusion_type', 'pass')
    conclusion = template_data.get('conclusion', 'No conclusion available.')
    scripts = template_data.get('scripts', [])
    if isinstance(scripts, str):
        scripts = [s for s in scripts.splitlines() if s.strip()]

    # Read existing template if it exists
    if os.path.exists(filepath):
        with open(filepath, 'r') as file:
            existing_content = file.read()
        sections = parse_template(existing_content)
    else:
        sections = {
            "introduction": "",
            "testing": "",
            "documentation": "",
            "conclusion-pass": "",
            "conclusion-fail": "",
            "scripts": []
        }

    # Update only the relevant conclusion section
    conclusion_key = f"conclusion-{conclusion_type}"
    sections["introduction"] = introduction
    sections["testing"] = testing_methodology
    sections["documentation"] = documentation
    sections[conclusion_key] = conclusion
    sections["scripts"] = scripts

    # Reconstruct the template content
    template_content = ""
    for key in ['Introduction', 'Testing', 'Documentation', 'conclusion-pass', 'conclusion-fail']:
        content = sections.get(key.lower(), "")
        template_content += f"[{key}]\n{content}\n\n"

    # Add Scripts Section if scripts exist
    if sections.get('scripts'):
        template_content += "[Scripts]\n" + "\n".join(sections['scripts']) + "\n"

    # Write back to the file
    with open(filepath, 'w') as file:
        file.write(template_content.strip())

    return {"exists": False, "message": "Template saved successfully."}

def save_draft(working_folder, listing_codename, filename, draft_data):
    """
    Save a draft to a file.
    
    Args:
        working_folder: The working folder where drafts are stored
        listing_codename: The codename of the listing
        filename: The name of the draft file (can be mission_id or title)
        draft_data: The draft data to save
        
    Returns:
        Dict containing the result of the operation
    """
    directory = os.path.join(working_folder, listing_codename)
    
    # Use the mission title if provided in draft_data, otherwise use filename
    mission_title = draft_data.get('mission_title', '')
    
    if mission_title:
        # Normalize the mission title for filesystem use
        safe_title = mission_title.lower().replace(' ', '_').replace('/', '_')
        safe_title = ''.join(c for c in safe_title if c.isalnum() or c in '_-')
        draft_filename = safe_title
    else:
        # Fallback to the provided filename (typically mission_id)
        draft_filename = filename
    
    # Create metadata file to map between mission ID and filename
    metadata_file = os.path.join(directory, "draft_mapping.json")
    mapping = {}
    
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, 'r') as f:
                mapping = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            mapping = {}
    
    # Store both forward and reverse mappings
    mapping[filename] = draft_filename
    mapping[draft_filename] = filename  # This helps when loading by filename
    
    # Save the mapping
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    with open(metadata_file, 'w') as f:
        json.dump(mapping, f)
    
    # Save the actual draft file
    filepath = os.path.join(directory, f"{draft_filename}.txt")

    introduction = draft_data.get('introduction', 'No introduction provided.')
    testing_methodology = draft_data.get('testing_methodology', 'No testing methodology provided.')
    documentation = draft_data.get('documentation', 'No documentation provided.')
    conclusion_type = draft_data.get('conclusion_type', 'pass')
    conclusion = draft_data.get('conclusion', 'No conclusion available.')
    scripts = draft_data.get('scripts', [])
    if isinstance(scripts, str):
        scripts = [s for s in scripts.splitlines() if s.strip()]

    # Read existing draft if it exists
    if os.path.exists(filepath):
        with open(filepath, 'r') as file:
            existing_content = file.read()
        sections = parse_template(existing_content)
    else:
        sections = {
            "introduction": "",
            "testing": "",
            "documentation": "",
            "conclusion-pass": "",
            "conclusion-fail": "",
            "scripts": []
        }

    # Update only the relevant conclusion section
    conclusion_key = f"conclusion-{conclusion_type}"
    sections["introduction"] = introduction
    sections["testing"] = testing_methodology
    sections["documentation"] = documentation
    sections[conclusion_key] = conclusion
    sections["scripts"] = scripts

    # Reconstruct the template content
    template_content = ""
    for key in ['Introduction', 'Testing', 'Documentation', 'conclusion-pass', 'conclusion-fail']:
        content = sections.get(key.lower(), "")
        template_content += f"[{key}]\n{content}\n\n"

    # Add Scripts section if scripts exist
    if sections["scripts"]:
        scripts_content = "\n".join(sections["scripts"])
        template_content += f"[Scripts]\n{scripts_content}\n"

    # Write back to the file
    with open(filepath, 'w') as file:
        file.write(template_content.strip())

    return {"message": "Draft saved successfully.", "filename": draft_filename} 