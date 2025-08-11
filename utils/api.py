import os
import json
import requests
import logging
import time
from datetime import datetime
from utils.config import CONFIG

logger = logging.getLogger(__name__)

# Base URL for the Synack platform
PLATFORM_BASE_URL = CONFIG.get("platform", "https://platform.synack.com")

# Common API base URL derived from configuration
API_BASE_URL = f"{PLATFORM_BASE_URL}/api/tasks/v2/tasks"
WORKING_FOLDER = CONFIG.get('working_folder', 'data')
TOKEN_FILE = CONFIG.get('token_file', '/tmp/synacktoken')
CACHE_EXPIRY_SECONDS = 3600  # 1 hour

# Global variable to track last API fetch time
_last_fetch_time = 0
_cached_missions = None
_app_init_time = time.time()  # Track when the app started
_has_loaded_initial = False   # Flag to track if we've done an initial load

def read_auth_token():
    """Read the authentication token from the token file."""
    try:
        with open(TOKEN_FILE, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error(f"Token file not found: {TOKEN_FILE}")
    except IOError as e:
        logger.error(f"Error reading token file: {e}")
    return None

def get_all_missions(force_refresh=False):
    """
    Get all missions with smarter caching behavior.
    
    Args:
        force_refresh: If True, force a refresh from the API regardless of cache
        
    Returns:
        Tuple: (missions_list, api_success_status)
        - missions_list: List of mission objects
        - api_success_status: Dict with 'success' (bool), 'source' (str), and 'error' (str) if applicable
    """
    global _last_fetch_time, _cached_missions, _has_loaded_initial
    
    current_time = time.time()
    
    # Load from tasks.json by default (no API call)
    if not _has_loaded_initial:
        # This is the first time we're getting missions since startup
        missions = load_cached_tasks()
        if missions:
            _cached_missions = missions
            _last_fetch_time = os.path.getmtime(os.path.join(WORKING_FOLDER, 'tasks.json'))
            _has_loaded_initial = True
            logger.info(f"Initial load of {len(missions)} missions from tasks.json")
            return missions, {'success': True, 'source': 'initial_cache', 'error': None}
    
    # Return cached missions if they exist and are fresh enough
    if not force_refresh and _cached_missions is not None:
        logger.debug("Using cached missions from memory")
        return _cached_missions, {'success': True, 'source': 'memory_cache', 'error': None}
    
    # If force refresh or no cache, we need to load from API
    api_error = None
    try:
        token = read_auth_token()
        if not token:
            logger.warning("No auth token found. Loading cached tasks.")
            cached_missions = load_cached_tasks()
            return cached_missions, {'success': False, 'source': 'cache_fallback', 'error': 'No auth token found'}

        tasks = []
        page = 1
        per_page = 20
        
        logger.info("Fetching missions from API")
        try:
            while True:
                # Fetch the tasks with pagination
                response = requests.get(
                    f"{API_BASE_URL}?perPage={per_page}&viewed=true&page={page}&status=CLAIMED&includeAssignedBySynackUser=true",
                    headers={'Authorization': f'Bearer {token}'}
                )

                if response.status_code == 200:
                    new_tasks = response.json()
                    tasks.extend(new_tasks)
                    logger.info(f"Fetched {len(new_tasks)} missions from page {page}")

                    # Break the loop if fewer than `per_page` entries were returned
                    if len(new_tasks) < per_page:
                        break
                    page += 1
                elif response.status_code == 401:
                    logger.error(f"Error fetching tasks: HTTP {response.status_code}")
                    raise Exception("API call failed please check authentication")
                else:
                    logger.error(f"Error fetching tasks: HTTP {response.status_code}")
                    logger.error(f"Error fetching tasks: {api_error}")
                    break
                    
            # If no tasks were fetched, try to load from cached file
            if not tasks:
                logger.warning("No tasks fetched from API. Loading cached tasks.")
                cached_missions = load_cached_tasks()
                return cached_missions, {'success': False, 'source': 'cache_fallback', 'error': api_error or 'No tasks fetched from API'}
                
        except requests.exceptions.RequestException as e:
            api_error = f"Network error while fetching tasks: {e}"
            logger.error(api_error)
            cached_missions = load_cached_tasks()
            return cached_missions, {'success': False, 'source': 'cache_fallback', 'error': api_error}

        # Write the fetched tasks to the tasks.json file
        if not os.path.exists(WORKING_FOLDER):
            os.makedirs(WORKING_FOLDER)
            
        with open(os.path.join(WORKING_FOLDER, 'tasks.json'), 'w') as file:
            json.dump(tasks, file)
            logger.info(f"Saved {len(tasks)} missions to tasks.json")

        # Update cache and timestamp
        _cached_missions = tasks
        _last_fetch_time = current_time
        return tasks, {'success': True, 'source': 'api', 'error': None}
    except Exception as e:
        api_error = f"Error fetching tasks: {e}"
        logger.error(api_error)
        cached_missions = load_cached_tasks()
        return cached_missions, {'success': False, 'source': 'cache_fallback', 'error': api_error}

def load_cached_tasks():
    """Load tasks from the local cache file."""
    try:
        cache_path = os.path.join(WORKING_FOLDER, 'tasks.json')
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as file:
                tasks = json.load(file)
                logger.info(f"Loaded {len(tasks)} missions from cached tasks.json")
                return tasks
        else:
            logger.warning(f"No cached tasks found at {cache_path}")
            return []
    except Exception as e:
        logger.error(f"Error loading cached tasks: {e}")
        return []

def force_refresh_missions():
    """
    Force a refresh of missions from the API, ignoring caches.
    
    Returns:
        Tuple: (missions_list, api_success_status)
        - missions_list: List of mission objects  
        - api_success_status: Dict with 'success' (bool), 'source' (str), and 'error' (str) if applicable
    """
    global _last_fetch_time, _cached_missions
    _last_fetch_time = 0  # Reset the timestamp to force refresh
    _cached_missions = None  # Clear the cache
    return get_all_missions(force_refresh=True)  # Fetch fresh data

def sync_evidence_to_api(mission_id, evidence_data):
    """
    Sync mission evidence to the API.
    
    Args:
        mission_id: The ID of the mission
        evidence_data: Dict containing the evidence data
        
    Returns:
        Dict containing success status and response information
    """
    # Log what we're about to do
    logger.info(f"Syncing evidence to API for mission ID: {mission_id}")
    logger.info(f"Received payload: {evidence_data}")
    
    # Verify required fields (structuredResponse is optional)
    required_fields = ['introduction', 'testing_methodology', 'conclusion']
    for field in required_fields:
        if field not in evidence_data:
            error_msg = f"Missing required field: {field}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
    
    # Construct the API endpoint URL
    api_endpoint = f"{PLATFORM_BASE_URL}/api/tasks/v2/tasks/{mission_id}/evidences"
    logger.info(f"API endpoint: {api_endpoint}")
    
    # Get the API token
    token = read_auth_token()
    if not token:
        logger.error("No API token found")
        return {"success": False, "message": "No API token found. Please ensure your token file exists."}
    
    # Set up headers with token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Format the payload exactly as required by the API
    api_payload = {
        "introduction": evidence_data['introduction'],
        "testing_methodology": evidence_data['testing_methodology'],
        "conclusion": evidence_data['conclusion']
    }
    # Include structuredResponse if provided (SV2M sends values like 'vulnerable', others send 'yes'/'no')
    sr = evidence_data.get('structuredResponse')
    if isinstance(sr, str) and sr.strip():
        api_payload['structuredResponse'] = sr.strip()
    
    logger.info(f"Formatted API payload: {api_payload}")
    
    try:
        # Make the PATCH request to the Synack API
        logger.info(f"Sending PATCH request to {api_endpoint}")
        response = requests.patch(
            api_endpoint,
            headers=headers,
            json=api_payload
        )
        
        # Log the response
        logger.info(f"API response status: {response.status_code}")
        
        # Try to log response body
        try:
            response_data = response.json()
            logger.info(f"API response body: {response_data}")
        except:
            logger.info(f"API response text: {response.text}")
        
        # Check if the request was successful
        if response.status_code in [200, 201, 204]:
            logger.info("Evidence submitted successfully")
            return {"success": True, "message": "Evidence submitted successfully"}
        else:
            error_msg = f"API error: {response.status_code}"
            try:
                error_data = response.json()
                error_msg = f"{error_msg} - {error_data.get('message', 'Unknown error')}"
            except:
                error_msg = f"{error_msg} - {response.text}"
            
            logger.error(error_msg)
            return {
                "success": False, 
                "message": error_msg, 
                "status_code": response.status_code,
                "endpoint": api_endpoint,
                "sent_payload": api_payload
            }
            
    except Exception as e:
        error_msg = f"Error submitting evidence: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "message": error_msg,
            "endpoint": api_endpoint,
            "sent_payload": api_payload
        }


def delete_evidence_from_api(
    mission_id: str,
    evidence_id: str,
    organization_uid: str,
    listing_uid: str,
    campaign_uid: str,
):
    """Delete an evidence attachment from the Synack API."""
    logger.info(
        f"Deleting evidence {evidence_id} from mission {mission_id} via API"
    )

    api_endpoint = (
        f"{PLATFORM_BASE_URL}/api/tasks/v1/organizations/"
        f"{organization_uid}/listings/{listing_uid}/campaigns/{campaign_uid}/"
        f"tasks/{mission_id}/attachments/{evidence_id}"
    )

    token = read_auth_token()
    if not token:
        logger.error("No API token found")
        return False, "No API token found"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.delete(api_endpoint, headers=headers)
        logger.info(
            f"Delete evidence API response: {response.status_code}"
        )
        if response.status_code in [200, 201, 202, 204]:
            return True, None
        return False, f"API error {response.status_code}: {response.text}"
    except Exception as e:
        logger.error(f"Error deleting evidence via API: {e}")
        return False, str(e)
