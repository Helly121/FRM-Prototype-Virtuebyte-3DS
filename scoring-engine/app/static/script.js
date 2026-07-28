document.addEventListener('DOMContentLoaded', () => {
    
    const editor = document.getElementById('payload-editor');
    const scoreBtn = document.getElementById('score-btn');
    const loader = document.getElementById('score-loader');
    const btnText = scoreBtn.querySelector('.btn-text');
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
    const btnRefreshDb = document.getElementById('btn-refresh-db');

    // DB Explorer Pagination & Search DOM
    const dbSearch = document.getElementById('db-search');
    const dbPrev = document.getElementById('db-prev');
    const dbNext = document.getElementById('db-next');
    const dbPageInfo = document.getElementById('db-page-info');
    let dbOffset = 0;
    const DB_LIMIT = 50;

    // Modal DOM
    const profileModal = document.getElementById('profile-modal');
    const modalClose = document.getElementById('modal-close');
    const modalContent = document.getElementById('modal-content');
    const modalTitle = document.getElementById('modal-title');
    
    if (modalClose) {
        modalClose.addEventListener('click', () => {
            profileModal.style.display = 'none';
        });
    }
    
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
        "force_profile_update": true, // Force update for demo visibility
        "card_id_hash": "a9d188e4884d9e49506e2ed8c56c7017dc17b62fb90234a9efdf2ef45b206775",
        "acctType": "01",
        "mcc": "5411",
        "merchantCountryCode": "356",
        "purchaseAmount": 1500.0,
        "purchaseCurrency": "356",
        "purchaseDate": "2026-07-15T14:30:00+05:30",
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
        "DeviceModel": "Samsung Galaxy S23",
        "OSName": "Android",
        "OSVersion": "14",
        "Locale": "en_IN",
        "TimeZone": "Asia/Kolkata",
        "ScreenResolution": "1080x2340",
        "DeviceName": "Android_Samsung_Galaxy_S23",
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
            
            // Auto-refresh Profile Explorer so the dynamic update is instantly visible
            if (typeof fetchDbExplorer === 'function') {
                fetchDbExplorer();
            }
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
        btnOtpSuccess.innerHTML = "Submitting...";
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
            
            btnOtpSuccess.innerHTML = "Feedback submitted. Score again to see the learning loop.";
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
    const btnConfig = document.getElementById('tab-btn-config');
    const tabConfig = document.getElementById('tab-config');
    const breadcrumbActive = document.getElementById('breadcrumb-active');
    
    // View Switching Logic
    function switchView(activeBtn, activeTab, title) {
        // Reset all buttons
        [btnSimulator, btnAudit, btnDb, btnDemo, btnConfig].forEach(btn => {
            if(btn) btn.classList.remove('active');
        });
        // Reset all tabs
        [tabSimulator, tabAudit, tabDb, tabDemo, tabConfig].forEach(tab => {
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

    if(btnConfig) {
        btnConfig.addEventListener('click', () => {
            switchView(btnConfig, tabConfig, "Model Configuration");
            fetchWeights();
            fetchWeightHistory();
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
                    
                    let factorsHtml = '';
                    if (res.factors && res.factors.length > 0) {
                        factorsHtml = res.factors.map(f => 
                            `<span style="background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 4px; border: 1px solid rgba(255,255,255,0.1); display: inline-block; margin-bottom: 2px; text-transform: capitalize;">${f.field} (${f.pct.toFixed(0)}%)</span>`
                        ).join('');
                    } else {
                        factorsHtml = '<span style="color: #64748b; font-size: 0.8rem;">None</span>';
                    }
                    
                    row.innerHTML = `
                        <td style="font-family: monospace;">${res.card_id}</td>
                        <td>${typeLabel}</td>
                        <td style="color: ${tierColor}; font-weight: bold;">${res.tier}</td>
                        <td style="font-family: monospace;">${res.score.toFixed(2)}</td>
                        <td>${factorsHtml}</td>
                        <td style="font-family: monospace; color: #94a3b8;">${res.latency.toFixed(1)} ms</td>
                    `;
                    row.style.cursor = "pointer";
                    row.addEventListener('mouseenter', () => row.style.backgroundColor = 'rgba(255,255,255,0.05)');
                    row.addEventListener('mouseleave', () => row.style.backgroundColor = 'transparent');
                    
                    row.addEventListener('click', () => {
                        const modalTitle = document.getElementById('modal-title');
                        const modalContent = document.getElementById('modal-content');
                        if (profileModal && modalTitle && modalContent) {
                            modalTitle.innerText = `Simulated Transaction (Tier: ${res.tier})`;
                            
                            const displayData = {
                                "Risk Summary": {
                                    "Risk_Tier": res.tier,
                                    "Total_Deviation": res.score.toFixed(2),
                                    "Latency": res.latency.toFixed(1) + ' ms'
                                },
                                "Contributing Factors": res.full_factors,
                                "Raw Payload": res.raw_payload
                            };
                            
                            modalContent.innerHTML = generateCleanHTML(displayData);
                            profileModal.style.display = 'flex';
                        }
                    });
                    
                    demoTableBody.appendChild(row);
                });
                
                // Show completion time
                demoTime.innerHTML = `Simulation completed in <strong>${data.total_time_sec} seconds</strong>.`;
                demoResultsContainer.style.display = "block";
                
                // Refresh DB explorer implicitly so it's updated in the background
                if (typeof fetchDbExplorer === "function") {
                    fetchDbExplorer();
                }
                
            } catch (e) {
                console.error(e);
                alert("Load simulation failed. Check backend logs.");
            } finally {
                btnRunDemo.disabled = false;
                btnText.innerHTML = "Run 50-User Simulation";
                demoLoader.style.display = "none";
            }
        });
    }

    // Pagination and Search Handlers
    if (dbSearch) {
        let debounceTimer;
        dbSearch.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                dbOffset = 0;
                fetchDbExplorer();
            }, 300);
        });
    }

    if (dbPrev) {
        dbPrev.addEventListener('click', () => {
            if (dbOffset >= DB_LIMIT) {
                dbOffset -= DB_LIMIT;
                fetchDbExplorer();
            }
        });
    }

    if (dbNext) {
        dbNext.addEventListener('click', () => {
            dbOffset += DB_LIMIT;
            fetchDbExplorer();
        });
    }

    // JSON Formatter for Modal
    function generateCleanHTML(obj) {
        if (typeof obj !== 'object' || obj === null) {
            return `<span style="color: #60a5fa;">${obj}</span>`;
        }
        
        let html = '<table style="width: 100%; border-collapse: collapse;">';
        for (const [key, value] of Object.entries(obj)) {
            html += `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                    <td style="padding: 8px; color: #94a3b8; width: 30%; vertical-align: top;">${key}</td>
                    <td style="padding: 8px; word-break: break-all;">${generateCleanHTML(value)}</td>
                </tr>
            `;
        }
        html += '</table>';
        return html;
    }

    // Fetch and render DB Explorer
    async function fetchDbExplorer() {
        if (!dbListBody) return;
        dbListBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">Loading database rows...</td></tr>';
        
        try {
            const searchQuery = dbSearch ? dbSearch.value.trim() : '';
            let url = `/internal/db-explorer?limit=${DB_LIMIT}&offset=${dbOffset}`;
            if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;

            const response = await fetch(url);
            if (!response.ok) throw new Error("Failed to fetch database rows");
            
            const rows = await response.json();
            
            // Update Pagination UI
            if (dbPageInfo) {
                const pageNum = Math.floor(dbOffset / DB_LIMIT) + 1;
                dbPageInfo.innerText = `Page ${pageNum}`;
            }
            if (dbPrev) dbPrev.disabled = dbOffset === 0;
            if (dbNext) dbNext.disabled = rows.length < DB_LIMIT;

            if (rows.length === 0) {
                dbListBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">No profiles found.</td></tr>';
                return;
            }

            dbListBody.innerHTML = '';
            rows.forEach((row) => {
                const tr = document.createElement('tr');
                tr.style.cursor = "pointer";
                const profile = row.profile || {};
                const meta = profile._meta || {};
                const device = profile.device || {};
                const requestor = profile.requestor || {};
                
                // Maturity: Txn Count & Confidence
                const txCount = meta.transaction_count || 0;
                const conf = (meta.profile_confidence || 0).toFixed(2);
                const maturityHtml = `
                    <div style="display: flex; flex-direction: column; gap: 4px;">
                        <span style="color: #f8fafc; font-weight: 500;">${txCount} Txns</span>
                        <div style="width: 100px; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden;">
                            <div style="width: ${conf * 100}%; height: 100%; background: #3b82f6;"></div>
                        </div>
                    </div>
                `;

                // Trust State: Normal, Probation, or Elevated Scrutiny
                let trustState = "Normal";
                let trustColor = "#10b981"; // Green
                
                if (requestor.suspicious_ever) {
                    trustState = "Elevated Scrutiny";
                    trustColor = "#ef4444"; // Red
                } else if (device.probation && Object.keys(device.probation).length > 0) {
                    trustState = "Probation";
                    trustColor = "#f59e0b"; // Yellow
                }
                
                const trustHtml = `<span style="color: ${trustColor}; font-weight: 600; font-size: 0.85rem; padding: 2px 8px; border-radius: 12px; background: ${trustColor}20;">${trustState}</span>`;

                // Last Updated
                const updatedDate = new Date(meta.last_updated * 1000);
                const updatedStr = isNaN(updatedDate.getTime()) ? 'N/A' : updatedDate.toLocaleString();

                tr.innerHTML = `
                    <td class="mono-cell">${row.card_id_hash.substring(0, 16)}...</td>
                    <td>${maturityHtml}</td>
                    <td>${trustHtml}</td>
                    <td style="color: #94a3b8; font-size: 0.85rem;">${updatedStr}</td>
                `;
                
                tr.addEventListener('mouseenter', () => tr.style.backgroundColor = 'rgba(255,255,255,0.05)');
                tr.addEventListener('mouseleave', () => tr.style.backgroundColor = 'transparent');
                
                tr.addEventListener('click', () => {
                    if (profileModal) {
                        modalTitle.innerText = `Raw ML Profile: ${row.card_id_hash.substring(0, 16)}...`;
                        modalContent.innerHTML = generateCleanHTML(profile);
                        profileModal.style.display = 'flex';
                    }
                });
                
                dbListBody.appendChild(tr);
            });

        } catch (e) {
            console.error("DB Explorer error:", e);
            dbListBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #ef4444;">Failed to load database profiles.</td></tr>';
        }
    }

    // ================================================================
    // MODEL CONFIGURATION — Issue #3
    // All config code lives inside the existing DOMContentLoaded block.
    // ================================================================

    // ── Weight group definitions ─────────────────────────────────────
    const WEIGHT_GROUPS = [
        {
            id: 'device', title: 'Device Intelligence', icon: '📱',
            iconBg: 'rgba(37,99,235,0.12)',
            description: 'Device fingerprint, platform, OS and SDK signals',
            vectors: [
                { name: 's_platform',           label: 'Platform',            desc: 'Surprise when the device OS platform (Android/iOS) changes from baseline.' },
                { name: 's_device_model',        label: 'Device Model',        desc: 'Surprise when the hardware model is not in the known device set.' },
                { name: 's_device_fp_composite', label: 'Device Fingerprint',  desc: 'Composite hash of Platform+Model+OS+App. Flags full device replacement.' },
                { name: 's_os_name',             label: 'OS Name',             desc: 'Surprise when the operating system name changes (e.g. Android → macOS).' },
                { name: 's_os_version',          label: 'OS Version',          desc: 'OS version changes; downgrades receive a 1.5× penalty.' },
                { name: 's_app_package',         label: 'App Package',         desc: 'Unknown app performing 3DS auth triggers a high integrity penalty.' },
                { name: 's_sdk_ref_tamper',      label: 'SDK Ref Tamper',      desc: 'SDK Reference Number hash mismatch — strong tampering indicator.' },
                { name: 's_sdk_version',         label: 'SDK Version',         desc: 'Surprise when the SDK version is outside the known version set.' },
            ]
        },
        {
            id: 'location', title: 'Location Intelligence', icon: '🌍',
            iconBg: 'rgba(15,118,110,0.12)',
            description: 'Geographic, IP, timezone and screen signals',
            vectors: [
                { name: 's_gps_billing_dist', label: 'Geo Distance',    desc: 'Log-scaled Haversine distance between GPS location and historical centroid.' },
                { name: 's_ip_subnet',        label: 'IP Subnet',       desc: 'Surprise when the /24 subnet is not in the known set.' },
                { name: 's_timezone',         label: 'Timezone',        desc: 'Surprise when device timezone is not in the known set.' },
                { name: 's_screen_res',       label: 'Screen Resolution', desc: 'Surprise when screen resolution is not in the known set.' },
                { name: 's_locale',           label: 'Locale',          desc: 'Surprise when device locale (language/region) is unusual.' },
            ]
        },
        {
            id: 'transaction', title: 'Transaction Behaviour', icon: '💳',
            iconBg: 'rgba(124,58,237,0.12)',
            description: 'Amount, MCC, currency and account type signals',
            vectors: [
                { name: 's_amount',           label: 'Purchase Amount',  desc: 'Z-score on log-transformed amount vs EWMA baseline.' },
                { name: 's_mcc',              label: 'Merchant Category', desc: 'Laplace-smoothed surprise when MCC is outside historical distribution.' },
                { name: 's_merchant_country', label: 'Merchant Country', desc: 'Surprise when the merchant country code is uncommon.' },
                { name: 's_currency',         label: 'Currency',         desc: 'Surprise when transaction currency is unusual.' },
                { name: 's_acct_type',        label: 'Account Type',     desc: 'Surprise when account type (credit/debit) deviates from norm.' },
                { name: 's_cvv_status',       label: 'CVV Status',       desc: 'Deviation from historical CVV match rate.' },
                { name: 's_temporal',         label: 'Time of Transaction', desc: 'Histogram-density surprise from hour-of-day and day-of-week.' },
            ]
        },
        {
            id: 'merchant', title: 'Merchant & Identity', icon: '🏪',
            iconBg: 'rgba(217,119,6,0.12)',
            description: 'Merchant IDs, addresses and contact hash signals',
            vectors: [
                { name: 's_merchant_id',        label: 'Merchant ID',       desc: 'Surprise when acquirer merchant ID is not in the known set.' },
                { name: 's_acquirer_bin',        label: 'Acquirer BIN',      desc: 'Surprise when acquirer BIN is outside the known set.' },
                { name: 's_billing_addr_hash',   label: 'Billing Address',   desc: 'New billing address hash not in the known address set.' },
                { name: 's_shipping_addr_hash',  label: 'Shipping Address',  desc: 'New shipping address hash not in the known set.' },
                { name: 's_email_hash',          label: 'Email Hash',        desc: 'New email address hash not in the known email set.' },
                { name: 's_phone_hash',          label: 'Phone Hash',        desc: 'New mobile phone hash not in the known phone set.' },
                { name: 's_ship_indicator',      label: 'Shipping Type',     desc: 'Surprise when the shipping indicator deviates from baseline.' },
                { name: 's_ship_name_match',     label: 'Ship Name Match',   desc: 'Deviation from historical cardholder ↔ shipping name match rate.' },
            ]
        },
        {
            id: 'authentication', title: 'Authentication & 3DS', icon: '🔐',
            iconBg: 'rgba(220,38,38,0.12)',
            description: 'Requestor and authentication method signals',
            vectors: [
                { name: 's_requestor_id',  label: '3DS Requestor ID', desc: 'Surprise when 3DS requestor is not in the known requestor set.' },
                { name: 's_requestor_url', label: 'Requestor URL',    desc: 'Surprise when requestor URL hash is not in the known URL set.' },
                { name: 's_auth_ind',      label: 'Auth Indicator',   desc: 'Surprise when authentication indicator type is unusual.' },
                { name: 's_auth_method',   label: 'Auth Method',      desc: 'Surprise when authentication method (password/biometric) is unusual.' },
            ]
        },
        {
            id: 'velocity', title: 'Velocity & Account Risk', icon: '⚡',
            iconBg: 'rgba(5,150,105,0.12)',
            description: 'Transaction velocity, account age and provision signals',
            vectors: [
                { name: 's_txn_vel_day',           label: 'Daily Velocity',         desc: 'Z-score of daily transaction count vs EWMA. Flags burst activity.' },
                { name: 's_txn_vel_year',           label: 'Yearly Velocity',        desc: 'Z-score of yearly transaction count vs EWMA baseline.' },
                { name: 's_provision_attempts',     label: 'Provision Attempts',     desc: 'Provisioning spike on a clean card triggers a high-weight flag.' },
                { name: 's_nb_purchase',            label: 'Purchase Count',         desc: 'Deviation of 6-month purchase count from EWMA baseline.' },
                { name: 's_ch_acc_age_regression',  label: 'Account Age Regression', desc: 'Penalty when account age indicator decreases (monotonic violation).' },
                { name: 's_ch_acc_change',          label: 'Account Change Ind.',    desc: 'EWMA deviation of account-information-change indicator.' },
                { name: 's_pw_change',              label: 'Password Change Ind.',   desc: 'EWMA deviation of password-change indicator.' },
                { name: 's_suspicious',             label: 'Suspicious Activity',    desc: 'Direct high-weight flag when merchant reports suspicious activity.' },
            ]
        },
        {
            id: 'cross_field', title: 'Cross-Field Checks', icon: '🔗',
            iconBg: 'rgba(100,116,139,0.12)',
            description: 'Consistency checks spanning multiple payload fields',
            vectors: [
                { name: 's_clock_skew',            label: 'Clock Skew',            desc: 'Device time vs purchase timestamp differ > 5 min — clock manipulation.' },
                { name: 's_platform_os_coherence', label: 'Platform / OS Coherence', desc: '"iOS" platform with "Android" OS — strong spoofing indicator.' },
                { name: 's_velocity_crosscheck',   label: 'Velocity Cross-check',  desc: 'Daily velocity disproportionate to yearly rate — burst fraud indicator.' },
                { name: 's_new_shipping_context',  label: 'New Shipping Context',  desc: 'Shipping city/country combination not seen in card history.' },
            ]
        },
    ];

    // Flat lookup: vector name → display metadata
    const VECTOR_META = {};
    WEIGHT_GROUPS.forEach(g => g.vectors.forEach(v => { VECTOR_META[v.name] = { ...v, groupId: g.id }; }));


    // ── Config state ─────────────────────────────────────────────────
    let _serverWeights  = {};   // last confirmed values from the server
    let _defaultWeights = {};   // factory defaults returned by GET endpoint
    let _dirtyWeights   = {};   // current unsaved edits
    let _configLoaded   = false;
    let _saving         = false;
    let _lastSavedAt    = null; // Date of last successful save

    // ── Config DOM refs ───────────────────────────────────────────────
    const cfgWeightGroups   = document.getElementById('cfg-weight-groups');
    const cfgWeightTotal    = document.getElementById('cfg-weight-total');
    const cfgVectorsChanged = document.getElementById('cfg-vectors-changed');
    const cfgLastSaved      = document.getElementById('cfg-last-saved');
    const cfgValBanner      = document.getElementById('cfg-validation-banner');
    const cfgValMsg         = document.getElementById('cfg-validation-msg');
    const cfgBtnSave        = document.getElementById('cfg-btn-save');
    const cfgSaveText       = document.getElementById('cfg-save-text');
    const cfgSaveLoader     = document.getElementById('cfg-save-loader');
    const cfgSearchInput    = document.getElementById('cfg-search');
    const cfgSearchCount    = document.getElementById('cfg-search-count');
    const cfgImportFile     = document.getElementById('cfg-import-file');
    const confirmOverlay    = document.getElementById('confirm-overlay');
    const confirmCancel     = document.getElementById('confirm-cancel');
    const confirmOk         = document.getElementById('confirm-ok');
    // Summary stats
    const csTotal   = document.getElementById('cs-total-vectors');
    const csAvg     = document.getElementById('cs-avg-weight');
    const csHighest = document.getElementById('cs-highest');
    const csLowest  = document.getElementById('cs-lowest');
    const csUpdated = document.getElementById('cs-last-updated');
    const csBy      = document.getElementById('cs-updated-by');

    // ── showToast ─────────────────────────────────────────────────────
    function showToast(type, message) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        const t = document.createElement('div');
        t.className = `toast toast-${type === 'warning' ? 'info' : type}`;
        t.innerHTML = `<span class="toast-icon">${icons[type] || 'ℹ'}</span><span class="toast-msg">${message}</span>`;
        container.appendChild(t);
        setTimeout(() => { t.classList.add('fade-out'); setTimeout(() => t.remove(), 280); }, 3500);
    }

    // ── setSaveLoading ────────────────────────────────────────────────
    function setSaveLoading(on) {
        if (!cfgBtnSave) return;
        cfgBtnSave.disabled = on;
        if (cfgSaveText)   cfgSaveText.style.display   = on ? 'none'         : 'inline';
        if (cfgSaveLoader) cfgSaveLoader.style.display = on ? 'inline-block' : 'none';
    }

    // ── impactBadgeHTML ───────────────────────────────────────────────
    function impactBadgeHTML(w) {
        const lvl   = w >= 0.12 ? 'critical' : w >= 0.07 ? 'high' : w >= 0.04 ? 'medium' : 'low';
        const label = lvl === 'critical' ? 'CRITICAL' : lvl === 'high' ? 'HIGH' : lvl === 'medium' ? 'MEDIUM' : 'LOW';
        return `<span class="impact-badge impact-${lvl}">${label}</span>`;
    }

    // ── weightRowHTML ─────────────────────────────────────────────────
    function weightRowHTML(vectorName, weight, defaultWeight) {
        const meta    = VECTOR_META[vectorName] || { label: vectorName, desc: '' };
        const w       = typeof weight === 'number' ? weight : 0;
        const def     = typeof defaultWeight === 'number' ? defaultWeight : 0;
        const isDirty = Math.abs(w - def) > 1e-6;
        return `
<div class="weight-row" data-vector="${vectorName}">
  <div class="weight-name-col">
    <div class="weight-feat-name">${meta.label}</div>
    <div class="weight-feat-desc">${meta.desc}</div>
  </div>
  <div class="weight-slider-col">
    <span class="weight-slider-min">0.00</span>
    <input type="range" class="weight-slider" min="0" max="1" step="0.01"
           value="${w.toFixed(2)}" aria-label="${meta.label} weight slider"
           data-vector="${vectorName}">
    <span class="weight-slider-max">1.00</span>
  </div>
  <div class="weight-input-col">
    <input type="number" class="weight-num-input" min="0" max="1" step="0.01"
           value="${w.toFixed(2)}" aria-label="${meta.label} weight value"
           data-vector="${vectorName}">
    <span class="weight-input-error" data-error="${vectorName}"></span>
  </div>
  <div>${impactBadgeHTML(w)}</div>
  <button class="weight-reset-btn" data-reset="${vectorName}"
          data-default="${def.toFixed(4)}"
          aria-label="Reset ${meta.label} to default"
          style="${isDirty ? '' : 'opacity:0.3;pointer-events:none;'}">↺</button>
</div>`;
    }

    // ── renderWeightGroups ────────────────────────────────────────────
    function renderWeightGroups() {
        if (!cfgWeightGroups) return;
        const openGroups = new Set();
        cfgWeightGroups.querySelectorAll('.weight-group.open').forEach(el => openGroups.add(el.dataset.groupId));
        if (openGroups.size === 0) WEIGHT_GROUPS.forEach(g => openGroups.add(g.id));

        cfgWeightGroups.innerHTML = WEIGHT_GROUPS.map(group => {
            const isOpen   = openGroups.has(group.id);
            const rowsHTML = group.vectors.map(v => {
                const w   = typeof _dirtyWeights[v.name] === 'number' ? _dirtyWeights[v.name] : (_defaultWeights[v.name] || 0);
                const def = _defaultWeights[v.name] || 0;
                return weightRowHTML(v.name, w, def);
            }).join('');
            return `
<div class="weight-group ${isOpen ? 'open' : ''}" data-group-id="${group.id}">
  <div class="weight-group-header" role="button" aria-expanded="${isOpen}" tabindex="0">
    <div class="weight-group-title-wrap">
      <div class="weight-group-icon" style="background:${group.iconBg}">${group.icon}</div>
      <div>
        <div class="weight-group-title">${group.title}</div>
        <div class="weight-group-subtitle">${group.description}</div>
      </div>
    </div>
    <div class="weight-group-meta">
      <span class="weight-group-count">${group.vectors.length} vectors</span>
      <span class="weight-group-chevron">▼</span>
    </div>
  </div>
  <div class="weight-group-body">${rowsHTML}</div>
</div>`;
        }).join('');

        attachGroupListeners();
        recomputeTotals();
        validateWeights();
        applySearch(cfgSearchInput ? cfgSearchInput.value : '');
    }

    // ── attachGroupListeners (delegated) ──────────────────────────────
    function attachGroupListeners() {
        if (!cfgWeightGroups) return;
        // Clone to drop any previous listener
        const fresh = cfgWeightGroups.cloneNode(true);
        cfgWeightGroups.parentNode.replaceChild(fresh, cfgWeightGroups);
        // Re-point module-level ref via a trick: expose on a window property
        // so applySearch / applyWeightChange can find the live element.
        window.__cfgGroupsLive = fresh;

        fresh.addEventListener('click', e => {
            const header   = e.target.closest('.weight-group-header');
            const resetBtn = e.target.closest('[data-reset]');
            if (header) {
                const grp = header.closest('.weight-group');
                const opening = !grp.classList.contains('open');
                grp.classList.toggle('open', opening);
                header.setAttribute('aria-expanded', opening);
                return;
            }
            if (resetBtn) {
                applyWeightChange(resetBtn.dataset.reset, parseFloat(resetBtn.dataset.default), fresh);
            }
        });
        fresh.addEventListener('input', e => {
            if (e.target.classList.contains('weight-slider'))
                applyWeightChange(e.target.dataset.vector, parseFloat(e.target.value), fresh);
        });
        fresh.addEventListener('change', e => {
            if (e.target.classList.contains('weight-num-input'))
                applyWeightChange(e.target.dataset.vector, parseFloat(e.target.value), fresh);
        });
        fresh.addEventListener('keydown', e => {
            if (e.key === 'Enter' && e.target.classList.contains('weight-num-input')) e.target.blur();
        });
    }

    // ── normalizeWeights(weights) ─────────────────────────────────────
    // Proportionally scale all values so they sum to exactly 1.0.
    // If the total is 0 (all zeros), falls back to a uniform distribution.
    function normalizeWeights(weights) {
        const names = Object.keys(weights);
        const total = names.reduce((s, k) => s + (weights[k] || 0), 0);
        if (total <= 0) {
            const even = 1 / names.length;
            const out  = {};
            names.forEach(k => { out[k] = even; });
            return out;
        }
        const out = {};
        names.forEach(k => { out[k] = (weights[k] || 0) / total; });
        return out;
    }

    // ── _syncRowDOM(name, val, def, el) ───────────────────────────────
    // Update ONE row's slider, input, badge, and reset button in the DOM.
    function _syncRowDOM(name, val, def, el) {
        const row = el.querySelector(`.weight-row[data-vector="${name}"]`);
        if (!row) return;
        const slider    = row.querySelector('.weight-slider');
        const numInput  = row.querySelector('.weight-num-input');
        const badgeCell = row.children[3];
        const resetBtn  = row.querySelector('[data-reset]');
        if (slider   && Math.abs(parseFloat(slider.value)   - val) > 5e-4) slider.value   = val.toFixed(4);
        if (numInput && Math.abs(parseFloat(numInput.value) - val) > 5e-4) numInput.value = val.toFixed(4);
        if (badgeCell) badgeCell.innerHTML = impactBadgeHTML(val);
        const isDirty = Math.abs(val - def) > 1e-6;
        if (resetBtn) {
            resetBtn.style.opacity        = isDirty ? '1'    : '0.3';
            resetBtn.style.pointerEvents  = isDirty ? 'auto' : 'none';
        }
        // Clear any per-field error state — normalization guarantees valid range
        const errEl = el.querySelector(`[data-error="${name}"]`);
        if (errEl) { errEl.textContent = ''; errEl.classList.remove('visible'); }
        if (numInput) numInput.classList.remove('invalid');
    }

    // ── applyWeightChange ─────────────────────────────────────────────
    // Sets the changed weight, then proportionally rebalances all OTHER
    // weights so the total remains exactly 1.000.
    function applyWeightChange(name, rawVal, container) {
        // Clamp the user-entered value to [0, 0.99] — cap at 0.99 so there
        // is always at least 0.01 left to distribute to the other vectors.
        const clamped = Math.min(0.99, Math.max(0, isNaN(rawVal) ? 0 : rawVal));

        // Compute the remainder that must be distributed across ALL OTHER vectors
        const remaining = 1 - clamped;
        const otherNames = Object.keys(_dirtyWeights).filter(k => k !== name);
        const otherTotal = otherNames.reduce((s, k) => s + (_dirtyWeights[k] || 0), 0);

        // Set the changed vector
        _dirtyWeights[name] = clamped;

        if (otherTotal <= 0) {
            // Edge case: all others are 0 — distribute evenly
            const even = remaining / otherNames.length;
            otherNames.forEach(k => { _dirtyWeights[k] = even; });
        } else {
            // Proportional redistribution: each other vector scales by (remaining / otherTotal)
            const scale = remaining / otherTotal;
            otherNames.forEach(k => { _dirtyWeights[k] = (_dirtyWeights[k] || 0) * scale; });
        }

        // DOM update — sync every affected row
        const el = container || window.__cfgGroupsLive || cfgWeightGroups;
        if (!el) return;

        // Sync the changed row
        _syncRowDOM(name, _dirtyWeights[name], _defaultWeights[name] || 0, el);
        // Sync all rebalanced rows
        otherNames.forEach(k => _syncRowDOM(k, _dirtyWeights[k], _defaultWeights[k] || 0, el));

        recomputeTotals();
        validateWeights();
    }

    // ── recomputeTotals ───────────────────────────────────────────────
    function recomputeTotals() {
        const total   = Object.values(_dirtyWeights).reduce((s, v) => s + v, 0);
        const changed = Object.keys(_dirtyWeights).filter(
            k => Math.abs((_dirtyWeights[k] || 0) - (_serverWeights[k] || 0)) > 1e-6
        ).length;
        
        // Update Total Weight indicator with balance status
        if (cfgWeightTotal) {
            const isBalanced = Math.abs(total - 1.0) <= 0.001;
            const statusIcon = isBalanced ? '✓ Balanced' : '⚠ Not Balanced';
            cfgWeightTotal.textContent = `${total.toFixed(3)} / 1.000 ${statusIcon}`;
            cfgWeightTotal.className = isBalanced ? 'weight-total-pill valid' : 'weight-total-pill invalid';
        }
        
        // Update Modified Weights count
        if (cfgVectorsChanged) {
            const totalVectors = Object.keys(_dirtyWeights).length;
            cfgVectorsChanged.textContent = `${changed} / ${totalVectors}`;
        }
        
        // Update Last Saved timestamp
        if (cfgLastSaved) {
            if (_lastSavedAt) {
                const now = new Date();
                const diff = Math.floor((now - _lastSavedAt) / 1000); // seconds
                if (diff < 10) {
                    cfgLastSaved.textContent = 'Just now';
                } else if (diff < 60) {
                    cfgLastSaved.textContent = `${diff}s ago`;
                } else if (diff < 3600) {
                    const mins = Math.floor(diff / 60);
                    cfgLastSaved.textContent = `${mins} min${mins !== 1 ? 's' : ''} ago`;
                } else {
                    cfgLastSaved.textContent = _lastSavedAt.toLocaleString();
                }
            } else {
                cfgLastSaved.textContent = 'Never';
            }
        }
    }

    // ── validateWeights ───────────────────────────────────────────────
    // With auto-normalization, values are always in [0,1] and sum to 1.
    // This function now only manages the Save button's enabled state.
    function validateWeights() {
        if (cfgValBanner) cfgValBanner.classList.remove('visible');
        const hasChanges = Object.keys(_dirtyWeights).some(
            k => Math.abs((_dirtyWeights[k] || 0) - (_serverWeights[k] || 0)) > 1e-6
        );
        if (cfgBtnSave) cfgBtnSave.disabled = !hasChanges;
        return true;
    }

    // ── updateSummaryStats ────────────────────────────────────────────
    function updateSummaryStats(meta) {
        if (!meta) return;
        if (csTotal)   csTotal.textContent   = meta.total_vectors   ?? '—';
        if (csAvg)     csAvg.textContent     = (meta.average_weight ?? 0).toFixed(4);
        if (csHighest) csHighest.textContent = meta.highest_vector  ?? '—';
        if (csLowest)  csLowest.textContent  = meta.lowest_vector   ?? '—';
        if (csUpdated) csUpdated.textContent = meta.last_updated ? new Date(meta.last_updated).toLocaleString() : 'Never';
        if (csBy)      csBy.textContent      = meta.last_updated_by ?? 'system';
    }

    // ── fetchWeights ──────────────────────────────────────────────────
    async function fetchWeights() {
        if (!cfgWeightGroups) return;
        if (!_configLoaded) cfgWeightGroups.innerHTML = '<div style="padding:2rem;text-align:center;color:var(--text-muted);">Loading configuration…</div>';
        try {
            const res  = await fetch('/internal/config/weights');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            _serverWeights  = data.weights  || {};
            _defaultWeights = data.defaults || {};
            if (!_configLoaded) {
                // Use server weights exactly as stored — the frontend already
                // guarantees they sum to 1.0 before saving.
                _dirtyWeights = { ..._serverWeights };
                _configLoaded = true;
                renderWeightGroups();
            } else {
                _serverWeights = { ...data.weights };
                recomputeTotals();
                validateWeights();
            }
            updateSummaryStats(data.metadata || {});
        } catch (err) {
            console.error('fetchWeights error:', err);
            if (!_configLoaded) cfgWeightGroups.innerHTML = `<div style="padding:2rem;text-align:center;color:var(--status-high);">Failed to load: ${err.message}</div>`;
            showToast('error', 'Failed to load weight configuration.');
        }
    }

    // ── fetchWeightHistory ────────────────────────────────────────────
    async function fetchWeightHistory() {
        const list = document.getElementById('cfg-history-list');
        if (!list) return;
        try {
            const res     = await fetch('/internal/config/weights/history?limit=10');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const entries = await res.json();
            if (!Array.isArray(entries) || entries.length === 0) {
                list.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;text-align:center;padding:1rem 0;">No changes recorded yet.</div>';
                return;
            }
            list.innerHTML = entries.map(e => `
<div class="history-entry">
  <div class="history-entry-header">
    <span class="history-entry-by">${e.changed_by || 'system'}</span>
    <span class="history-entry-time">${e.changed_at ? new Date(e.changed_at).toLocaleString() : '—'}</span>
  </div>
  <div class="history-entry-delta">${e.delta_summary || 'no changes'}</div>
</div>`).join('');
        } catch (err) {
            console.error('fetchWeightHistory error:', err);
            list.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;padding:0.5rem;">Could not load history.</div>';
        }
    }

    // ── saveWeights ───────────────────────────────────────────────────
    async function saveWeights() {
        if (_saving || !validateWeights()) return;
        _saving = true;
        setSaveLoading(true);
        try {
            const res  = await fetch('/internal/config/weights', {
                method:  'PUT',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ weights: _dirtyWeights, updated_by: 'analyst' })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
            _serverWeights = { ..._dirtyWeights };
            _lastSavedAt   = new Date();
            fetchWeights();
            fetchWeightHistory();
            recomputeTotals(); // Update UI immediately after successful save
            showToast('success', `Configuration saved — ${data.vectors_changed || 0} vector(s) updated.`);
        } catch (err) {
            console.error('saveWeights error:', err);
            showToast('error', `Save failed: ${err.message}`);
        } finally {
            _saving = false;
            setSaveLoading(false);
            validateWeights();
        }
    }

    // ── resetWeights + confirm dialog ─────────────────────────────────
    function showConfirmDialog()  { if (confirmOverlay) confirmOverlay.classList.add('visible'); }
    function hideConfirmDialog()  { if (confirmOverlay) confirmOverlay.classList.remove('visible'); }

    if (confirmCancel)  confirmCancel.addEventListener('click', hideConfirmDialog);
    if (confirmOverlay) confirmOverlay.addEventListener('click', e => { if (e.target === confirmOverlay) hideConfirmDialog(); });

    if (confirmOk) confirmOk.addEventListener('click', async () => {
        hideConfirmDialog();
        try {
            const res = await fetch('/internal/config/weights/reset', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ confirm: true, updated_by: 'analyst' })
            });
            if (!res.ok) { const d = await res.json(); throw new Error(d.detail || `HTTP ${res.status}`); }
            _configLoaded = false;
            _dirtyWeights = {};
            await fetchWeights();
            fetchWeightHistory();
            showToast('success', 'Weights reset to factory defaults.');
        } catch (err) {
            console.error('resetWeights error:', err);
            showToast('error', `Reset failed: ${err.message}`);
        }
    });

    function resetWeights() { showConfirmDialog(); }

    // ── exportWeights ─────────────────────────────────────────────────
    function exportWeights() {
        const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), source: 'VirtueByte 3DS Fraud Analytics', weights: { ..._dirtyWeights } }, null, 2)], { type: 'application/json' });
        const url  = URL.createObjectURL(blob);
        const a    = Object.assign(document.createElement('a'), { href: url, download: `weights-${new Date().toISOString().slice(0,10)}.json` });
        a.click();
        URL.revokeObjectURL(url);
        showToast('info', 'Configuration exported as JSON.');
    }

    // ── importWeights ─────────────────────────────────────────────────
    function importWeights() {
        if (cfgImportFile) { cfgImportFile.value = ''; cfgImportFile.click(); }
    }

    if (cfgImportFile) {
        cfgImportFile.addEventListener('change', e => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = ev => {
                try {
                    const parsed = JSON.parse(ev.target.result);
                    const raw    = parsed.weights || parsed;
                    if (typeof raw !== 'object' || Array.isArray(raw)) throw new Error('JSON must be an object mapping vector names to weights.');
                    const errors = []; const imported = {}; const known = new Set(Object.keys(_defaultWeights));
                    for (const [k, v] of Object.entries(raw)) {
                        if (!known.has(k))         { errors.push(`Unknown vector: "${k}"`); continue; }
                        if (typeof v !== 'number' || isNaN(v)) { errors.push(`"${k}" must be a number`); continue; }
                        if (v < 0)                 { errors.push(`"${k}" cannot be negative`); continue; }
                        imported[k] = v;  // accept any non-negative — normalization handles the rest
                    }
                    if (errors.length > 0) { showToast('error', `Import error: ${errors[0]}${errors.length > 1 ? ` (+${errors.length-1} more)` : ''}`); return; }
                    const count      = Object.keys(imported).length;
                    const normalized = normalizeWeights({ ..._dirtyWeights, ...imported });
                    Object.assign(_dirtyWeights, normalized);
                    renderWeightGroups();
                    const sumNote = Math.abs(Object.values(imported).reduce((s,v)=>s+v,0) - 1) > 1e-3 ? ' (auto-normalized to 1.000)' : '';
                    showToast('success', `Imported ${count} weight${count !== 1 ? 's' : ''}${sumNote}. Review then click Save Changes.`);
                } catch (err) { showToast('error', `Import failed: ${err.message}`); }
            };
            reader.readAsText(file);
        });
    }

    // ── applySearch ───────────────────────────────────────────────────
    function applySearch(query) {
        const el = window.__cfgGroupsLive || cfgWeightGroups;
        if (!el) return;
        const q = (query || '').toLowerCase().trim();
        let totalVisible = 0;
        el.querySelectorAll('.weight-group').forEach(group => {
            let groupVisible = 0;
            group.querySelectorAll('.weight-row').forEach(row => {
                const meta = VECTOR_META[row.dataset.vector] || {};
                const text = `${row.dataset.vector} ${(meta.label||'').toLowerCase()} ${(meta.desc||'').toLowerCase()}`;
                const show = !q || text.includes(q);
                row.classList.toggle('hidden', !show);
                if (show) { groupVisible++; totalVisible++; }
            });
            group.style.display = (groupVisible === 0 && q) ? 'none' : '';
            if (q && groupVisible > 0) group.classList.add('open');
        });
        if (cfgSearchCount) cfgSearchCount.textContent = q ? `${totalVisible} result${totalVisible !== 1 ? 's' : ''}` : '';
    }

    if (cfgSearchInput) {
        let srchDebounce;
        cfgSearchInput.addEventListener('input', () => {
            clearTimeout(srchDebounce);
            srchDebounce = setTimeout(() => applySearch(cfgSearchInput.value), 160);
        });
    }


    // ── Wire config action buttons ────────────────────────────────────
    const _cfgBtnSaveWire   = document.getElementById('cfg-btn-save');
    const _cfgBtnResetWire  = document.getElementById('cfg-btn-reset');
    const _cfgBtnExportWire = document.getElementById('cfg-btn-export');
    const _cfgBtnImportWire = document.getElementById('cfg-btn-import');

    if (_cfgBtnSaveWire)   _cfgBtnSaveWire.addEventListener('click',   saveWeights);
    if (_cfgBtnResetWire)  _cfgBtnResetWire.addEventListener('click',  resetWeights);
    if (_cfgBtnExportWire) _cfgBtnExportWire.addEventListener('click', exportWeights);
    if (_cfgBtnImportWire) _cfgBtnImportWire.addEventListener('click', importWeights);

    // ── Periodic update for "Last Saved" timestamp ────────────────────
    // Update every 10 seconds to show relative time (e.g., "2 mins ago")
    setInterval(() => {
        if (_lastSavedAt && cfgLastSaved) {
            const now = new Date();
            const diff = Math.floor((now - _lastSavedAt) / 1000); // seconds
            if (diff < 10) {
                cfgLastSaved.textContent = 'Just now';
            } else if (diff < 60) {
                cfgLastSaved.textContent = `${diff}s ago`;
            } else if (diff < 3600) {
                const mins = Math.floor(diff / 60);
                cfgLastSaved.textContent = `${mins} min${mins !== 1 ? 's' : ''} ago`;
            } else {
                cfgLastSaved.textContent = _lastSavedAt.toLocaleString();
            }
        }
    }, 10000);

    // ── Initialisation — load config tab on first open ────────────────
    // fetchWeights() and fetchWeightHistory() are called by the tab
    // button listener (already wired above in the switchView block).
    // No eager fetch needed: the panel is hidden until the user opens it.

}); // end DOMContentLoaded
