import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, send_from_directory, abort, current_app, send_file
from utils.api import (
    get_all_missions,
    sync_evidence_to_api,
    force_refresh_missions,
    delete_evidence_from_api,
)
from utils.template_utils import determine_category, get_available_scripts, get_default_templates
from utils.template_loader import load_task_template, save_template, save_draft
from werkzeug.utils import secure_filename
# Removed upload_utils imports - functionality moved inline
from datetime import datetime
import json
from utils.mission_helpers import get_mission_by_id, find_draft_path, get_attachment_dirs
import random
import requests
import re
import glob
import time
import base64
import traceback
import string
from requests_toolbelt import MultipartEncoder
from utils.config import CONFIG
import uuid
from utils.ai_generator import detect_network_indicators, strip_scope, rewrite_text
import copy

# Base URL for the Synack platform
PLATFORM_BASE_URL = CONFIG.get("platform", "https://platform.synack.com")

# Set up logging
logger = logging.getLogger(__name__)

# Initialize blueprint
mission_bp = Blueprint('mission', __name__)

def upload_multiple_attachments_to_api(mission_id, attachments, mission, attachments_dir, metadata_dir, title, description):
    """Upload multiple attachments in a single request to the Synack API.

    Parameters
    ----------
    mission_id : str
        Mission identifier.
    attachments : list
        List of dicts with keys 'id', 'filename', 'original_filename',
        'content_type', 'metadata_path' and 'file_path'.
    mission : dict
        Mission details loaded from local storage/API.
    attachments_dir : str
        Directory containing attachment files.
    metadata_dir : str
        Directory containing metadata files.
    title : str
        Title for the evidence group.
    description : str
        Description for the evidence group.

    Returns
    -------
    tuple
        (success: bool, message: str, api_results: list)
    """

    try:
        # Get authentication token
        token_file = current_app.config.get('TOKEN_FILE')
        token = None
        if token_file and os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token = f.read().strip()

        if not token:
            return False, "No authentication token available", None

        organization_uid = mission.get('organizationUid')
        listing_uid = mission.get('listingUid')
        campaign_uid = mission.get('campaignUid')
        if not all([organization_uid, listing_uid, campaign_uid]):
            return False, "Missing mission UID components", None

        api_url = (
            f"{PLATFORM_BASE_URL}/api/tasks/v1/organizations/{organization_uid}/"
            f"listings/{listing_uid}/campaigns/{campaign_uid}/tasks/{mission_id}/attachments"
        )

        fields = []
        fields.append(('metadata', json.dumps({'title': title, 'description': description})))

        file_handles = []
        try:
            for att in attachments:
                fh = open(att['file_path'], 'rb')
                file_handles.append(fh)
                fields.append(
                    ('file', (att['original_filename'], fh, att['content_type']))
                )

            form_data = MultipartEncoder(fields=fields)
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': form_data.content_type
            }

            current_app.logger.info(f"Making multi-upload request to {api_url}")
            response = requests.post(api_url, headers=headers, data=form_data)

            if response.status_code not in [200, 201]:
                current_app.logger.error(
                    f"API request failed: {response.status_code} - {response.text}"
                )
                return False, f"API request failed with status {response.status_code}", None

            api_response = response.json() if response.text else []
            if isinstance(api_response, dict):
                api_results = [api_response]
            elif isinstance(api_response, list):
                api_results = api_response
            else:
                api_results = []

            if not api_results:
                current_app.logger.error(f"No valid response data from API: {api_response}")
                return False, "No Synack ID in API response", None

            return True, "Successfully uploaded to API", api_results

        finally:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass

    except Exception as e:
        current_app.logger.error(f"Error uploading attachments to API: {str(e)}")
        return False, f"Error uploading to API: {str(e)}", None

def upload_attachment_to_api(mission_id, attachment_id, mission, attachments_dir, metadata_dir):
    """
    Helper function to upload a single attachment to the API.
    Returns tuple (success, message, synack_id)
    """
    try:
        # Find the file based on the attachment_id
        attachment_file = None
        metadata_file = None
        
        # Look for the file in different ways
        for filename in os.listdir(attachments_dir):
            file_path = os.path.join(attachments_dir, filename)
            if not os.path.isfile(file_path) or filename.startswith('temp_'):
                continue
                
            # Check if filename starts with attachment_id
            if filename.startswith(f"{attachment_id}_"):
                attachment_file = filename
                metadata_file = os.path.join(metadata_dir, f"{filename}.json")
                break
                
            # Check metadata file for this attachment_id
            potential_metadata = os.path.join(metadata_dir, f"{filename}.json")
            if os.path.exists(potential_metadata):
                try:
                    with open(potential_metadata, 'r') as f:
                        metadata = json.load(f)
                    if metadata.get('id') == attachment_id:
                        attachment_file = filename
                        metadata_file = potential_metadata
                        break
                except Exception as e:
                    current_app.logger.error(f"Error reading metadata for {filename}: {e}")
        
        if not attachment_file or not os.path.exists(os.path.join(attachments_dir, attachment_file)):
            return False, f"Attachment file not found for ID {attachment_id}", None
        
        # Load metadata if it exists
        metadata = {}
        if metadata_file and os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
            except Exception as e:
                current_app.logger.error(f"Error reading metadata: {e}")
                return False, f"Error reading metadata: {str(e)}", None
        
        # Check if already uploaded to API
        if metadata.get('uploaded_to_api'):
            return True, "Already uploaded to API", metadata.get('synack_id')
        
        # Get file content
        file_path = os.path.join(attachments_dir, attachment_file)
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Get authentication token from file configured in Flask app
        token_file = current_app.config.get('TOKEN_FILE')
        token = None
        if token_file and os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token = f.read().strip()
        
        if not token:
            return False, "No authentication token available", None
        
        # Get mission UID components
        organization_uid = mission.get('organizationUid')
        listing_uid = mission.get('listingUid')
        campaign_uid = mission.get('campaignUid')
        
        if not all([organization_uid, listing_uid, campaign_uid]):
            return False, "Missing mission UID components", None
        
        # API endpoint
        api_url = (
            f"{PLATFORM_BASE_URL}/api/tasks/v1/organizations/{organization_uid}/"
            f"listings/{listing_uid}/campaigns/{campaign_uid}/tasks/{mission_id}/attachments"
        )
        
        # Create multipart/form-data payload
        original_filename = metadata.get('original_filename', attachment_file)
        title = metadata.get('title', os.path.splitext(original_filename)[0])
        description = metadata.get('description', '')
        content_type = metadata.get('content_type', 'application/octet-stream')
        
        form_data = MultipartEncoder(
            fields={
                'metadata': json.dumps({
                    'title': title,
                    'description': description
                }),
                'file': (original_filename, file_content, content_type)
            }
        )
        
        # Request headers
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': form_data.content_type
        }
        
        # Make API request
        current_app.logger.info(f"Making API request to {api_url}")
        
        response = requests.post(api_url, headers=headers, data=form_data)
        
        if response.status_code not in [200, 201]:
            current_app.logger.error(f"API request failed: {response.status_code} - {response.text}")
            return False, f"API request failed with status {response.status_code}", None
        
        # Process response
        api_response = response.json()
        synack_id = None
        
        # Handle both list and dictionary response formats
        if isinstance(api_response, dict) and 'id' in api_response:
            synack_id = api_response['id']
        elif isinstance(api_response, list) and len(api_response) > 0 and isinstance(api_response[0], dict):
            # If response is a list, take the first item's ID
            synack_id = api_response[0].get('id')
        
        if not synack_id:
            current_app.logger.error(f"No Synack ID in API response: {api_response}")
            return False, "No Synack ID in API response", None
        
        # Update metadata
        metadata['synack_id'] = synack_id
        metadata['uploaded_to_api'] = True
        metadata['upload_api_time'] = datetime.now().isoformat()
        
        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=4)
        
        # Rename the file to include the Synack ID if it doesn't already
        if not attachment_file.startswith(f"{synack_id}_"):
            # Get base filename without any potential previous ID
            parts = attachment_file.split('_', 1)
            base_filename = parts[1] if len(parts) > 1 else attachment_file
            
            # Create new filename with Synack ID
            new_filename = f"{synack_id}_{base_filename}"
            new_file_path = os.path.join(attachments_dir, new_filename)
            
            # Rename file
            try:
                os.rename(file_path, new_file_path)
                current_app.logger.info(f"Renamed file from {attachment_file} to {new_filename}")
                
                # Rename metadata file
                new_metadata_path = os.path.join(metadata_dir, f"{new_filename}.json")
                if metadata_file and os.path.exists(metadata_file):
                    os.rename(metadata_file, new_metadata_path)
                
                # Update file reference in metadata
                metadata['filename'] = new_filename
                with open(new_metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=4)
                
            except Exception as e:
                current_app.logger.error(f"Error renaming file: {e}")
                # Not critical, continue with original filename
        
        current_app.logger.info(f"Successfully uploaded attachment {attachment_id} to API with Synack ID {synack_id}")
        return True, "Successfully uploaded to API", synack_id
        
    except Exception as e:
        current_app.logger.error(f"Error uploading attachment to API: {str(e)}")
        return False, f"Error uploading to API: {str(e)}", None

# Load configuration
def get_working_folder():
    """Get the working folder from app.config"""
    from flask import current_app
    return current_app.config.get('WORKING_FOLDER', 'data')

@mission_bp.route('/')
def index():
    """Display the list of missions."""
    missions, _ = get_all_missions()
    missions_info = [
        {
            "id": mission.get('id'),
            "title": mission.get('title', ''),
            "listingCodename": mission.get('listingCodename', ''),
            "payout": mission.get('payout', {}),
            "claimedOn": mission.get('claimedOn', ''),
            "returnedForEditOn": mission.get('returnedForEditOn', ''),
            "maxCompletionTimeInSecs": mission.get('maxCompletionTimeInSecs', 0),
            "assetTypes": mission.get('assetTypes', []),
            "description": mission.get('description', ''),
            "attackTypes": mission.get('attackTypes', []),
            "categories": mission.get('categories', [])
        }
        for mission in missions
    ]
    return render_template('index.html', missions=missions_info)

@mission_bp.route('/mission_form/<path:mission_id>', methods=['GET', 'POST'])
def mission_form(mission_id):
    """Handle mission form display and submission."""
    logger.info(f"Mission form accessed for ID: {mission_id}")
    try:
        # Get mission data
        missions, _ = get_all_missions()
        mission = next((m for m in missions if m.get('id') == mission_id), None)

        if not mission:
            logger.error(f"Mission with ID {mission_id} not found")
            flash(f"Mission with ID {mission_id} not found", "error")
            return redirect(url_for('mission.index'))

        # Get working folder and listing codename
        working_folder = get_working_folder()
        listing_codename = mission.get('listingCodename', 'unknown')

        # Get app root for absolute paths
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Determine category hint before loading template (SV2M special case)
        task_type = (mission.get('taskType') or '').upper()
        category_hint = 'sv2m' if task_type == 'SV2M' else None

        # Load template data with category hint so SV2M uses its default immediately
        template_data = load_task_template(
            working_folder,
            listing_codename,
            mission_id,
            category=category_hint,
            app_root=app_root,
            user_templates_dir=current_app.config.get('USER_TEMPLATES_DIR')
        )

        # Get final category from template data or fallback logic
        category = template_data.get('category', category_hint or 'web')
        if not category or category == 'default':
            # Try to determine category from mission data using asset types
            asset_types = mission.get('assetTypes', [])
            category = determine_category(asset_types) if asset_types else 'web'

        # Get available scripts for this category
        scripts = get_available_scripts(app_root, category)

        # Format deadline
        deadline = mission.get('deadline', '')
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                deadline = deadline_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
            except Exception:
                logger.warning(f"Failed to parse deadline: {deadline}")

        # Check if we should show default templates
        show_default_templates = template_data.get('show_default_templates', False)
        logger.info(f"Show default templates: {show_default_templates}")

        # Get default templates if needed
        default_templates = get_default_templates(
            app_root=app_root,
            user_templates_dir=current_app.config.get('USER_TEMPLATES_DIR')
        ) if show_default_templates else []

        # Extract script names from sections for the template
        template_scripts = []
        if 'sections' in template_data and 'scripts' in template_data['sections']:
            scripts_data = template_data['sections']['scripts']
            if isinstance(scripts_data, list):
                template_scripts = scripts_data
            elif isinstance(scripts_data, str):
                template_scripts = [s.strip() for s in scripts_data.split('\n') if s.strip()]

        # Format conclusion type
        conclusion_type = template_data.get('sections', {}).get('conclusion_type', 'pass')

        # Log template data for debugging
        logger.info(f"Template data loaded: {template_data.get('template_path', 'No template path')}")
        logger.info(f"Needs template selection: {template_data.get('needs_template_selection', False)}")

        ai_enabled = bool(CONFIG.get('ai_key') and CONFIG.get('ai_model'))
        mission_scope = mission.get('scope', '') or ''

        return render_template(
            'mission_form.html',
            mission=mission,
            mission_id=mission_id,
            sections=template_data.get('sections', {}),
            scripts=scripts,
            template_scripts=template_scripts,
            category=category,
            needs_template_selection=template_data.get('needs_template_selection', False),
            default_templates=default_templates,
            show_default_templates=show_default_templates,
            conclusion_type=conclusion_type,
            ai_enabled=ai_enabled,
            mission_scope=mission_scope,
            deadline=deadline,
        )

    except Exception as e:
        logger.error(f"Error loading mission form: {e}")
        logger.error(traceback.format_exc())
        flash(f"Error loading mission: {str(e)}", "error")
        return redirect(url_for('mission.index'))

@mission_bp.route('/save_template', methods=['POST'])
def save_template_route():
    """Save a template to a file."""
    
    try:
        # Get the template data from the request
        data = request.get_json()
        
        # Extract template name and validate
        template_name = data.get('template_name', '').strip()
        if not template_name:
            return jsonify({'success': False, 'message': 'Template name is required.'}), 400
        
        # Determine category based on template content or use default
        category = data.get('category', request.args.get('category', 'default'))
        if str(category).lower() == 'sv2m':
            return jsonify({'success': False, 'message': 'SV2M templates cannot be saved. Use Save Draft instead.'}), 400
        
        # Resolve base dir: prefer user templates dir if configured; otherwise app text_templates
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base_dir = current_app.config.get('USER_TEMPLATES_DIR') or os.path.join(app_root, 'text_templates')
        # Create the templates directory if it doesn't exist
        template_dir = os.path.join(base_dir, category)
        os.makedirs(template_dir, exist_ok=True)
        # Create the template file path
        if category.lower() == 'sv2m':
            # Always save under default/sv2m.txt in the chosen base_dir
            template_dir = os.path.join(base_dir, 'default')
            os.makedirs(template_dir, exist_ok=True)
            template_path = os.path.join(template_dir, 'sv2m.txt')
        else:
            template_path = os.path.join(template_dir, f"{template_name}.txt")
        
        # Format the template data in the expected format used by the application
        template_content = "[Introduction]\n"
        
        # Extract introduction content from multiple possible sources
        introduction = data.get('introduction', data.get('content', ''))
        template_content += introduction + "\n\n\n"
        
        # Extract testing methodology
        testing = data.get('testing_methodology', data.get('supporting_content', ''))
        template_content += "[Testing]\n"
        template_content += testing + "\n\n"
        
        # Extract documentation
        documentation = data.get('documentation', '')
        if documentation.strip():
            template_content += "[Documentation]\n"
            template_content += documentation + "\n\n"
        
        # Extract scripts - handle both string and array formats
        scripts = data.get('scripts', '')
        if scripts:
            template_content += "[Scripts]\n"
            if isinstance(scripts, list):
                template_content += "\n".join(scripts) + "\n\n"
            else:
                template_content += scripts + "\n\n"
        
        # Handle conclusion sections - look for multiple formats
        conclusion_pass = data.get('conclusion-pass', '')
        if conclusion_pass.strip():
            template_content += "[conclusion-pass]\n"
            template_content += conclusion_pass + "\n\n"
        
        conclusion_fail = data.get('conclusion-fail', '')
        if conclusion_fail.strip():
            template_content += "[conclusion-fail]\n"
            template_content += conclusion_fail + "\n\n"
        
        # If we only have one conclusion, check if it has a type
        conclusion = data.get('conclusion', '')
        conclusion_type = data.get('conclusion_type', 'pass')
        if conclusion and not (conclusion_pass or conclusion_fail):
            template_content += f"[conclusion-{conclusion_type}]\n"
            template_content += conclusion + "\n\n"
        
        # Check for overwrite flag
        overwrite = request.args.get('overwrite', 'false').lower() == 'true'

        # Check if file exists and we're not overwriting (except SV2M default which we allow overwrite prompt)
        if os.path.exists(template_path) and not overwrite:
            return jsonify({'success': False, 'message': 'Template already exists', 'exists': True})

        # Save the template file
        with open(template_path, 'w') as f:
            f.write(template_content)

        logger.info(f"Template saved successfully to {template_path}")
        return jsonify({'success': True, 'message': 'Template saved successfully', 'path': template_path})
    except Exception as e:
        logger.error(f"Error saving template: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'})

@mission_bp.route('/save_draft/<listing_codename>/<filename>', methods=['POST'])
def save_draft_route(listing_codename, filename):
    """Save a draft to a file."""
    working_folder = get_working_folder()
    data = request.json
    
    result = save_draft(working_folder, listing_codename, filename, data)
    return jsonify(result)

@mission_bp.route('/sync_to_api/<mission_id>', methods=['POST'])
def sync_to_api_route(mission_id):
    """Sync evidence to API."""
    data = request.json
    result = sync_evidence_to_api(mission_id, data)
    return jsonify(result)

@mission_bp.route('/get_conclusion/<listing_codename>/<mission_id>', methods=['POST'])
def get_conclusion(listing_codename, mission_id):
    """Get the conclusion based on the selected conclusion type."""
    data = request.get_json()
    conclusion_type = data.get('conclusion_type', 'pass')
    
    # First try to load from a previously saved draft
    working_folder = get_working_folder()
    directory = os.path.join(working_folder, listing_codename)
    
    draft_path = find_draft_path(working_folder, listing_codename, mission_id)
    if draft_path:
        try:
            logger.info(f"Found draft file: {draft_path}")
            with open(draft_path, "r") as f:
                draft_content = f.read()
            from utils.template_utils import parse_template
            sections = parse_template(draft_content)
            conclusion_key = f"conclusion-{conclusion_type}"
            if conclusion_key in sections:
                logger.info(f"Loaded {conclusion_type} conclusion from draft")
                return jsonify({"success": True, "conclusion": sections[conclusion_key]})
        except Exception as e:
            logger.error(f"Error loading conclusion from draft {draft_path}: {e}")
    # Load the template data as fallback
    template_data = load_task_template(working_folder, listing_codename, mission_id)
    sections = template_data.get('sections', {})

    # Fetch the appropriate conclusion section
    conclusion_key = f"conclusion-{conclusion_type}"
    conclusion = sections.get(conclusion_key, "No conclusion available.")

    return jsonify({'success': True, 'conclusion': conclusion})

@mission_bp.route('/get_available_templates')
def get_available_templates():
    """
    Get a list of available templates from the standard folders.
    """
    try:
        # Get app root for absolute paths
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # Define template categories
        categories = ['default', 'web', 'host']
        
        templates = []
        for category in categories:
            template_dir = os.path.join(app_root, 'text_templates', category)
            
            # Skip if directory doesn't exist
            if not os.path.exists(template_dir):
                continue
            
            # Get all .txt files in the directory
            template_files = [f for f in os.listdir(template_dir) if f.endswith('.txt')]
            
            for filename in template_files:
                template_id = os.path.splitext(filename)[0]
                template_name = template_id.replace('_', ' ').title()
                
                templates.append({
                    'id': template_id,
                    'name': template_name,
                    'category': category,
                    'path': os.path.join(template_dir, filename)
                })
        
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        logger.error(f"Error getting available templates: {e}")
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'})

@mission_bp.route('/load_template/<template_id>')
def load_template(template_id):
    """
    Load a template from any of the template categories.
    """
    try:
        # Get app root for absolute paths
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # Check each category for the template
        categories = ['default', 'web', 'host']
        template_path = None
        category = None
        
        # Parse template_id to check if it includes category info
        if '/' in template_id:
            parts = template_id.split('/')
            if len(parts) == 2:
                category, template_id = parts
                # Only check this specific category
                categories = [category]
        
        # Search for the template in the specified categories
        for cat in categories:
            path = os.path.join(app_root, 'text_templates', cat, f"{template_id}.txt")
            if os.path.exists(path):
                template_path = path
                category = cat
                break
                
        if not template_path:
            return jsonify({'success': False, 'message': 'Template not found'})
        
        # Parse the template using the utility function
        from utils.template_utils import parse_template
        
        with open(template_path, 'r') as f:
            template_content = f.read()
            
        # Parse the template content
        sections = parse_template(template_content)
        
        # Map the sections to the expected format
        formatted_sections = {
            'title': template_id.replace('_', ' ').title(),
            'content': sections.get('introduction', ''),
            'supporting_content': sections.get('testing', ''),
            'documentation': sections.get('documentation', ''),
            'script': sections.get('scripts', ''),
            'conclusion-pass': sections.get('conclusion-pass', ''),
            'conclusion-fail': sections.get('conclusion-fail', '')
        }
        
        return jsonify({
            'success': True, 
            'sections': formatted_sections,
            'category': category
        })
    except Exception as e:
        logger.error(f"Error loading template: {e}")
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'})

@mission_bp.route('/get_mission_attachments/<mission_id>', methods=['GET'])
def get_mission_attachments(mission_id):
    """Get attachments for a specific mission."""
    
    current_app.logger.debug(f"Getting attachments for mission ID: {mission_id}")
    
    if not mission_id:
        current_app.logger.error("Mission ID is required")
        return jsonify({'success': False, 'message': 'Mission ID is required'}), 400
    
    # Get mission from metadata
    mission = get_mission_by_id(mission_id)
    if not mission:
        current_app.logger.error(f"Mission with ID {mission_id} not found")
        return jsonify({"success": False, "message": "Mission not found"}), 404
    
    # Get mission attachments dir
    listing_codename = mission.get('listingCodename', 'unknown')
    current_app.logger.debug(f"Mission listing codename: {listing_codename}")
    
    attachments_dir, metadata_dir = get_attachment_dirs(current_app.config["UPLOAD_FOLDER"], listing_codename, mission_id)
    
    current_app.logger.debug(f"Attachments directory: {attachments_dir}")
    current_app.logger.debug(f"Metadata directory: {metadata_dir}")
    
    # Check if directory exists
    if not os.path.exists(attachments_dir):
        current_app.logger.warning(f"Attachments directory does not exist: {attachments_dir}")
        os.makedirs(attachments_dir, exist_ok=True)
        current_app.logger.debug(f"Created attachments directory: {attachments_dir}")
        
    if not os.path.exists(metadata_dir):
        os.makedirs(metadata_dir, exist_ok=True)
        current_app.logger.debug(f"Created metadata directory: {metadata_dir}")
    
    # Get all image files in the directory
    extensions = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']
    all_files = []
    for ext in extensions:
        files = glob.glob(os.path.join(attachments_dir, f'*.{ext}'))
        all_files.extend(files)
    
    current_app.logger.debug(f"Found {len(all_files)} attachment files")
    
    attachments = []
    for file_path in all_files:
        file_name = os.path.basename(file_path)
        current_app.logger.debug(f"Processing attachment: {file_name}")
        
        metadata = {}
        
        # Try to load metadata if exists
        metadata_file = os.path.join(metadata_dir, f"{file_name}.json")
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                current_app.logger.debug(f"Loaded metadata for {file_name}")
            except Exception as e:
                current_app.logger.error(f"Error loading metadata for {file_name}: {str(e)}")
        else:
            current_app.logger.debug(f"No metadata file found for {file_name}")
        
        # Create attachment object
        attachment = {
            'id': os.path.splitext(file_name)[0],  # Use filename without extension as ID
            'filename': file_name,
            'url': url_for('mission.get_attachment', mission_id=mission_id, filename=file_name),
            'title': metadata.get('title', file_name),
            'description': metadata.get('description', ''),
            'uploaded_at': metadata.get('uploaded_at', ''),
            'uploaded_to_api': metadata.get('uploaded_to_api', False),
        }
        attachments.append(attachment)
    
    current_app.logger.debug(f"Returning {len(attachments)} attachments")
    return jsonify({'success': True, 'attachments': attachments}), 200

@mission_bp.route('/get_attachment/<mission_id>/<path:filename>')
def get_attachment(mission_id, filename):
    """Serve an attachment file by filename."""
    if not mission_id or not filename:
        abort(400)
    
    mission = get_mission_by_id(mission_id)
    if not mission:
        abort(404)
    
    attachments_dir, _ = get_attachment_dirs(current_app.config["UPLOAD_FOLDER"], mission.get("listingCodename", "unknown"), mission_id)
    
    # Check if it's a direct filename request
    file_path = os.path.join(attachments_dir, filename)
    if os.path.exists(file_path):
        return send_from_directory(attachments_dir, filename)
    
    # If file doesn't exist directly, try to find it by Synack ID
    # (in case filename was actually a Synack ID)
    if len(filename) >= 36 and '-' in filename:
        potential_synack_id = filename
        # Search for files starting with this ID
        matching_files = []
        for f in os.listdir(attachments_dir):
            if f.startswith(potential_synack_id + '_') and os.path.isfile(os.path.join(attachments_dir, f)):
                matching_files.append(f)
        
        if matching_files:
            # Use the first matching file
            return send_from_directory(attachments_dir, matching_files[0])
    
    # If we still haven't found the file, return 404
    abort(404)

@mission_bp.route('/mission/<mission_id>/delete_attachment/<attachment_id>', methods=['DELETE'])
def delete_synack_attachment(mission_id, attachment_id):
    """Delete an attachment both locally and from Synack API."""
    try:
        current_app.logger.info(f"Delete request for attachment {attachment_id} in mission {mission_id}")
        
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            current_app.logger.error(f"Mission with ID {mission_id} not found")
            return jsonify({"success": False, "message": "Mission not found"}), 404
        listing_codename = mission.get('listingCodename', 'unknown')
        attachments_dir, metadata_dir = get_attachment_dirs(
            current_app.config["UPLOAD_FOLDER"], listing_codename, mission_id
        )

        organization_uid = mission.get("organizationUid")
        listing_uid = mission.get("listingUid")
        campaign_uid = mission.get("campaignUid")
        
        # Make sure directories exist
        if not os.path.exists(attachments_dir):
            current_app.logger.error(f"Attachments directory not found: {attachments_dir}")
            return jsonify({'success': False, 'message': 'Attachments directory not found'}), 404
        
        current_app.logger.info(f"Searching for files matching attachment ID: {attachment_id}")
        
        # First, find the file by Synack ID or filename prefix
        matching_files = []
        
        # Look for files starting with the attachment ID (for files named with Synack ID pattern)
        for filename in os.listdir(attachments_dir):
            file_path = os.path.join(attachments_dir, filename)
            if os.path.isfile(file_path) and not filename.startswith('temp_'):
                # First check: Does the filename start with the attachment ID?
                # This is true for files named like: "synack-id_title.ext"
                if filename.startswith(attachment_id + '_'):
                    current_app.logger.info(f"Found file with matching prefix: {filename}")
                    matching_files.append(filename)
                    continue
                
                # Second check: Is the attachment ID the filename without extension?
                # This is true for locally uploaded files without Synack ID
                if os.path.splitext(filename)[0] == attachment_id:
                    current_app.logger.info(f"Found file with matching name: {filename}")
                    matching_files.append(filename)
                    continue
                
                # Third check: Check metadata for Synack ID
                metadata_file = os.path.join(metadata_dir, f"{filename}.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            if metadata.get('synack_id') == attachment_id:
                                current_app.logger.info(f"Found file with matching Synack ID in metadata: {filename}")
                                matching_files.append(filename)
                    except Exception as e:
                        current_app.logger.error(f"Error reading metadata for {filename}: {str(e)}")
        
        if not matching_files:
            current_app.logger.error(f"No files found matching attachment ID: {attachment_id}")
            return jsonify({'success': False, 'message': 'Attachment not found'}), 404
            
        current_app.logger.info(f"Found {len(matching_files)} matching files: {matching_files}")
        
        deleted_files = []
        api_deleted_overall = False
        api_error = None

        for filename in matching_files:
            file_path = os.path.join(attachments_dir, filename)
            metadata_path = os.path.join(metadata_dir, f"{filename}.json")

            synack_id = None
            uploaded_to_api = False
            metadata = {}

            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)

                    uploaded_to_api = metadata.get('uploaded_to_api', False)
                    if uploaded_to_api and 'synack_id' in metadata:
                        synack_id = metadata.get('synack_id')
                        current_app.logger.info(
                            f"File was uploaded to API with Synack ID: {synack_id}"
                        )
                except Exception as e:
                    current_app.logger.error(f"Error reading metadata: {str(e)}")

            if uploaded_to_api and synack_id:
                try:
                    api_deleted, api_err = delete_evidence_from_api(
                        mission_id,
                        synack_id,
                        organization_uid,
                        listing_uid,
                        campaign_uid,
                    )
                    if api_deleted:
                        api_deleted_overall = True
                        current_app.logger.info("Successfully deleted evidence via API")
                    else:
                        api_error = api_err
                        current_app.logger.error(
                            f"Failed to delete evidence via API: {api_err}"
                        )
                except Exception as e:
                    api_error = str(e)
                    current_app.logger.error(f"Error deleting evidence via API: {e}")

            try:
                os.remove(file_path)
                deleted_files.append(filename)
                current_app.logger.info(f"Deleted local file: {file_path}")

                if os.path.exists(metadata_path):
                    os.remove(metadata_path)
                    current_app.logger.info(f"Deleted metadata file: {metadata_path}")
            except Exception as e:
                current_app.logger.error(f"Error deleting local file: {str(e)}")
                return jsonify({
                    'success': False,
                    'message': f'Error deleting local file: {str(e)}',
                    'deleted_files': deleted_files,
                    'deleted_from_api': api_deleted_overall
                }), 500

        result = {
            'success': True,
            'message': 'Attachment deleted successfully',
            'deleted_files': deleted_files,
            'deleted_from_api': api_deleted_overall
        }

        if api_error and not api_deleted_overall:
            result['api_warning'] = (
                "The file was deleted locally but could not be deleted from "
                f"Synack API. Error: {api_error}"
            )

        return jsonify(result), 200
    
    except Exception as e:
        current_app.logger.error(f"Error in delete_synack_attachment: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500

@mission_bp.route('/mission/<mission_id>/attachments', methods=['GET'])
def mission_attachments(mission_id):
    """Endpoint for getting mission attachments with Synack IDs."""
    try:
        current_app.logger.info(f"Fetching attachments for mission: {mission_id}")
        
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            current_app.logger.warning(f"Mission with ID {mission_id} not found, returning empty attachments list")
            return jsonify({"success": True, "attachments": [], "message": "Mission not found"}), 200
        
        # Get listing codename
        listing_codename = mission.get('listingCodename', 'unknown')
        
        # Check directory structure
        upload_folder = current_app.config.get('UPLOAD_FOLDER')
        if not upload_folder:
            current_app.logger.error("UPLOAD_FOLDER not configured in app settings")
            return jsonify({'success': False, 'attachments': [], 'message': 'Upload folder not configured'}), 200
            
        upload_dir = os.path.join(upload_folder, listing_codename, mission_id)
        metadata_dir = os.path.join(upload_dir, 'metadata')
        
        # Create directories if they don't exist
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(metadata_dir, exist_ok=True)
        
        # Get all image files in the directory
        extensions = []  # Removed image file extensions as requested
        all_files = []

        try:
            for ext in extensions:
                pattern = os.path.join(upload_dir, f'*.{ext}')
                files = glob.glob(pattern)
                current_app.logger.debug(f"Found {len(files)} files with pattern {pattern}")
                all_files.extend(files)
        except Exception as e:
            current_app.logger.error(f"Error searching for files: {str(e)}")
            return jsonify({'success': False, 'attachments': [], 'message': f'Error searching for files: {str(e)}'}), 200

        current_app.logger.info(f"Found {len(all_files)} attachment files")

        attachments_dict = {}

        # Load local attachments first
        for file_path in all_files:
            try:
                file_name = os.path.basename(file_path)

                # Skip temporary files
                if file_name.startswith('temp_'):
                    current_app.logger.debug(f"Skipping temporary file: {file_name}")
                    continue

                current_app.logger.debug(f"Processing attachment: {file_name}")

                metadata = {}
                synack_id = None

                # Try to extract Synack ID from filename
                try:
                    file_parts = os.path.splitext(file_name)[0].split('_', 1)
                    if len(file_parts) > 1:
                        potential_id = file_parts[0]
                        if '-' in potential_id and len(potential_id) >= 36:
                            synack_id = potential_id
                except Exception as e:
                    current_app.logger.debug(f"Error extracting Synack ID from filename: {str(e)}")

                metadata_file = os.path.join(metadata_dir, f"{file_name}.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                        current_app.logger.debug(f"Loaded metadata for {file_name}")

                        if not synack_id and 'synack_id' in metadata:
                            synack_id = metadata.get('synack_id')
                    except Exception as e:
                        current_app.logger.error(f"Error loading metadata for {file_name}: {str(e)}")
                else:
                    current_app.logger.debug(f"No metadata file found for {file_name}")

                if not os.path.exists(file_path):
                    current_app.logger.warning(f"File no longer exists: {file_path}")
                    continue

                try:
                    file_size = os.path.getsize(file_path)
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
                except Exception as e:
                    current_app.logger.error(f"Error getting file stats: {str(e)}")
                    file_size = 0
                    file_mtime = datetime.now().isoformat()

                attachment = {
                    'id': synack_id or os.path.splitext(file_name)[0],
                    'filename': file_name,
                    'original_filename': metadata.get('original_filename', file_name),
                    'url': url_for('mission.get_attachment', mission_id=mission_id, filename=file_name),
                    'title': metadata.get('title', file_name),
                    'description': metadata.get('description', ''),
                    'uploaded_at': metadata.get('uploaded_at', file_mtime),
                    'synack_id': synack_id,
                    'uploaded_to_api': metadata.get('uploaded_to_api', False),
                    'size': file_size
                }
                attachments_dict[attachment['id']] = attachment
            except Exception as e:
                current_app.logger.error(f"Error processing attachment file {file_path}: {str(e)}")

        # Also fetch attachments from the API and merge
        # Get authentication token from file configured in Flask app
        token_file = current_app.config.get('TOKEN_FILE')
        token = None
        if token_file and os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token = f.read().strip()
        
        if token:
            organization_uid = mission.get('organizationUid')
            listing_uid = mission.get('listingUid')
            campaign_uid = mission.get('campaignUid')
            if all([organization_uid, listing_uid, campaign_uid]):
                api_url = (
                    f"{PLATFORM_BASE_URL}/api/tasks/v1/organizations/{organization_uid}/"
                    f"listings/{listing_uid}/campaigns/{campaign_uid}/tasks/{mission_id}/attachments"
                )
                try:
                    headers = {'Authorization': f'Bearer {token}'}
                    resp = requests.get(api_url, headers=headers)
                    if resp.status_code in [200, 201]:
                        api_data = resp.json() if resp.text else []
                        if isinstance(api_data, list):
                            for item in api_data:
                                att_id = item.get('id')
                                if att_id and att_id not in attachments_dict:
                                    attachments_dict[att_id] = {
                                        'id': att_id,
                                        'filename': item.get('originalFilename', ''),
                                        'url': item.get('data') or item.get('thumbnailData'),
                                        'title': item.get('title', item.get('originalFilename', '')),
                                        'description': item.get('description', ''),
                                        'uploaded_at': item.get('createdOn'),
                                        'size': item.get('sizeInBytes'),
                                        'uploaded_to_api': True,
                                    }
                    else:
                        current_app.logger.error(
                            f"API request failed: {resp.status_code} - {resp.text}"
                        )
                except Exception as api_e:
                    current_app.logger.error(f"Error fetching attachments from API: {api_e}")

        attachments = list(attachments_dict.values())

        # Sort attachments by upload date, newest first
        try:
            attachments.sort(key=lambda x: x.get('uploaded_at', ''), reverse=True)
        except Exception as e:
            current_app.logger.error(f"Error sorting attachments: {str(e)}")

        current_app.logger.info(f"Returning {len(attachments)} attachments")
        return jsonify({
            'success': True,
            'attachments': attachments,
            'mission_id': mission_id,
            'listing_codename': listing_codename
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error getting attachments: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        # Always return a 200 with a structured response
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}', 
            'attachments': [],
            'mission_id': mission_id
        }), 200

@mission_bp.route('/mission/<mission_id>/test_attachments', methods=['GET'])
def test_mission_attachments(mission_id):
    """Test endpoint to diagnose attachment functionality."""
    try:
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            missions_for_debug, _ = get_all_missions()
            return jsonify({
                "status": "error",
                "message": f"Mission with ID {mission_id} not found",
                "all_mission_ids": [m.get("id") for m in missions_for_debug if m.get("id")]
            }), 404
        # Get listing codename
        listing_codename = mission.get('listingCodename', 'unknown')
        
        # Check directory structure
        upload_folder = current_app.config['UPLOAD_FOLDER']
        upload_dir = os.path.join(upload_folder, listing_codename, mission_id)
        metadata_dir = os.path.join(upload_dir, 'metadata')
        
        dirs_exist = {
            'upload_folder': os.path.exists(upload_folder),
            'upload_dir': os.path.exists(upload_dir),
            'metadata_dir': os.path.exists(metadata_dir)
        }
        
        # Create dirs if they don't exist
        if not dirs_exist['upload_dir']:
            os.makedirs(upload_dir, exist_ok=True)
        
        if not dirs_exist['metadata_dir']:
            os.makedirs(metadata_dir, exist_ok=True)
        
        # List all files in upload directory
        files = []
        if os.path.exists(upload_dir):
            for filename in os.listdir(upload_dir):
                file_path = os.path.join(upload_dir, filename)
                if os.path.isfile(file_path) and not filename.startswith('.'):
                    files.append({
                        'filename': filename,
                        'size': os.path.getsize(file_path),
                        'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat(),
                        'metadata_exists': os.path.exists(os.path.join(metadata_dir, f"{filename}.json"))
                    })
        
        # Check if the get_attachment view works
        attachment_url = None
        if files:
            attachment_url = url_for('mission.get_attachment', 
                                   mission_id=mission_id, 
                                   filename=files[0]['filename'], 
                                   _external=True)
        
        return jsonify({
            'status': 'success',
            'mission_id': mission_id,
            'listing_codename': listing_codename,
            'directory_structure': {
                'upload_folder': upload_folder,
                'upload_dir': upload_dir,
                'metadata_dir': metadata_dir
            },
            'directories_exist': dirs_exist,
            'files': files,
            'test_url': attachment_url,
            'routes': {
                'get_attachments': url_for('mission.mission_attachments', mission_id=mission_id, _external=True),
                'upload_attachment': url_for('mission.upload_single_attachment', mission_id=mission_id, _external=True)
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error in test_mission_attachments: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}',
            'traceback': traceback.format_exc()
        }), 500 

@mission_bp.route('/mission/<mission_id>/upload_to_api/<attachment_id>', methods=['POST'])
def upload_to_api(mission_id, attachment_id):
    """Upload a local attachment to the Synack API."""
    try:
        current_app.logger.info(f"Uploading attachment {attachment_id} to API for mission {mission_id}")
        
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            current_app.logger.error(f"Mission with ID {mission_id} not found")
            return jsonify({"success": False, "message": "Mission not found"}), 404
        
        # Get listing codename for directory structure
        listing_codename = mission.get('listingCodename', 'unknown')
        
        # Create path to attachments directory
        attachments_dir, metadata_dir = get_attachment_dirs(current_app.config["UPLOAD_FOLDER"], listing_codename, mission_id)
        
        # Check if directories exist
        if not os.path.exists(attachments_dir):
            current_app.logger.error(f"Attachments directory not found: {attachments_dir}")
            return jsonify({'success': False, 'message': 'Attachments directory not found'}), 404
        
        # Find the file based on the attachment_id
        attachment_file = None
        metadata_file = None
        
        # Look for the file in different ways
        for filename in os.listdir(attachments_dir):
            file_path = os.path.join(attachments_dir, filename)
            if not os.path.isfile(file_path) or filename.startswith('temp_'):
                continue
                
            # Check if filename starts with attachment_id
            if filename.startswith(f"{attachment_id}_"):
                attachment_file = filename
                metadata_file = os.path.join(metadata_dir, f"{filename}.json")
                break
                
            # Check if filename exactly matches attachment_id (without extension)
            base_name = os.path.splitext(filename)[0]
            if base_name == attachment_id:
                attachment_file = filename
                metadata_file = os.path.join(metadata_dir, f"{filename}.json")
                break
            
            # Check metadata file for this attachment_id
            potential_metadata = os.path.join(metadata_dir, f"{filename}.json")
            if os.path.exists(potential_metadata):
                try:
                    with open(potential_metadata, 'r') as f:
                        metadata = json.load(f)
                    if metadata.get('id') == attachment_id:
                        attachment_file = filename
                        metadata_file = potential_metadata
                        break
                except Exception as e:
                    current_app.logger.error(f"Error reading metadata for {filename}: {e}")
        
        if not attachment_file or not os.path.exists(os.path.join(attachments_dir, attachment_file)):
            current_app.logger.error(f"Attachment file not found for ID {attachment_id}")
            return jsonify({'success': False, 'message': 'Attachment file not found'}), 404
        
        # Load metadata if it exists
        metadata = {}
        if metadata_file and os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
            except Exception as e:
                current_app.logger.error(f"Error reading metadata: {e}")
                return jsonify({'success': False, 'message': f'Error reading metadata: {str(e)}'}), 500
        
        # Check if already uploaded to API
        if metadata.get('uploaded_to_api'):
            current_app.logger.info(f"Attachment {attachment_id} already uploaded to API with Synack ID: {metadata.get('synack_id')}")
            return jsonify({
                'success': True, 
                'message': 'Attachment already uploaded to API',
                'synack_id': metadata.get('synack_id'),
                'already_uploaded': True
            })
        
        # Get file content
        file_path = os.path.join(attachments_dir, attachment_file)
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Get authentication token from file configured in Flask app
        token_file = current_app.config.get('TOKEN_FILE')
        token = None
        if token_file and os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token = f.read().strip()
        
        if not token:
            current_app.logger.error("No authentication token available")
            return jsonify({'success': False, 'message': 'No authentication token available'}), 401
        
        # Get mission UID components
        organization_uid = mission.get('organizationUid')
        listing_uid = mission.get('listingUid')
        campaign_uid = mission.get('campaignUid')
        
        if not all([organization_uid, listing_uid, campaign_uid]):
            current_app.logger.error("Missing mission UID components")
            return jsonify({'success': False, 'message': 'Missing mission UID components'}), 400
        
        # API endpoint
        api_url = (
            f"{PLATFORM_BASE_URL}/api/tasks/v1/organizations/{organization_uid}/"
            f"listings/{listing_uid}/campaigns/{campaign_uid}/tasks/{mission_id}/attachments"
        )
        
        # Create multipart/form-data payload
        original_filename = metadata.get('original_filename', attachment_file)
        title = metadata.get('title', os.path.splitext(original_filename)[0])
        description = metadata.get('description', '')
        content_type = metadata.get('content_type', 'application/octet-stream')
        
        form_data = MultipartEncoder(
            fields={
                'metadata': json.dumps({
                    'title': title,
                    'description': description
                }),
                'file': (original_filename, file_content, content_type)
            }
        )
        
        # Request headers
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': form_data.content_type
        }
        
        # Make API request
        current_app.logger.info(f"Making API request to {api_url}")
        
        response = requests.post(api_url, headers=headers, data=form_data)
        
        if response.status_code not in [200, 201]:
            current_app.logger.error(f"API request failed: {response.status_code} - {response.text}")
            return jsonify({
                'success': False, 
                'message': f'API request failed with status {response.status_code}',
                'response': response.text
            }), 500
        
        # Process response
        api_response = response.json()
        synack_id = None
        
        # Handle both list and dictionary response formats
        if isinstance(api_response, dict) and 'id' in api_response:
            synack_id = api_response['id']
        elif isinstance(api_response, list) and len(api_response) > 0 and isinstance(api_response[0], dict):
            # If response is a list, take the first item's ID
            synack_id = api_response[0].get('id')
        
        if not synack_id:
            current_app.logger.error(f"No Synack ID in API response: {api_response}")
            return jsonify({'success': False, 'message': 'No Synack ID in API response'}), 500
        
        # Update metadata
        metadata['synack_id'] = synack_id
        metadata['uploaded_to_api'] = True
        metadata['upload_api_time'] = datetime.now().isoformat()
        
        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=4)
        
        # Rename the file to include the Synack ID if it doesn't already
        if not attachment_file.startswith(f"{synack_id}_"):
            # Get base filename without any potential previous ID
            parts = attachment_file.split('_', 1)
            base_filename = parts[1] if len(parts) > 1 else attachment_file
            
            # Create new filename with Synack ID
            new_filename = f"{synack_id}_{base_filename}"
            new_file_path = os.path.join(attachments_dir, new_filename)
            
            # Rename file
            try:
                os.rename(file_path, new_file_path)
                current_app.logger.info(f"Renamed file from {attachment_file} to {new_filename}")
                
                # Rename metadata file
                new_metadata_path = os.path.join(metadata_dir, f"{new_filename}.json")
                os.rename(metadata_file, new_metadata_path)
                
                # Update file reference in metadata
                metadata['filename'] = new_filename
                with open(new_metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=4)
                
                # Update references for response
                attachment_file = new_filename
                file_path = new_file_path
                metadata_file = new_metadata_path
            except Exception as e:
                current_app.logger.error(f"Error renaming file: {e}")
                # Not critical, continue with original filename
        
        current_app.logger.info(f"Successfully uploaded attachment {attachment_id} to API with Synack ID {synack_id}")
        
        return jsonify({
            'success': True,
            'message': 'Attachment successfully uploaded to API',
            'synack_id': synack_id,
            'attachment_id': attachment_id,
            'filename': attachment_file,
            'api_response': api_response
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in upload_to_api: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Error uploading to API: {str(e)}'}), 500

@mission_bp.route('/upload_attachments', methods=['POST'])
def upload_attachments():
    """Upload multiple attachments for a mission."""
    try:
        # Get mission ID from form data
        mission_id = request.form.get('mission_id')
        if not mission_id:
            current_app.logger.error("Mission ID not provided")
            return jsonify({"success": False, "message": "Mission ID is required"}), 400
        
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            current_app.logger.error(f"Mission with ID {mission_id} not found")
            return jsonify({"success": False, "message": "Mission not found"}), 404
        
        # Get listing codename for directory structure
        listing_codename = mission.get('listingCodename', 'unknown')
        
        # Get form data
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        
        # Get uploaded files
        files = request.files.getlist('file')
        if not files or not any(file.filename for file in files):
            current_app.logger.error("No files uploaded")
            return jsonify({"success": False, "message": "No files uploaded"}), 400
        
        # Create directory structure
        attachments_dir, metadata_dir = get_attachment_dirs(current_app.config["UPLOAD_FOLDER"], listing_codename, mission_id)
        
        # Ensure directories exist
        os.makedirs(attachments_dir, exist_ok=True)
        os.makedirs(metadata_dir, exist_ok=True)
        
        current_app.logger.info(f"Uploading {len(files)} files to {attachments_dir}")
        
        uploaded_files = []
        
        for file in files:
            if file.filename:
                try:
                    # Generate unique ID for this attachment
                    attachment_id = str(uuid.uuid4())
                    
                    # Secure filename
                    original_filename = secure_filename(file.filename)
                    filename = f"{attachment_id}_{original_filename}"
                    
                    # Save file
                    file_path = os.path.join(attachments_dir, filename)
                    file.save(file_path)
                    
                    # Create metadata
                    metadata = {
                        'id': attachment_id,
                        'original_filename': original_filename,
                        'filename': filename,
                        'title': title or os.path.splitext(original_filename)[0],
                        'description': description,
                        'content_type': file.content_type or 'application/octet-stream',
                        'size': os.path.getsize(file_path),
                        'upload_time': datetime.now().isoformat(),
                        'uploaded_to_api': False
                    }
                    
                    # Save metadata
                    metadata_path = os.path.join(metadata_dir, f"{filename}.json")
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=4)
                    
                    uploaded_files.append({
                        'id': attachment_id,
                        'filename': filename,
                        'original_filename': original_filename,
                        'title': metadata['title'],
                        'size': metadata['size'],
                        'metadata_path': metadata_path,
                        'file_path': file_path,
                        'content_type': metadata['content_type']
                    })

                    current_app.logger.info(f"Successfully uploaded file locally: {filename}")

                except Exception as e:
                    current_app.logger.error(f"Error uploading file {file.filename}: {str(e)}")
                    return jsonify({"success": False, "message": f"Error uploading file {file.filename}: {str(e)}"}), 500

        # After local upload, send a single multi-upload request to the API
        try:
            success, message, api_results = upload_multiple_attachments_to_api(
                mission_id, uploaded_files, mission, attachments_dir, metadata_dir, title, description
            )
            if not success:
                current_app.logger.error(f"API multi-upload failed: {message}")
                for u in uploaded_files:
                    try:
                        if os.path.exists(u['file_path']):
                            os.remove(u['file_path'])
                        if os.path.exists(u['metadata_path']):
                            os.remove(u['metadata_path'])
                    except Exception:
                        pass
                return jsonify({
                    "success": False,
                    "message": f"Failed to upload files to Synack API: {message}",
                    "api_error": True,
                    "error_type": "api_upload_failed"
                }), 500

            # Update local metadata with returned Synack IDs
            for api_item, local_item in zip(api_results, uploaded_files):
                synack_id = api_item.get('id')
                if not synack_id:
                    continue
                metadata_path = local_item['metadata_path']
                try:
                    with open(metadata_path, 'r') as f:
                        meta = json.load(f)
                    meta['synack_id'] = synack_id
                    meta['uploaded_to_api'] = True
                    meta['upload_api_time'] = datetime.now().isoformat()
                    with open(metadata_path, 'w') as f:
                        json.dump(meta, f, indent=4)

                    if not local_item['filename'].startswith(f"{synack_id}_"):
                        base_filename = local_item['filename'].split('_', 1)[1] if '_' in local_item['filename'] else local_item['filename']
                        new_filename = f"{synack_id}_{base_filename}"
                        new_file_path = os.path.join(attachments_dir, new_filename)
                        os.rename(local_item['file_path'], new_file_path)
                        new_metadata_path = os.path.join(metadata_dir, f"{new_filename}.json")
                        os.rename(metadata_path, new_metadata_path)
                        meta['filename'] = new_filename
                        with open(new_metadata_path, 'w') as f:
                            json.dump(meta, f, indent=4)
                        local_item['filename'] = new_filename
                        local_item['metadata_path'] = new_metadata_path
                        local_item['file_path'] = new_file_path
                except Exception as update_err:
                    current_app.logger.error(f"Error updating metadata for {local_item['filename']}: {update_err}")

            for idx, api_item in enumerate(api_results):
                uploaded_files[idx]['synack_id'] = api_item.get('id')

        except Exception as api_exc:
            current_app.logger.error(f"Error during API multi-upload: {api_exc}")
            return jsonify({"success": False, "message": f"Error uploading to API: {api_exc}"}), 500

        current_app.logger.info(f"Successfully uploaded {len(uploaded_files)} files")

        return jsonify({
            "success": True,
            "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
            "files": uploaded_files
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in upload_attachments: {str(e)}")
        return jsonify({"success": False, "message": f"Upload failed: {str(e)}"}), 500

@mission_bp.route('/mission/<mission_id>/upload_attachment', methods=['POST'])
def upload_single_attachment(mission_id):
    """Upload a single attachment for a mission - alias for upload_attachments endpoint."""
    # This function now works by calling the same logic as upload_attachments
    # but using the mission_id from the URL parameter
    try:
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            current_app.logger.error(f"Mission with ID {mission_id} not found")
            return jsonify({"success": False, "message": "Mission not found"}), 404
        
        # Get listing codename for directory structure
        listing_codename = mission.get('listingCodename', 'unknown')
        
        # Get form data
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        
        # Get uploaded files
        files = request.files.getlist('file')
        if not files or not any(file.filename for file in files):
            current_app.logger.error("No files uploaded")
            return jsonify({"success": False, "message": "No files uploaded"}), 400
        
        # Create directory structure
        attachments_dir, metadata_dir = get_attachment_dirs(current_app.config["UPLOAD_FOLDER"], listing_codename, mission_id)
        
        # Ensure directories exist
        os.makedirs(attachments_dir, exist_ok=True)
        os.makedirs(metadata_dir, exist_ok=True)
        
        current_app.logger.info(f"Uploading {len(files)} files to {attachments_dir}")
        
        uploaded_files = []
        
        for file in files:
            if file.filename:
                try:
                    # Generate unique ID for this attachment
                    attachment_id = str(uuid.uuid4())
                    
                    # Secure filename
                    original_filename = secure_filename(file.filename)
                    filename = f"{attachment_id}_{original_filename}"
                    
                    # Save file
                    file_path = os.path.join(attachments_dir, filename)
                    file.save(file_path)
                    
                    # Create metadata
                    metadata = {
                        'id': attachment_id,
                        'original_filename': original_filename,
                        'filename': filename,
                        'title': title or os.path.splitext(original_filename)[0],
                        'description': description,
                        'content_type': file.content_type or 'application/octet-stream',
                        'size': os.path.getsize(file_path),
                        'upload_time': datetime.now().isoformat(),
                        'uploaded_to_api': False
                    }
                    
                    # Save metadata
                    metadata_path = os.path.join(metadata_dir, f"{filename}.json")
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=4)
                    
                    uploaded_files.append({
                        'id': attachment_id,
                        'filename': filename,
                        'original_filename': original_filename,
                        'title': metadata['title'],
                        'size': metadata['size']
                    })
                    
                    current_app.logger.info(f"Successfully uploaded file locally: {filename}")

                except Exception as e:
                    current_app.logger.error(f"Error uploading file {file.filename}: {str(e)}")
                    return jsonify({"success": False, "message": f"Error uploading file {file.filename}: {str(e)}"}), 500

        # After local upload, send a single multi-upload request to the API
        try:
            success, message, api_results = upload_multiple_attachments_to_api(
                mission_id, uploaded_files, mission, attachments_dir, metadata_dir, title, description
            )
            if not success:
                current_app.logger.error(f"API multi-upload failed: {message}")
                for u in uploaded_files:
                    try:
                        if os.path.exists(u['file_path']):
                            os.remove(u['file_path'])
                        if os.path.exists(u['metadata_path']):
                            os.remove(u['metadata_path'])
                    except Exception:
                        pass
                return jsonify({
                    "success": False,
                    "message": f"Failed to upload files to Synack API: {message}",
                    "api_error": True,
                    "error_type": "api_upload_failed"
                }), 500

            for api_item, local_item in zip(api_results, uploaded_files):
                synack_id = api_item.get('id')
                if not synack_id:
                    continue
                metadata_path = local_item['metadata_path']
                try:
                    with open(metadata_path, 'r') as f:
                        meta = json.load(f)
                    meta['synack_id'] = synack_id
                    meta['uploaded_to_api'] = True
                    meta['upload_api_time'] = datetime.now().isoformat()
                    with open(metadata_path, 'w') as f:
                        json.dump(meta, f, indent=4)

                    if not local_item['filename'].startswith(f"{synack_id}_"):
                        base_filename = local_item['filename'].split('_', 1)[1] if '_' in local_item['filename'] else local_item['filename']
                        new_filename = f"{synack_id}_{base_filename}"
                        new_file_path = os.path.join(attachments_dir, new_filename)
                        os.rename(local_item['file_path'], new_file_path)
                        new_metadata_path = os.path.join(metadata_dir, f"{new_filename}.json")
                        os.rename(metadata_path, new_metadata_path)
                        meta['filename'] = new_filename
                        with open(new_metadata_path, 'w') as f:
                            json.dump(meta, f, indent=4)
                        local_item['filename'] = new_filename
                        local_item['metadata_path'] = new_metadata_path
                        local_item['file_path'] = new_file_path
                except Exception as update_err:
                    current_app.logger.error(f"Error updating metadata for {local_item['filename']}: {update_err}")

            for idx, api_item in enumerate(api_results):
                uploaded_files[idx]['synack_id'] = api_item.get('id')

        except Exception as api_exc:
            current_app.logger.error(f"Error during API multi-upload: {api_exc}")
            return jsonify({"success": False, "message": f"Error uploading to API: {api_exc}"}), 500

        current_app.logger.info(f"Successfully uploaded {len(uploaded_files)} files")

        return jsonify({
            "success": True,
            "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
            "files": uploaded_files
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in upload_single_attachment: {str(e)}")
        return jsonify({"success": False, "message": f"Upload failed: {str(e)}"}), 500

@mission_bp.route('/mission/<mission_id>/download_attachment/<attachment_id>', methods=['GET'])
def download_attachment(mission_id, attachment_id):
    """Download an attachment file."""
    try:
        current_app.logger.info(f"Download request for attachment {attachment_id} in mission {mission_id}")
        
        # Get mission details
        mission = get_mission_by_id(mission_id)
        if not mission:
            current_app.logger.error(f"Mission with ID {mission_id} not found")
            return jsonify({"success": False, "message": "Mission not found"}), 404
        # Get listing codename for directory structure
        listing_codename = mission.get('listingCodename', 'unknown')
        
        attachments_dir, metadata_dir = get_attachment_dirs(current_app.config["UPLOAD_FOLDER"], listing_codename, mission_id)
        
        # Check if directories exist
        if not os.path.exists(attachments_dir):
            current_app.logger.error(f"Attachments directory not found: {attachments_dir}")
            return jsonify({'success': False, 'message': 'Attachments directory not found'}), 404
        
        # Search for the file based on attachment_id
        current_app.logger.info(f"Searching for attachment with ID: {attachment_id}")
        
        # First, try to find by filename starting with attachment_id
        matching_files = []
        
        # Look for files with matching attachment ID pattern
        for filename in os.listdir(attachments_dir):
            file_path = os.path.join(attachments_dir, filename)
            if os.path.isfile(file_path) and not filename.startswith('temp_'):
                # Check if filename starts with the attachment ID (for files named with Synack ID pattern)
                if filename.startswith(attachment_id + '_'):
                    current_app.logger.info(f"Found matching file by prefix: {filename}")
                    matching_files.append(filename)
                    break
                
                # Check if the attachment ID matches the filename without extension
                if os.path.splitext(filename)[0] == attachment_id:
                    current_app.logger.info(f"Found matching file by name: {filename}")
                    matching_files.append(filename)
                    break
                
                # Check metadata for Synack ID
                metadata_file = os.path.join(metadata_dir, f"{filename}.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            synack_id = metadata.get('synack_id')
                            if synack_id == attachment_id:
                                current_app.logger.info(f"Found matching file by Synack ID in metadata: {filename}")
                                matching_files.append(filename)
                                break
                    except Exception as e:
                        current_app.logger.error(f"Error reading metadata for {filename}: {str(e)}")
        
        if not matching_files:
            current_app.logger.error(f"No attachment found with ID: {attachment_id}")
            return jsonify({'success': False, 'message': 'Attachment not found'}), 404
        
        # Use the first matching file
        filename = matching_files[0]
        file_path = os.path.join(attachments_dir, filename)
        
        # Get file metadata if available
        metadata = {}
        metadata_path = os.path.join(metadata_dir, f"{filename}.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
            except Exception as e:
                current_app.logger.error(f"Error reading metadata: {str(e)}")
        
        # Determine content type
        content_type = metadata.get('content_type') or 'application/octet-stream'
        
        # Get display filename (original if available)
        display_filename = metadata.get('original_filename') or filename
        
        current_app.logger.info(f"Serving file: {file_path} as {display_filename}")
        
        # Send file with proper filename and content type
        return send_file(
            file_path,
            as_attachment=True,
            download_name=display_filename,
            mimetype=content_type
        )
    
    except Exception as e:
        current_app.logger.error(f"Error in download_attachment: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Error downloading attachment: {str(e)}'}), 500 

@mission_bp.route('/get_default_templates')
def get_default_templates_route():
    """
    Get a list of available default templates from the text_templates/default directory.
    """
    try:
        from utils.template_utils import get_default_templates
        
        # Get app root for absolute paths
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Get templates from the utility function
        templates = get_default_templates(app_root=app_root, user_templates_dir=current_app.config.get('USER_TEMPLATES_DIR'))

        # Log the templates for debugging
        for template in templates:
            logger.info(f"Default template: {template}")

        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        logger.error(f"Error getting default templates: {e}")
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'})

@mission_bp.route('/load_default_template', methods=['POST'])
def load_default_template():
    """Load a default template."""
    from utils.template_utils import parse_template
    
    try:
        data = request.get_json()
        template_path = data.get('template_name')
        
        logger.info(f"Loading default template from path: {template_path}")
        
        if not template_path:
            return jsonify({"success": False, "message": "Template path is required."}), 400
        
        # Get app root for absolute paths
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # Handle different path formats with secure path validation
        final_template_path = None
        
        # Define allowed template directories (user dir first, then app dir)
        user_default_dir = None
        try:
            utd = current_app.config.get('USER_TEMPLATES_DIR')
            if utd:
                user_default_dir = os.path.normpath(os.path.join(utd, 'default'))
        except Exception:
            user_default_dir = None
        app_default_dir = os.path.normpath(os.path.join(app_root, 'text_templates', 'default'))
        
        # Check if it's already an absolute path
        if os.path.isabs(template_path):
            # For absolute paths, validate they're within one of the allowed directories
            normalized_template_path = os.path.normpath(template_path)
            try:
                allowed_dirs = [d for d in [user_default_dir, app_default_dir] if d]
                in_allowed = False
                for d in allowed_dirs:
                    try:
                        if os.path.commonpath([normalized_template_path, d]) == d:
                            in_allowed = True
                            break
                    except ValueError:
                        continue
                if in_allowed:
                    final_template_path = normalized_template_path
                else:
                    return jsonify({"success": False, "message": "Invalid template path - absolute path must be within allowed default templates directory."}), 400
            except ValueError:
                # commonpath raises ValueError if paths are on different drives (Windows)
                return jsonify({"success": False, "message": "Invalid template path - absolute path must be within allowed default templates directory."}), 400
        elif template_path.startswith('text_templates/default/') or template_path.startswith('text_templates\\default\\'):
            # Convert relative path to absolute path and validate
            final_template_path = os.path.normpath(os.path.join(app_root, template_path))
            try:
                common_path = os.path.commonpath([final_template_path, app_default_dir])
                if common_path != app_default_dir:
                    return jsonify({"success": False, "message": "Invalid template path - path must be within text_templates/default directory."}), 400
            except ValueError:
                return jsonify({"success": False, "message": "Invalid template path - path must be within text_templates/default directory."}), 400
        elif os.path.sep not in template_path and '/' not in template_path:
            # If only a filename is provided, add the default directory path
            # Prefer user default dir if available
            base_dir = user_default_dir or app_default_dir
            final_template_path = os.path.join(base_dir, template_path)
        else:
            return jsonify({"success": False, "message": "Invalid template path format."}), 400
        
        # Double-check that the resolved path exists
        if not os.path.exists(final_template_path):
            # If the absolute path doesn't exist, try to find it in the local workspace
            filename = os.path.basename(final_template_path)
            local_template_path = os.path.join(app_root, 'text_templates', 'default', filename)
            if user_default_dir:
                user_candidate = os.path.join(user_default_dir, filename)
                if os.path.exists(user_candidate):
                    final_template_path = user_candidate
                    logger.info(f"Using user template path: {final_template_path}")
                elif os.path.exists(local_template_path):
                    final_template_path = local_template_path
                    logger.info(f"Using local template path: {final_template_path}")
                else:
                    return jsonify({"success": False, "message": "Template not found."}), 404
            else:
                if os.path.exists(local_template_path):
                    final_template_path = local_template_path
                    logger.info(f"Using local template path: {final_template_path}")
                else:
                    return jsonify({"success": False, "message": "Template not found."}), 404
        
        logger.info(f"Loading template from resolved path: {final_template_path}")
        
        with open(final_template_path, 'r') as file:
            template_content = file.read()
            
        sections = parse_template(template_content)
        scripts = sections.get('scripts', [])
        
        return jsonify({"success": True, "sections": sections, "scripts": scripts})
    except Exception as e:
        logger.error(f"Error loading default template: {e}")
        return jsonify({"success": False, "message": f"Failed to load template: {str(e)}"}), 500

@mission_bp.route('/generate_ai_template/<path:mission_id>', methods=['POST'])
def generate_ai_template_route(mission_id):
    """Generate a mission template using Google AI."""
    from utils.template_utils import parse_template, determine_category
    from utils.ai_generator import generate_template, detect_network_indicators
    try:
        ai_key = CONFIG.get('ai_key')
        ai_model = CONFIG.get('ai_model')
        if not ai_key or not ai_model:
            return jsonify({'success': False, 'message': 'AI not configured'}), 400

        mission = get_mission_by_id(mission_id)
        if not mission:
            return jsonify({'success': False, 'message': 'Mission not found'}), 404

        # Optional JSON body for consent and automask
        payload = {}
        try:
            payload = request.get_json(force=False, silent=True) or {}
        except Exception:
            payload = {}
        consent = bool(payload.get('consent'))
        automask = bool(payload.get('automask'))

        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompt_path = os.path.join(app_root, 'utils', 'prompt.md')
        with open(prompt_path, 'r') as f:
            prompt_text = f.read()

        # Build mission_details but exclude scope from being sent
        mission_details = f"Mission Title: {mission.get('title','')}\nMission Description: {mission.get('description','')}"

        # Safety: detect hostnames/IPs in mission details; require UI confirmation
        found, host_ct, ip_ct, hosts, ips = detect_network_indicators(mission_details)
        if found and not consent:
            return jsonify({
                'success': False,
                'message': f'Network indicators detected in mission details (hosts: {host_ct}, IPs: {ip_ct}). Confirm before sending to AI.',
                'needs_user_consent': True,
                'host_count': host_ct,
                'ip_count': ip_ct,
                'hosts': hosts,
                'ips': ips
            }), 400

        # Apply automask if requested
        if automask and found:
            try:
                masked = mission_details
                for idx, h in enumerate(hosts or []):
                    repl = 'example.com' if idx == 0 else f'example{idx+1}.com'
                    masked = masked.replace(h, repl)
                for ip in ips or []:
                    masked = masked.replace(ip, '192.0.2.1')
                mission_details = masked
            except Exception:
                pass

        # Prompt text
        enhanced_prompt = prompt_text

        ai_output = generate_template(enhanced_prompt, mission_details)

        sections = parse_template(ai_output)
        if not sections.get('introduction') or not sections.get('testing'):
            return jsonify({'success': False, 'message': 'Generated template missing required sections'}), 400

        category = determine_category(mission.get('assetTypes', []))

        working_folder = get_working_folder()
        listing_codename = mission.get('listingCodename', 'unknown')
        safe_title = mission.get('title', '').replace(' ', '_').replace('/', '_').lower()
        directory = os.path.join(working_folder, listing_codename)
        os.makedirs(directory, exist_ok=True)
        template_path = os.path.join(directory, f"{safe_title}.txt")
        with open(template_path, 'w') as f:
            f.write(ai_output)

        formatted = {
            'introduction': sections.get('introduction', ''),
            'testing_methodology': sections.get('testing', ''),
            'documentation': sections.get('documentation', ''),
            'conclusion-pass': sections.get('conclusion-pass', ''),
            'conclusion-fail': sections.get('conclusion-fail', ''),
            'conclusion_type': 'pass',
            'scripts': sections.get('scripts', [])
        }

        return jsonify({'success': True, 'sections': formatted, 'category': category})
    except Exception as e:
        logger.error(f"Error generating template: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@mission_bp.route('/get_tools')
def get_tools_route():
    """Return list of available tool names."""
    try:
        from utils.tool_utils import load_tools
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = load_tools(app_root, current_app.config.get('USER_TEMPLATES_DIR'))
        return jsonify({'success': True, 'tools': list(tools.keys())})
    except Exception as e:
        logger.error(f"Error loading tools: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@mission_bp.route('/ai/rewrite', methods=['POST'])
def ai_rewrite_route():
    """Rewrite a selected text block per instruction, with safety checks."""
    try:
        data = request.get_json() or {}
        instruction = data.get('instruction', '').strip()
        selected_text = data.get('selected_text', '').strip()
        # references and reference URL removed per requirements
        mission_id = data.get('mission_id')

        if not instruction or not selected_text:
            return jsonify({'success': False, 'message': 'instruction and selected_text are required'}), 400

        # Ensure we do not send scope
        mission = get_mission_by_id(mission_id) if mission_id else None
        scope = mission.get('scope') if mission else None
        safe_text = strip_scope(selected_text, scope)

        # Detect network indicators in the text and ask consent
        found, host_ct, ip_ct, hosts, ips = detect_network_indicators(safe_text)
        if found and not data.get('consent'):
            return jsonify({
                'success': False,
                'needs_user_consent': True,
                'message': 'Network indicators detected. Confirm before sending to AI.',
                'host_count': host_ct,
                'ip_count': ip_ct,
                'hosts': hosts,
                'ips': ips
            }), 400

        # Optional automask: replace hosts with example.com/example2.com and mask IPs
        if data.get('automask'):
            try:
                masked_text = safe_text
                for idx, h in enumerate(hosts):
                    repl = 'example.com' if idx == 0 else f'example{idx+1}.com'
                    masked_text = masked_text.replace(h, repl)
                for ip in ips:
                    masked_text = masked_text.replace(ip, '192.0.2.1')
                safe_text = masked_text
            except Exception:
                pass

        full_instruction = instruction
        result = rewrite_text(full_instruction, safe_text)
        return jsonify({'success': True, 'text': result})
    except Exception as e:
        current_app.logger.error(f"AI rewrite error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@mission_bp.route('/config', methods=['GET', 'POST'])
def config_page():
    """Simple config editor: view/update CONFIG via UI."""
    try:
        config_path = os.path.join(current_app.config.get('APP_ROOT'), 'config.json')
        if request.method == 'POST':
            data = request.get_json() or {}
            allowed_keys = {'platform', 'working_folder', 'token_file', 'ai_key', 'ai_model', 'user_templates_dir'}

            # Validate
            errors = {}
            platform = (data.get('platform') or '').strip()
            if platform and not (platform.startswith('http://') or platform.startswith('https://')):
                errors['platform'] = 'Platform must start with http:// or https://'
            working_folder = (data.get('working_folder') or '').strip()
            if not working_folder:
                errors['working_folder'] = 'Working folder is required'
            token_file = (data.get('token_file') or '').strip()
            if not token_file:
                errors['token_file'] = 'Token file path is required'
            ai_model = (data.get('ai_model') or '').strip()
            ai_key = data.get('ai_key')
            if ai_key is not None and not str(ai_key).strip():
                errors['ai_key'] = 'AI key cannot be blank when provided'
            if errors:
                return jsonify({'success': False, 'message': 'Validation failed', 'errors': errors}), 400

            # Load existing to preserve unknown keys
            current_cfg = {}
            if os.path.exists(config_path):
                with open(config_path) as f:
                    try:
                        current_cfg = json.load(f) or {}
                    except Exception:
                        current_cfg = {}

            # Ensure folders exist
            try:
                os.makedirs(working_folder, exist_ok=True)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Invalid working_folder: {e}'}), 400
            try:
                token_dir = os.path.dirname(token_file) or '.'
                os.makedirs(token_dir, exist_ok=True)
            except Exception as e:
                return jsonify({'success': False, 'message': f'Invalid token_file directory: {e}'}), 400

            # Merge allowed
            for k, v in data.items():
                if k in allowed_keys:
                    if k == 'ai_key' and v is None:
                        continue
                    current_cfg[k] = v

            # Normalize and scaffold user_templates_dir
            utd = (data.get('user_templates_dir') or '').strip()
            if utd:
                try:
                    utd_norm = os.path.expanduser(utd)
                    utd_abs = utd_norm if os.path.isabs(utd_norm) else os.path.abspath(utd_norm)
                    os.makedirs(utd_abs, exist_ok=True)
                    for p in [
                        os.path.join(utd_abs, 'default'),
                        os.path.join(utd_abs, 'web'),
                        os.path.join(utd_abs, 'host'),
                        os.path.join(utd_abs, 'ai_prompts', 'global'),
                        os.path.join(utd_abs, 'tools'),
                    ]:
                        os.makedirs(p, exist_ok=True)
                    current_cfg['user_templates_dir'] = utd_abs
                except Exception as e:
                    return jsonify({'success': False, 'message': f'Invalid user_templates_dir: {e}'}), 400

            # Write back
            with open(config_path, 'w') as f:
                json.dump(current_cfg, f, indent=2)

            # Refresh runtime config
            from utils.config import load_config
            new_cfg = load_config()
            current_app.config['WORKING_FOLDER'] = new_cfg.get('working_folder', 'data')
            current_app.config['TOKEN_FILE'] = new_cfg.get('token_file', '/tmp/synacktoken')
            current_app.config['PLATFORM'] = new_cfg.get('platform', 'https://platform.synack.com')
            current_app.config['USER_TEMPLATES_DIR'] = new_cfg.get('user_templates_dir')
            return jsonify({'success': True})

        # GET: read fresh from disk, then prefer in-memory for values set at runtime
        from utils.config import load_config
        cfg_now = load_config()
        cfg_now['working_folder'] = current_app.config.get('WORKING_FOLDER', cfg_now.get('working_folder'))
        cfg_now['token_file'] = current_app.config.get('TOKEN_FILE', cfg_now.get('token_file'))
        cfg_now['platform'] = current_app.config.get('PLATFORM', cfg_now.get('platform'))
        cfg_now['user_templates_dir'] = current_app.config.get('USER_TEMPLATES_DIR', cfg_now.get('user_templates_dir'))
        safe = {k: cfg_now.get(k) for k in ['platform', 'working_folder', 'token_file', 'ai_model', 'user_templates_dir']}
        safe['ai_key'] = cfg_now.get('ai_key') or ''
        return jsonify({'success': True, 'config': safe})
    except Exception as e:
        current_app.logger.error(f"Config page error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@mission_bp.route('/config/edit')
def render_config_page():
    """Render the config editor page."""
    return render_template('config_edit.html')

@mission_bp.route('/fs/list')
def fs_list():
    """Return a simple listing of directories for the client-side directory browser.
    Only lists subdirectories of the provided path and does not expose file contents.
    """
    try:
        path = request.args.get('path', '/')
        # Normalize path to prevent traversal oddities
        path = os.path.abspath(path)
        # If path doesn't exist or isn't a directory, try fallback to root
        if not os.path.isdir(path):
            return jsonify({'success': False, 'message': 'Not a directory'}), 400

        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            # Only show directories
            if os.path.isdir(full) and not name.startswith('.'):
                entries.append({'name': name, 'path': full})
        return jsonify({'success': True, 'path': path, 'entries': entries})
    except PermissionError:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    except Exception as e:
        current_app.logger.error(f"fs_list error: {e}")
        return jsonify({'success': False, 'message': 'Failed to list directory'}), 500

@mission_bp.route('/ai/prompts', methods=['GET'])
def list_ai_prompts():
    """List AI prompt presets from text_templates/ai_prompts.

    Structure and precedence:
    - Section-specific presets are loaded from text_templates/ai_prompts/<section> (if section is provided), recursively.
    - Global presets are loaded from text_templates/ai_prompts/global, recursively.
    - Section presets appear first, then global. Within each, directory structure and lexicographic names are preserved
      to allow authors to control ordering via folder/file names (e.g., 00-Intro/, 10-Style/).
    """
    try:
        section = (request.args.get('section') or '').strip()
        user_base = None
        try:
            user_base = os.path.join(current_app.config.get('USER_TEMPLATES_DIR') or '', 'ai_prompts')
        except Exception:
            user_base = None
        app_base = os.path.join(current_app.root_path, 'text_templates', 'ai_prompts')

        def collect_from(root_dir, source_label):
            collected = []
            if not root_dir or not os.path.isdir(root_dir):
                return collected
            for dirpath, dirnames, filenames in os.walk(root_dir):
                # Enforce lexicographic and skip hidden dirs/files
                dirnames[:] = sorted([d for d in dirnames if not d.startswith('.')])
                for fname in sorted(f for f in filenames if not f.startswith('.') and f.lower().endswith(('.txt', '.md'))):
                    fpath = os.path.join(dirpath, fname)
                    try:
                        rel = os.path.relpath(fpath, root_dir)
                    except ValueError:
                        rel = fname
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(8192)
                    except Exception:
                        content = ''
                    collected.append({
                        'name': fname,
                        'path': rel.replace('\\', '/'),
                        'display': rel.replace('\\', '/'),
                        'source': source_label,
                        'content': content,
                    })
            return collected

        # Collect and de-duplicate by file name, preferring section versions
        items = []
        seen_names = set()
        # Section-first
        base = user_base if user_base and os.path.isdir(user_base) else app_base
        section_dir = os.path.join(base, section) if section else None
        for it in collect_from(section_dir, 'section'):
            if it['name'] in seen_names:
                continue
            seen_names.add(it['name'])
            items.append(it)
        # Then global
        global_dir = os.path.join(base, 'global')
        for it in collect_from(global_dir, 'global'):
            if it['name'] in seen_names:
                continue
            seen_names.add(it['name'])
            items.append(it)
        return jsonify({'success': True, 'prompts': items})
    except Exception as e:
        current_app.logger.error(f"list_ai_prompts error: {e}")
        return jsonify({'success': False, 'message': 'Failed to list prompts'}), 500

@mission_bp.route('/ai/prompts', methods=['POST'])
def save_ai_prompt():
    """Save a new AI prompt preset under text_templates/ai_prompts/<section>.

    Notes:
    - Saving to nested subdirectories via UI is not supported; authors can organize files manually on disk.
    - Name cannot contain path separators; a .txt extension is added if missing.
    """
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        content = (data.get('content') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400
        if any(ch in name for ch in ('/', '\\', '..')):
            return jsonify({'success': False, 'message': 'Invalid name'}), 400
        if not content:
            return jsonify({'success': False, 'message': 'Content is required'}), 400
        section = (data.get('section') or '').strip()
        user_base = None
        try:
            user_base = os.path.join(current_app.config.get('USER_TEMPLATES_DIR') or '', 'ai_prompts')
        except Exception:
            user_base = None
        base = user_base if user_base else os.path.join(current_app.root_path, 'text_templates', 'ai_prompts')
        folder = os.path.join(base, section) if section else base
        os.makedirs(folder, exist_ok=True)
        # Ensure .txt extension if none provided
        if not os.path.splitext(name)[1]:
            name = name + '.txt'
        path = os.path.join(folder, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"save_ai_prompt error: {e}")
        return jsonify({'success': False, 'message': 'Failed to save prompt'}), 500

@mission_bp.route('/ai/prompts/open', methods=['POST'])
def open_ai_prompts_folder():
    """Open text_templates/ai_prompts (or section subfolder) in Finder on macOS."""
    try:
        import sys
        data = request.get_json() or {}
        section = (data.get('section') or '').strip()
        user_base = None
        try:
            user_base = os.path.join(current_app.config.get('USER_TEMPLATES_DIR') or '', 'ai_prompts')
        except Exception:
            user_base = None
        base = user_base if user_base else os.path.join(current_app.root_path, 'text_templates', 'ai_prompts')
        folder = os.path.join(base, section) if section else base
        os.makedirs(folder, exist_ok=True)
        if sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', folder])
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Open folder is only supported on macOS here'}), 400
    except Exception as e:
        current_app.logger.error(f"open_ai_prompts_folder error: {e}")
        return jsonify({'success': False, 'message': 'Failed to open folder'}), 500

@mission_bp.route('/ai/prompts/delete', methods=['POST'])
def delete_ai_prompt():
    """Delete an AI prompt preset file from text_templates/ai_prompts/<section>."""
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        section = (data.get('section') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400
        user_base = None
        try:
            user_base = os.path.join(current_app.config.get('USER_TEMPLATES_DIR') or '', 'ai_prompts')
        except Exception:
            user_base = None
        base = user_base if user_base else os.path.join(current_app.root_path, 'text_templates', 'ai_prompts')
        folder = os.path.join(base, section) if section else base
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            return jsonify({'success': False, 'message': 'File not found'}), 404
        os.remove(path)
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"delete_ai_prompt error: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete prompt'}), 500

@mission_bp.route('/ai/prompts/rename', methods=['POST'])
def rename_ai_prompt():
    """Rename an AI prompt preset file under text_templates/ai_prompts/<section>."""
    try:
        data = request.get_json() or {}
        old_name = (data.get('old_name') or '').strip()
        new_name = (data.get('new_name') or '').strip()
        section = (data.get('section') or '').strip()
        if not old_name or not new_name:
            return jsonify({'success': False, 'message': 'Both old_name and new_name are required'}), 400
        if any(ch in new_name for ch in ('/', '\\', '..')):
            return jsonify({'success': False, 'message': 'Invalid new_name'}), 400
        user_base = None
        try:
            user_base = os.path.join(current_app.config.get('USER_TEMPLATES_DIR') or '', 'ai_prompts')
        except Exception:
            user_base = None
        base = user_base if user_base else os.path.join(current_app.root_path, 'text_templates', 'ai_prompts')
        folder = os.path.join(base, section) if section else base
        os.makedirs(folder, exist_ok=True)
        if not os.path.splitext(new_name)[1]:
            new_name = new_name + '.txt'
        src = os.path.join(folder, old_name)
        dst = os.path.join(folder, new_name)
        if not os.path.isfile(src):
            return jsonify({'success': False, 'message': 'Source file not found'}), 404
        if os.path.exists(dst):
            return jsonify({'success': False, 'message': 'Destination already exists'}), 400
        os.rename(src, dst)
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"rename_ai_prompt error: {e}")
        return jsonify({'success': False, 'message': 'Failed to rename prompt'}), 500

def _tools_file_path():
    """Resolve the tools.txt path, preferring the user templates directory."""
    app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    user_dir = current_app.config.get('USER_TEMPLATES_DIR')
    if user_dir:
        return os.path.join(user_dir, 'tools', 'tools.txt')
    return os.path.join(app_root, 'text_templates', 'tools', 'tools.txt')

def _serialize_tools(tools_dict):
    parts = []
    for name, content in tools_dict.items():
        parts.append(f"[{name}]\n{content.strip()}\n")
    return "\n".join(parts) + ("\n" if parts else "")

@mission_bp.route('/tools', methods=['GET'])
def list_tools():
    try:
        from utils.tool_utils import load_tools
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = load_tools(app_root, current_app.config.get('USER_TEMPLATES_DIR'))
        return jsonify({'success': True, 'tools': tools})
    except Exception as e:
        current_app.logger.error(f"list_tools error: {e}")
        return jsonify({'success': False, 'message': 'Failed to load tools'}), 500

@mission_bp.route('/tools', methods=['POST'])
def save_tool():
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        content = (data.get('content') or '').strip()
        if not name or not content:
            return jsonify({'success': False, 'message': 'Name and content are required'}), 400
        if any(ch in name for ch in ('/', '\\', '..', '[', ']')):
            return jsonify({'success': False, 'message': 'Invalid name'}), 400
        # Load existing
        from utils.tool_utils import load_tools
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = load_tools(app_root, current_app.config.get('USER_TEMPLATES_DIR'))
        tools[name] = content
        # Serialize and write
        path = _tools_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_serialize_tools(tools))
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"save_tool error: {e}")
        return jsonify({'success': False, 'message': 'Failed to save tool'}), 500

@mission_bp.route('/tools/delete', methods=['POST'])
def delete_tool():
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400
        from utils.tool_utils import load_tools
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = load_tools(app_root, current_app.config.get('USER_TEMPLATES_DIR'))
        if name not in tools:
            return jsonify({'success': False, 'message': 'Tool not found'}), 404
        del tools[name]
        path = _tools_file_path()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_serialize_tools(tools))
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"delete_tool error: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete tool'}), 500

@mission_bp.route('/tools/rename', methods=['POST'])
def rename_tool():
    try:
        data = request.get_json() or {}
        old_name = (data.get('old_name') or '').strip()
        new_name = (data.get('new_name') or '').strip()
        if not old_name or not new_name:
            return jsonify({'success': False, 'message': 'Both old_name and new_name are required'}), 400
        if any(ch in new_name for ch in ('/', '\\', '..', '[', ']')):
            return jsonify({'success': False, 'message': 'Invalid new_name'}), 400
        from utils.tool_utils import load_tools
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = load_tools(app_root, current_app.config.get('USER_TEMPLATES_DIR'))
        if old_name not in tools:
            return jsonify({'success': False, 'message': 'Tool not found'}), 404
        tools[new_name] = tools.pop(old_name)
        path = _tools_file_path()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_serialize_tools(tools))
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"rename_tool error: {e}")
        return jsonify({'success': False, 'message': 'Failed to rename tool'}), 500

@mission_bp.route('/get_tool', methods=['POST'])
def get_tool_route():
    """Return a specific tool definition."""
    try:
        data = request.get_json()
        name = data.get('name')
        from utils.tool_utils import load_tools
        app_root = current_app.config.get('APP_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = load_tools(app_root, current_app.config.get('USER_TEMPLATES_DIR'))
        content = tools.get(name)
        if content is None:
            return jsonify({'success': False, 'message': 'Tool not found'}), 404
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        logger.error(f"Error fetching tool: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@mission_bp.route('/view_script/<category>/<script_name>')
def view_script(category, script_name):
    """
    Serve the script as plain text in the browser.
    """
    # Define the directory where scripts are stored
    scripts_dir = os.path.join(current_app.root_path, 'static', 'scripts', category)
    
    # Log the request
    logger.info(f"Requesting script: Category='{category}', Script Name='{script_name}'")
    
    # Sanitize inputs to prevent directory traversal attacks
    if not os.path.isdir(scripts_dir):
        logger.error(f"Scripts directory does not exist: {scripts_dir}")
        abort(404)  # Directory does not exist
    
    # Ensure script_name does not contain malicious patterns
    if '..' in script_name or '/' in script_name or '\\' in script_name:
        logger.error(f"Malicious script name detected: {script_name}")
        abort(400)  # Bad request
    
    # Full path to the script
    script_path = os.path.join(scripts_dir, script_name)
    
    # Check if the script exists and is a file
    if not os.path.isfile(script_path):
        logger.error(f"Script not found: {script_path}")
        abort(404)  # Script not found
    
    try:
        # Serve the script with 'text/plain' MIME type
        return send_from_directory(
            directory=scripts_dir,
            filename=script_name,
            mimetype='text/plain',
            as_attachment=False  # Ensure it's rendered in the browser
        )
    except Exception as e:
        logger.error(f"Error serving script {script_name}: {e}")
        abort(500)  # Internal Server Error 

@mission_bp.route('/refresh_tasks')
def refresh_tasks():
    """Refresh missions from the API."""
    try:
        logger.info("Refreshing missions from API")
        missions, api_status = force_refresh_missions()
        
        if api_status['success'] and api_status['source'] == 'api':
            # Successfully fetched from API
            return jsonify({
                'success': True, 
                'message': f'Missions refreshed successfully from API', 
                'count': len(missions)
            })
        elif api_status['success'] and api_status['source'] in ['initial_cache', 'memory_cache']:
            # Used cached data but no API call was attempted (not a failure)
            return jsonify({
                'success': True, 
                'message': f'Missions loaded from cache', 
                'count': len(missions)
            })
        else:
            # API call failed, fell back to cache
            error_message = api_status.get('error', 'Unknown error')
            logger.warning(f"API refresh failed: {error_message}, using cached missions")
            return jsonify({
                'success': False, 
                'message': f'Failed to refresh from API: {error_message}. Using cached missions.', 
                'count': len(missions),
                'fallback': True
            })
    except Exception as e:
        logger.error(f"Error refreshing missions: {e}")
        # Check if this is an authentication error
        if "API call failed please check authentication" in str(e):
            return jsonify({'success': False, 'message': 'API call failed please check authentication'}), 401
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}) 