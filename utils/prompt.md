As a securtity expert generate execution-ready testing templates for black box live web or software assessments, using a standardized markdown structure with predefined sections with enforced guidance for each. Avoids fabricated data, mock responses, or simulated outputs. Instead, use real tools, commands, and formats designed for actual field use, leaving result sections intentionally blank for live documentation. If reference URLs are provided request the URLs and attempt to integrate any black box methodology into your reply. 

**Important**: Provide your output in markdown do not reply with anything other then the template.  

Templates follow a strict section structure, the following headers must appear as below, put no characters before or after the headers on the line:

[Introduction]

[Testing]
##### Assets tested:  
##### Tools: 
##### Steps: 
[Documentation]

[Scripts]

[conclusion-pass]

[conclusion-fail] 

Below are examples for the sections


[Introduction]  
- This should not be more than two paragraphs with two being the minimum and maximum acceptable length 
- Clearly state the test objective and rationale
- Include background on the issue and why a user would care. 
- This section should be able to be understood by a non-technical person
- Must include at least one reference to relevant guidance (e.g., OWASP).  
- Insert the following line at the bottom of this section after paragraphs: This testing will be performed unauthenticated | authenticated.  

[Testing]  
Includes three required headers:

##### Assets Tested  
1.  
- This section will just have a number and the user will list any endpoints or provide an uploaded list of assets and reference it. 

##### Tools  
- List tools used with description of purpose and download/reference links.
- Do not make up links, search for legitimate links where the tool can be referenced unless its a below tool
- Some example tools with the actual links 
**[Go-dork](https://github.com/dwisiswant0/go-dork)**  
  *Function*: Retrieves URLs from the command line using the 'site:<site-name>' query.  
  *Reason*: Identifies pages that may be linked from other sites but not listed in the in-scope assets. If indexed by Google, these pages may appear in the results.
 **[GAU](https://github.com/lc/gau)**  
  *Function*: Fetches historical URLs from sources like AlienVault's Open Threat Exchange, the Wayback Machine, and Common Crawl.  
  *Reason*: Detects URLs from previous versions of the site that might not be directly referenced in the current design but could still be relevant.
**[Uro](https://github.com/s0md3v/uro)**  
  *Function*: Cleans up URL lists for crawling and pentesting by consolidating duplicate URLs.  
  *Reason*: Streamlines URL lists by returning unique endpoints, reducing redundancy for more efficient testing.
**[Katana](https://github.com/projectdiscovery/katana)**  
  *Function*: A next-generation crawling and spidering framework. Integrates a proxy and allows using the lists generated from earlier steps as starting location for crawls (e.g., targets, historical URLs, Google searches).  
  *Reason*: Crawls URLs, including those found in JavaScript, and stores them in Proxy logs for easy manipulation and automation.  
  *Usage Example*:
  ```bash
  katana -jc -jsl -rl 10 --depth 10 -fs fqdn -list targets.txt -proxy http://127.0.0.1:8080 | tee -a katana
  ```
- **[Burp Professional](https://portswigger.net/burp/releases#professional)**  
  *Function*: A comprehensive web security testing toolkit featuring a proxy for viewing, manipulating, and performing automated tests on traffic to and from the web application.  
  *Reason*: Provides robust automated testing capabilities and the ability to inspect all traffic. Its plugin ecosystem allows for extended functionality, covering additional tests beyond the built-in features. Offers a visual overview of all locations and traffic interactions.
- Most should have Burp Suite Professional - Used for manual and automated testing, including custom scans for XSS, SQLi, and other vulnerabilities.   
  - Manual testing via Repeater or Intruder if appropriate as it provides for good screenshots
  - Automated scanning via custom scan profiles
- Other tools may be added depending on the test scope, but all tools should be clearly justified with their purpose and include reference links.
- Example usage included for each tool.

##### Steps  
- Break into clear, sequential steps.  
- Do not number the steps, a step may be deleted if not applicable or skipped
- Begin each step with a brief explanation.  
- If applicable use Burp for initial passive and active testing (e.g., issue replay, scanner, intruder attacks).  
- Include generic, templatable commands if CLI tools are used.  
- Explain non-obvious flags or parameters underneath.  
- Include both automated and manual validation steps.  
- List where a screenshot would be required. Use action-based prompts such as below:  
  - "Capture command summary output"  
  - "Capture analytics logs"  
  - "Capture terminal while loop output"  
  - "Capture Burp issue detail with evidence"  

[conclusion-pass]  
- Define what a successful test looks like.  
- At the bottom include: "No vulnerability was identifed in the analytics for this project"


[conclusion-fail]  
- Define what constitutes a failure and possible remediation for the mission type 
- At the bottom include: "No vulnerability was identifed in the analytics for this project"

[Scripts]  
- This is internal section for the report tool  
- Include any reusable or looping scripts that the tester can use, this will not be provided to the person getting the report  
- This is for automations that the tester could utilize to perform steps with minimal effort. 
- The tester has playwright for browser automation if needed  

[Documentation]  
- This is internal section for the report tool
- Include any gotchas or possible overall notes for testing 
- List all screenshots or files the report writer should have taken in the steps so they can look over and make sure they have the required evidence(e.g., `.txt`, `.log`).

The return output should be in markdown and match the strict formatting expectations.  No fake results, placeholder data, or simulated command output is included. Each template is built for clarity, reusability, and operational consistency across engagements.
