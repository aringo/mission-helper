// Wait for DOM and ensure all resources are loaded
window.addEventListener('load', function() {
    // Add a small delay to ensure all DOM elements are fully initialized
    setTimeout(() => {
        const missionRows = document.querySelectorAll('.mission-row');
        missionRows.forEach(row => {
            const countdownElement = row.querySelector('.countdown');
            if (countdownElement) {
                const claimedOn = countdownElement.dataset.claimedOn;
                const returnedOn = countdownElement.dataset.returnedOn;
                const maxSecs = parseInt(countdownElement.dataset.maxSecs, 10);
                
                if (maxSecs && !isNaN(maxSecs)) {
                    startCountdown(countdownElement.id, claimedOn, returnedOn, maxSecs);
                } else {
                    console.error('Invalid maxSecs value for', countdownElement.id);
                    countdownElement.textContent = 'Invalid duration';
                }
            }
        });
    }, 100); // 100ms delay
});
