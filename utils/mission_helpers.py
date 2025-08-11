import os
import json
import logging
from utils.api import get_all_missions

logger = logging.getLogger(__name__)


def get_mission_by_id(mission_id):
    """Return the mission object for the given ID or None."""
    missions, _ = get_all_missions()
    mission = next((m for m in missions if m.get('id') == mission_id), None)
    if not mission:
        logger.warning(f"Mission with ID {mission_id} not found")
    return mission


def find_draft_path(working_folder, listing_codename, mission_id):
    """Locate a draft file for the given mission."""
    directory = os.path.join(working_folder, listing_codename)
    mapping_file = os.path.join(directory, "draft_mapping.json")
    draft_filename = mission_id

    if os.path.exists(mapping_file):
        try:
            with open(mapping_file, "r") as f:
                mapping = json.load(f)
            draft_filename = mapping.get(mission_id, draft_filename)
        except Exception as e:
            logger.error(f"Error loading draft mapping: {e}")

    for path in [
        os.path.join(directory, f"{draft_filename}.txt"),
        os.path.join(directory, f"{mission_id}.txt"),
    ]:
        if os.path.exists(path):
            return path
    return None


def get_attachment_dirs(upload_folder, listing_codename, mission_id):
    """Return attachment and metadata directories for a mission."""
    attachments_dir = os.path.join(upload_folder, listing_codename, mission_id)
    metadata_dir = os.path.join(attachments_dir, "metadata")
    return attachments_dir, metadata_dir
