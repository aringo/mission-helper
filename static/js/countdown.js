/**
 * Countdown timer functionality for mission deadlines
 * 
 * This script calculates and displays the remaining time for missions.
 */

// Global object to store all countdown timers
const countdownTimers = {};

/**
 * Format time duration in a readable format
 * @param {number} seconds - Total seconds remaining
 * @returns {string} Formatted time string
 */
function formatTime(seconds) {
    if (seconds <= 0) {
        return "Time expired";
    }
    
    const days = Math.floor(seconds / (24 * 3600));
    seconds %= (24 * 3600);
    
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    
    const minutes = Math.floor(seconds / 60);
    seconds %= 60;
    
    let result = "";
    
    if (days > 0) {
        result += days + "d ";
    }
    
    if (hours > 0 || days > 0) {
        result += hours + "h ";
    }
    
    if (minutes > 0 || hours > 0 || days > 0) {
        result += minutes + "m ";
    }
    
    result += seconds + "s";
    
    return result;
}

/**
 * Parse a date string and return a Date object
 * @param {string} dateString - ISO date string or timestamp
 * @returns {Date} JavaScript Date object
 */
function parseDate(dateString) {
    if (!dateString) return null;
    
    // Try parsing as ISO string first
    let date = new Date(dateString);
    
    // If valid, return it
    if (!isNaN(date.getTime())) {
        return date;
    }
    
    // Try parsing as a timestamp (milliseconds since epoch)
    if (/^\d+$/.test(dateString)) {
        date = new Date(parseInt(dateString, 10));
        if (!isNaN(date.getTime())) {
            return date;
        }
    }
    
    console.error('Failed to parse date string:', dateString);
    return null;
}

/**
 * Calculate the remaining time in seconds
 * @param {Date} startDate - Start date of the countdown
 * @param {number} maxSeconds - Maximum duration in seconds
 * @returns {number} Remaining seconds
 */
function calculateRemainingTime(startDate, maxSeconds) {
    if (!startDate || !maxSeconds) {
        console.error('Missing required parameters for countdown');
        return 0;
    }
    
    const now = new Date();
    const elapsedSeconds = Math.floor((now - startDate) / 1000);
    const remainingSeconds = maxSeconds - elapsedSeconds;
    
    return Math.max(0, remainingSeconds);
}

/**
 * Update the countdown display for a specific element
 * @param {string} elementId - ID of the countdown element
 */
function updateCountdown(elementId) {
    const timer = countdownTimers[elementId];
    if (!timer) {
        console.error('No timer found for:', elementId);
        return;
    }
    
    const element = document.getElementById(elementId);
    if (!element) {
        console.error('Countdown element not found:', elementId);
        clearInterval(timer.interval);
        delete countdownTimers[elementId];
        return;
    }
    
    const remainingSeconds = calculateRemainingTime(timer.startDate, timer.maxSeconds);
    element.textContent = formatTime(remainingSeconds);
    
    // Apply color based on remaining time
    if (remainingSeconds <= 0) {
        element.style.color = '#dc3545'; // Red
        clearInterval(timer.interval);
    } else if (remainingSeconds < 3600) { // Less than 1 hour
        element.style.color = '#dc3545'; // Red
    } else if (remainingSeconds < 24 * 3600) { // Less than 24 hours
        element.style.color = '#ffc107'; // Yellow/Amber
    } else {
        element.style.color = '#28a745'; // Green
    }
}

/**
 * Start a countdown timer for a mission
 * @param {string} elementId - ID of the countdown element
 * @param {string} claimedOn - ISO date string when the mission was claimed
 * @param {string} returnedOn - ISO date string when the mission was returned for edits
 * @param {number} maxSeconds - Maximum allowed time in seconds
 */
function startCountdown(elementId, claimedOn, returnedOn, maxSeconds) {
    // Clear any existing interval
    if (countdownTimers[elementId] && countdownTimers[elementId].interval) {
        clearInterval(countdownTimers[elementId].interval);
    }
    
    // Use returnedOn if available, otherwise use claimedOn
    const startDateString = returnedOn || claimedOn;
    const startDate = parseDate(startDateString);
    
    if (!startDate) {
        console.error('Invalid start date for countdown:', elementId);
        const element = document.getElementById(elementId);
        if (element) {
            element.textContent = 'Invalid date';
            element.style.color = '#dc3545'; // Red
        }
        return;
    }
    
    // Store the timer information
    countdownTimers[elementId] = {
        startDate,
        maxSeconds,
        interval: setInterval(() => updateCountdown(elementId), 1000)
    };
    
    // Initial update
    updateCountdown(elementId);
}

// Clean up intervals when page unloads
window.addEventListener('beforeunload', function() {
    // Clear all intervals
    Object.keys(countdownTimers).forEach(id => {
        clearInterval(countdownTimers[id].interval);
    });
});
