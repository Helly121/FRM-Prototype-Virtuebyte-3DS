document.addEventListener('DOMContentLoaded', () => {
    
    const editor = document.getElementById('payload-editor');
    const scoreBtn = document.getElementById('score-btn');
    const loader = document.getElementById('score-loader');
    const btnText = document.querySelector('.btn-text');
    let currentTxnId = null;
    
    // Tab DOM
    const btnSimulator = document.getElementById('tab-btn-simulator');
    const btnAudit = document.getElementById('tab-btn-audit');
    const tabSimulator = document.getElementById('tab-simulator');
    const tabAudit = document.getElementById('tab-audit');
    const auditTableBody = document.getElementById('audit-table-body');
    const btnDb = document.getElementById('tab-btn-db');
    const tabDb = document.getElementById('tab-db');
    const dbListBody = document.getElementById('db-list-body');
    const dbJsonContent = document.getElementById('db-json-content');
    const dbViewerTitle = document.getElementById('db-viewer-title');
    const btnRefreshDb = document.getElementById('btn-refresh-db');
    
    // Results DOM
    const emptyState = document.getElementById('results-empty');
    const resultsContent = document.getElementById('results-content');
    const valTier = document.getElementById('val-tier');
    const valDeviation = document.getElementById('val-deviation');
    const valIfscore = document.getElementById('val-ifscore');
    const valLatency = document.getElementById('val-latency');
    const valSummary = document.getElementById('val-summary');
    const factorsList = document.getElementById('factors-list');
    const contextList = document.getElementById('context-list');
    const cardTier = document.getElementById('card-tier');
    const feedbackSection = document.getElementById('feedback-section');
    const btnOtpSuccess = document.getElementById('btn-otp-success');

    // Sample Payloads
    const normalPayload = {
        "simulate_only": false,
        "card_id_hash": "00dd14b7deb88c381b2caae225819d34da20c27f81a2e807baaf0b4eb7153b5f",
        "acctType": "01",
        "mcc": "5411",
        "merchantCountryCode": "356",
        "purchaseAmount": 1000.0,
        "purchaseCurrency": "356",
        "purchaseDate": "2026-07-15T13:30:00+05:30",  // Wednesday, 1:30 PM (historically common)
        "cardSecurityCodeStatus": "01",
        "threeDSRequestorID": "REQ0001",
        "threeDSRequestorName": "Amazon India",
        "threeDSRequestorURL": "https://amazon.in",
        "threeDSRequestorAuthenticationInd": "01",
        "threeDSReqAuthMethod": "02",
        "chAccAgeInd": "05",
        "chAccChangeInd": "05",
        "chAccPwChangeInd": "05",
        "txnActivityDay": 1,
        "txnActivityYear": 50,
        "provisionAttemptsDay": 0,
        "nbPurchaseAccount": 50,
        "suspiciousAccActivity": "02",
        "shipNameIndicator": "01",
        "acquirerMerchantID": "MID000001",
        "acquirerBIN": "411111",
        "shipIndicator": "01",
        "billAddrLine1": "123 Main Road",
        "billAddrCity": "Mumbai",
        "billAddrCountry": "356",
        "billAddrPostCode": "400001",
        "email": "user0@gmail.com",
        "mobilePhone": "+919876543210",
        "shipAddrCity": "Mumbai",
        "shipAddrCountry": "356",
        "sdkInterface": "03",
        "sdkUiType": "01",
        "Platform": "Android",
        "DeviceModel": "Samsung Galaxy A34",
        "OSName": "Android",
        "OSVersion": "14",
        "Locale": "en_IN",
        "TimeZone": "Asia/Kolkata",
        "ScreenResolution": "1080x2340",
        "DeviceName": "Android_Samsung_Galaxy_A34",
        "IPAddress": "192.168.1.100",
        "Latitude": 18.52,
        "Longitude": 73.85,
        "ApplicationPackageName": "ef4f7219af5508087f0461e6c4a1bab855ec8ac6332cebcd659c3098b5c1c23e",
        "SDKAppID": "sdk_app_test",
        "SDKVersion": "5.3.0",
        "SDKRefNumber": "SDK_REF_CONSTANT_HASH_V1",
        "dateTime": "2026-07-15T13:30:03+05:30"
    };

    const anomalyPayload = {
        ...normalPayload,
        "purchaseAmount": 950000.0,
        "purchaseCurrency": "840", // USD
        "merchantCountryCode": "840", // US
        "mcc": "5944", // Jewelry Store
        "purchaseDate": "2026-07-19T03:15:00+05:30", // Sunday 3 AM
        "txnActivityDay": 15,
        "Platform": "macOS",
        "DeviceModel": "MacBook Pro M3",
        "OSName": "macOS",
        "OSVersion": "14.4",
        "ScreenResolution": "3024x1964",
        "IPAddress": "8.8.8.8", // Foreign IP
        "Latitude": 37.77,
        "Longitude": -122.41,
        "ApplicationPackageName": "com.unknown.fraud.app",
        "chAccChangeInd": "01" // Password just changed
    };

    // Initialization
    editor.value = JSON.stringify(normalPayload, null, 2);

    // Preset buttons logic
    document.getElementById('btn-normal').addEventListener('click', (e) => {
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        editor.value = JSON.stringify(normalPayload, null, 2);
    });

    document.getElementById('btn-anomaly').addEventListener('click', (e) => {
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        editor.value = JSON.stringify(anomalyPayload, null, 2);
    });

    // Handle Form Submission
    scoreBtn.addEventListener('click', async () => {
        let payload;
        try {
            payload = JSON.parse(editor.value);
        } catch (e) {
            alert("Invalid JSON payload.");
            return;
        }

        // UI Loading state
        btnText.style.display = 'none';
        loader.style.display = 'block';
        scoreBtn.disabled = true;

        try {
            const response = await fetch('/internal/score', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const report = await response.json();
            renderReport(report);
            
        } catch (error) {
            console.error("Error scoring transaction:", error);
            alert("Failed to score transaction. Ensure the backend is running and connected to PostgreSQL.");
        } finally {
            // Restore UI
            btnText.style.display = 'block';
            loader.style.display = 'none';
            scoreBtn.disabled = false;
        }
    });

    function renderReport(report) {
        // Toggle empty state
        emptyState.style.display = 'none';
        resultsContent.style.display = 'block';
        
        currentTxnId = report.transaction_id;
        feedbackSection.style.display = 'block';

        // Update Top Metrics
        valTier.textContent = report.deviation_tier;
        valDeviation.textContent = report.total_deviation.toFixed(2);
        // Map IF Score to a 0-100% Trust Score
        let trustPct = Math.min(100, Math.max(0, 100 + (report.if_score * 400)));
        valIfscore.textContent = trustPct.toFixed(1) + '%';
        valLatency.textContent = `${report.metadata.scoring_latency_ms.toFixed(1)} ms`;

        // Update Tier Styling
        cardTier.className = `metric-card tier-${report.deviation_tier}`;

        // Summary
        valSummary.textContent = report.summary;

        // Factors List
        factorsList.innerHTML = '';
        if (report.contributing_factors && report.contributing_factors.length > 0) {
            report.contributing_factors.forEach(factor => {
                const el = document.createElement('div');
                el.className = 'factor-item';
                
                // Add a dynamic border color based on contribution
                if(factor.contribution_pct > 15) el.style.borderLeft = "4px solid var(--status-high)";
                else if(factor.contribution_pct > 5) el.style.borderLeft = "4px solid var(--status-medium)";
                else el.style.borderLeft = "4px solid #5e6ad2";

                el.innerHTML = `
                    <div class="factor-header">
                        <div class="factor-title">${formatFieldTitle(factor.field)}</div>
                        <div class="factor-pct">${factor.contribution_pct.toFixed(1)}% Impact</div>
                    </div>
                    <div class="factor-desc">${factor.reason}</div>
                    <div class="factor-details">
                        <div class="detail-col">
                            <span class="detail-label">Observed</span>
                            <span class="detail-val">${factor.observed || "N/A"}</span>
                        </div>
                        <div class="detail-col">
                            <span class="detail-label">Expected</span>
                            <span class="detail-val">${factor.expected || "N/A"}</span>
                        </div>
                    </div>
                `;
                factorsList.appendChild(el);
            });
        } else {
            factorsList.innerHTML = '<p style="color:var(--text-muted)">No significant risk factors identified.</p>';
        }

        // Context List
        contextList.innerHTML = '';
        if (report.non_contributing_context && report.non_contributing_context.length > 0) {
            report.non_contributing_context.forEach(ctx => {
                const li = document.createElement('li');
                li.textContent = ctx;
                contextList.appendChild(li);
            });
        } else {
            contextList.innerHTML = '<li style="color:var(--text-muted)">No contextual data available.</li>';
        }
    }

    // Utility: Format raw field paths (e.g. "device.ApplicationPackageName") into human titles
    function formatFieldTitle(rawPath) {
        const parts = rawPath.split('.');
        const fieldName = parts[parts.length - 1];
        
        // Simple regex to insert spaces before capital letters
        const formatted = fieldName.replace(/([A-Z])/g, ' $1').trim();
        // Capitalize first letter
        return formatted.charAt(0).toUpperCase() + formatted.slice(1);
    }
    
    // Feedback Logic
    btnOtpSuccess.addEventListener('click', async () => {
        if (!currentTxnId) return;
        
        const originalText = btnOtpSuccess.innerHTML;
        btnOtpSuccess.innerHTML = "⏳ Submitting...";
        btnOtpSuccess.disabled = true;
        
        try {
            const response = await fetch('/internal/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    txn_id: currentTxnId,
                    outcome: "confirmed_legit",
                    source: "otp_success"
                })
            });
            
            if (!response.ok) throw new Error("Feedback failed");
            
            btnOtpSuccess.innerHTML = "✅ Feedback Submitted! (Score again to see learning loop)";
            btnOtpSuccess.style.backgroundColor = "#059669"; // darker green
            
            setTimeout(() => {
                btnOtpSuccess.innerHTML = originalText;
                btnOtpSuccess.disabled = false;
            }, 3000);
            
        } catch (e) {
            console.error("Feedback error:", e);
            alert("Failed to submit feedback.");
            btnOtpSuccess.innerHTML = originalText;
            btnOtpSuccess.disabled = false;
        }
    });

    // Menu DOM elements
    const btnDemo = document.getElementById('tab-btn-demo');
    const tabDemo = document.getElementById('tab-demo');
    const breadcrumbActive = document.getElementById('breadcrumb-active');
    
    // View Switching Logic
    function switchView(activeBtn, activeTab, title) {
        // Reset all buttons
        [btnSimulator, btnAudit, btnDb, btnDemo].forEach(btn => {
            if(btn) btn.classList.remove('active');
        });
        // Reset all tabs
        [tabSimulator, tabAudit, tabDb, tabDemo].forEach(tab => {
            if(tab) tab.classList.remove('active');
        });
        
        // Activate current
        if(activeBtn) activeBtn.classList.add('active');
        if(activeTab) activeTab.classList.add('active');
        if(breadcrumbActive) breadcrumbActive.innerText = title;
    }

    if(btnSimulator) btnSimulator.addEventListener('click', () => switchView(btnSimulator, tabSimulator, "Transaction Simulator"));
    
    if(btnAudit) {
        btnAudit.addEventListener('click', () => {
            switchView(btnAudit, tabAudit, "Audit Log");
            fetchAuditLog();
        });
    }

    if(btnDb) {
        btnDb.addEventListener('click', () => {
            switchView(btnDb, tabDb, "Profile Explorer");
            fetchDbExplorer();
        });
    }
    
    if(btnDemo) {
        btnDemo.addEventListener('click', () => {
            switchView(btnDemo, tabDemo, "Dynamic Simulator");
        });
    }

    if (btnRefreshDb) {
        btnRefreshDb.addEventListener('click', fetchDbExplorer);
    }

    // Fetch and render audit log
    async function fetchAuditLog() {
        auditTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem;">Loading audit logs...</td></tr>';
        
        try {
            const response = await fetch('/internal/audit');
            if (!response.ok) throw new Error("Failed to fetch audit log");
            
            const logs = await response.json();
            
            if (logs.length === 0) {
                auditTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem;">No transactions audited yet.</td></tr>';
                return;
            }

            auditTableBody.innerHTML = '';
            logs.forEach(log => {
                const tr = document.createElement('tr');
                
                // Format Timestamp
                const dt = new Date(log.scored_at);
                const timeString = dt.toLocaleString();
                
                // Tier Badge
                let badgeClass = 'low';
                if (log.deviation_tier === 'MEDIUM') badgeClass = 'medium';
                if (log.deviation_tier === 'HIGH') badgeClass = 'high';
                
                // Calculate Model Trust Percentage
                let trustPct = Math.min(100, Math.max(0, 100 + (log.if_score * 400)));
                
                tr.innerHTML = `
                    <td style="font-family: var(--font-mono); color: var(--accent);">${log.txn_id.substring(0, 8)}...</td>
                    <td style="font-family: var(--font-mono);">${log.card_id_hash.substring(0, 12)}...</td>
                    <td style="color: var(--text-muted);">${timeString}</td>
                    <td><span class="badge ${badgeClass}">${log.deviation_tier}</span></td>
                    <td style="font-weight: 600;">${trustPct.toFixed(1)}%</td>
                `;
                auditTableBody.appendChild(tr);
            });

        } catch (e) {
            console.error("Audit log error:", e);
            auditTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #ef4444;">Failed to load audit logs.</td></tr>';
        }
    }

    // Dynamic Load Simulator Logic
    const btnRunDemo = document.getElementById('btn-run-demo');
    const demoLoader = document.getElementById('demo-loader');
    const demoResultsContainer = document.getElementById('demo-results-container');
    const demoTableBody = document.getElementById('demo-table-body');
    const demoTime = document.getElementById('demo-time');

    if (btnRunDemo) {
        btnRunDemo.addEventListener('click', async () => {
            const btnText = btnRunDemo.querySelector('.btn-text');
            btnRunDemo.disabled = true;
            btnText.innerHTML = "Simulating 50 Users...";
            demoLoader.style.display = "inline-block";
            demoResultsContainer.style.display = "none";
            
            try {
                const response = await fetch('/internal/demo-load-test', {
                    method: 'POST',
                });
                
                if (!response.ok) throw new Error("Simulation failed");
                const data = await response.json();
                
                // Clear previous results
                demoTableBody.innerHTML = '';
                
                // Populate table
                data.results.forEach(res => {
                    const row = document.createElement('tr');
                    
                    let tierColor = "#ef4444"; // HIGH
                    if (res.tier === "LOW") tierColor = "#10b981";
                    else if (res.tier === "MEDIUM") tierColor = "#f59e0b";
                    
                    let typeLabel = "Normal";
                    if (res.type === "suspicious") typeLabel = "Suspicious";
                    else if (res.type === "abnormal") typeLabel = "Abnormal";
                    
                    row.innerHTML = `
                        <td style="font-family: monospace;">${res.card_id}</td>
                        <td>${typeLabel}</td>
                        <td style="color: ${tierColor}; font-weight: bold;">${res.tier}</td>
                        <td style="font-family: monospace;">${res.score.toFixed(2)}</td>
                        <td style="font-family: monospace; color: #94a3b8;">${res.latency.toFixed(1)} ms</td>
                    `;
                    demoTableBody.appendChild(row);
                });
                
                // Show completion time
                demoTime.innerHTML = `✅ Simulation completed in <strong>${data.total_time_sec} seconds</strong>.`;
                demoResultsContainer.style.display = "block";
                
            } catch (e) {
                console.error(e);
                alert("Load simulation failed. Check backend logs.");
            } finally {
                btnRunDemo.disabled = false;
                btnText.innerHTML = "Run 50-User Simulation 🚀";
                demoLoader.style.display = "none";
            }
        });
    }

    // Fetch and render DB Explorer
    async function fetchDbExplorer() {
        if (!dbListBody) return;
        dbListBody.innerHTML = '<tr><td colspan="2" style="text-align: center; padding: 2rem;">Loading database rows...</td></tr>';
        
        try {
            const response = await fetch('/internal/db-explorer');
            if (!response.ok) throw new Error("Failed to fetch database rows");
            
            const rows = await response.json();
            
            if (rows.length === 0) {
                dbListBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">No profiles found.</td></tr>';
                return;
            }

            dbListBody.innerHTML = '';
            rows.forEach((row) => {
                const tr = document.createElement('tr');
                const profile = row.profile || {};
                
                // Extract specific keys for the flat table
                const sdk = profile.sdk_version || 'N/A';
                const device = profile.device_model || 'N/A';
                const resolution = profile.known_resolution || 'N/A';
                
                tr.innerHTML = `
                    <td class="mono-cell">${row.card_id_hash.substring(0, 16)}...</td>
                    <td style="color: #93c5fd;">${sdk}</td>
                    <td>${device}</td>
                    <td>${resolution}</td>
                `;
                
                dbListBody.appendChild(tr);
            });

        } catch (e) {
            console.error("DB Explorer error:", e);
            dbListBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #ef4444;">Failed to load database profiles.</td></tr>';
        }
    }

});
