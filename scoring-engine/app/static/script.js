document.addEventListener('DOMContentLoaded', () => {
    
    const editor = document.getElementById('payload-editor');
    const scoreBtn = document.getElementById('score-btn');
    const loader = document.getElementById('score-loader');
    const btnText = document.querySelector('.btn-text');
    
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

    // Sample Payloads
    const normalPayload = {
        "card_id_hash": "demo_card_presentation",
        "acctType": "01",
        "mcc": "5411",
        "merchantCountryCode": "356",
        "purchaseAmount": 1500.0,
        "purchaseCurrency": "356",
        "purchaseDate": "2026-06-27T14:30:00+05:30",
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
        "ApplicationPackageName": "com.merchant.pay.app1",
        "SDKAppID": "sdk_app_test",
        "SDKVersion": "5.3.0",
        "SDKRefNumber": "SDK_REF_CONSTANT_HASH_V1",
        "dateTime": "2026-06-27T14:30:03+05:30"
    };

    const anomalyPayload = {
        ...normalPayload,
        "purchaseAmount": 95000.0,
        "txnActivityDay": 10,
        "Platform": "iOS",
        "DeviceModel": "iPhone 15 Pro",
        "OSName": "iOS",
        "OSVersion": "17.5",
        "ScreenResolution": "1179x2556",
        "IPAddress": "203.0.113.42",
        "ApplicationPackageName": "com.unknown.app.xyz123"
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

        // Update Top Metrics
        valTier.textContent = report.deviation_tier;
        valDeviation.textContent = report.total_deviation.toFixed(2);
        valIfscore.textContent = report.if_score.toFixed(4);
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
});
