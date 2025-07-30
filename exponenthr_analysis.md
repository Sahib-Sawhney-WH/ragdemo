# ExponentHR Documentation Analysis

## URL Structure Pattern
The ExponentHR help system uses a specific URL pattern:
- Base URL: `https://www.exponenthr.com/service/Help/Online/Exempt/ExponentHR_Personal_View.htm`
- Fragment identifier: `#t=` followed by the topic path
- Examples:
  - `#t=Accepted%2FAbout_ExponentHR.htm`
  - `#t=Accepted%2FEdit_Direct_Deposit.htm`
  - `#t=Edit_Retirement_Plan_Contributions.htm`

## Documentation Structure
The system has two main views:
1. **Personal View** - Employee-focused documentation
2. **Management View** - Manager-focused documentation

### Personal View Topics Discovered:
- About ExponentHR
- View/Edit Personal Information
- Report Time and Paid Leave
- Report Expenses
- View Wages and Direct Deposit
  - View Pay Information
  - Edit Pay Information
    - Edit Direct Deposit
    - Edit Retirement Plan Contributions
    - Edit W-4 Payroll Withholding
  - FAQs
- Manage My Benefits
- Access Company Information
- Performance Evaluation Dashboard
- Manage Customer Service Cases
- Demonstrations
- Troubleshooting

## Key Observations:
1. Content is loaded dynamically using fragment identifiers
2. The table of contents shows hierarchical structure
3. URLs use URL encoding (%2F for forward slashes)
4. Each topic corresponds to a specific .htm file path



## Additional Findings:

### URL Pattern Analysis:
1. **Base URLs:**
   - Personal View: `https://www.exponenthr.com/service/Help/Online/Exempt/ExponentHR_Personal_View.htm`
   - Management View: Likely accessible through the same interface but different navigation

2. **Fragment Structure:**
   - Uses `#t=` followed by the topic path
   - Paths can include subdirectories (e.g., `Accepted%2F`)
   - URL encoding is used (%2F for forward slashes)

3. **Content Discovery:**
   - The system has a hierarchical table of contents
   - Two main views: Personal and Management
   - Content is loaded dynamically based on fragment identifiers
   - Navigation is available through expandable/collapsible tree structure

### Technical Implementation Notes:
1. **Dynamic Content Loading:** The help system loads content dynamically using JavaScript based on the fragment identifier
2. **Navigation Structure:** The left sidebar contains the complete navigation tree
3. **Content Types:** Each topic corresponds to a specific .htm file with detailed documentation
4. **Cross-References:** Topics contain links to related topics and procedures

### Scraping Challenges Identified:
1. **Dynamic Content:** Content is loaded via JavaScript, requiring browser automation
2. **Navigation Discovery:** Need to programmatically expand all navigation sections
3. **URL Generation:** Must construct URLs with proper encoding for fragment identifiers
4. **Content Updates:** Need to detect when content changes on the server

### Next Steps for RAG Solution:
1. Implement web scraping with browser automation (Selenium/Playwright)
2. Create URL discovery mechanism to find all available topics
3. Set up Azure Blob Storage for content storage
4. Configure Azure AI Search for indexing and retrieval
5. Implement change detection and update mechanisms

