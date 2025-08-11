        // Function to show a flash message
        function showFlashMessage(message, type = 'success', duration = 3000) {
            // Remove any existing flash messages
            const existingFlash = document.querySelector('.flash-message');
            if (existingFlash) {
                existingFlash.remove();
            }
            
            // Create a new flash message
            const flashMessage = document.createElement('div');
            flashMessage.className = `flash-message flash-${type}`;
            flashMessage.innerText = message;
            
            // Add it to the document
            document.body.appendChild(flashMessage);
            
            // Remove it after the specified duration
            setTimeout(() => {
                flashMessage.style.opacity = '0';
                setTimeout(() => {
                    flashMessage.remove();
                }, 300);
            }, duration);
        }
        
        function setTheme(theme) {
            console.log('Setting theme to:', theme);
            // Update the select element if it exists
            const themeSelect = document.getElementById('themeSelect');
            if (themeSelect) {
                themeSelect.value = theme;
            }
            
            // Apply the theme to the document using data-theme attribute
            if (document.documentElement) {
                document.documentElement.setAttribute('data-theme', theme);
            } else {
                console.log('document.documentElement not available yet, will set attribute when DOM is loaded');
                document.addEventListener('DOMContentLoaded', function() {
                    document.documentElement.setAttribute('data-theme', theme);
                });
            }
            
            // CSS variables are now automatically applied via data-theme attribute
            // No need to manually set them
            
            // Save to localStorage
            localStorage.setItem('theme', theme);
            console.log('Theme set to:', theme, '- Saved to localStorage');
        }

        // IMPORTANT: Initialize theme from localStorage immediately 
        // This must run before the page renders to avoid flashes
        try {
            const savedTheme = localStorage.getItem('theme');
            console.log('Found saved theme in localStorage:', savedTheme);
            // Store the theme value but don't apply it yet - will apply after DOM is loaded
            window._savedTheme = savedTheme || 'light';
        } catch (e) {
            console.error('Error loading theme from localStorage:', e);
            window._savedTheme = 'light';
        }

        // Debug CSS loading
        document.addEventListener('DOMContentLoaded', function() {
            console.log('DOM content loaded, applying saved theme:', window._savedTheme);
            setTheme(window._savedTheme);
            
            // Set selected value in theme dropdown
            const themeSelect = document.getElementById('themeSelect');
            if (themeSelect) {
                const savedTheme = localStorage.getItem('theme') || 'light';
                themeSelect.value = savedTheme;
                console.log('Updated dropdown selection to match theme:', savedTheme);
            }
            
            // Add refresh button event listener
            const refreshButton = document.querySelector('#refreshButton');
            if (refreshButton) {
                refreshButton.addEventListener('click', function() {
                    refreshButton.classList.add('spinning');
                    
                    showFlashMessage('Refreshing missions...', 'info');
                    
                    fetch(window.refreshTasksUrl)
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                showFlashMessage(data.message, 'success');
                                // Reload the page after a brief delay so the user can see the message
                                setTimeout(() => {
                                    location.reload();
                                }, 1000);
                            } else {
                                showFlashMessage('Failed to refresh: ' + data.message, 'error');
                                refreshButton.classList.remove('spinning');
                            }
                        })
                        .catch(error => {
                            console.error('Error:', error);
                            showFlashMessage('An error occurred while refreshing', 'error');
                            refreshButton.classList.remove('spinning');
                        });
                });
            }


            
            // Debug CSS loading
            console.log('Base template loaded - checking stylesheets');
            const styleSheets = document.styleSheets;
            for (let i = 0; i < styleSheets.length; i++) {
                try {
                    console.log('Stylesheet ' + i + ':', styleSheets[i].href);
                } catch (e) {
                    console.log('Error accessing stylesheet ' + i + ':', e);
                }
            }
        });

                // Ensure theme persists correctly on back/forward navigation (bfcache restore)
                window.addEventListener('pageshow', function(event) {
                    try {
                        const savedTheme = localStorage.getItem('theme') || 'light';
                        const current = document.documentElement.getAttribute('data-theme');
                        if (current !== savedTheme) {
                            setTheme(savedTheme);
                        }
                    } catch (e) {
                        // ignore
                    }
                });
