/**
 * server.js — Node.js / Express API Gateway
 *
 * Responsibilities (§3.1):
 *   - JSON schema validation (Joi) for all 50 3DS fields
 *   - SHA-256(acctNumber) → card_id_hash (PAN never forwarded)
 *   - Rate limiting (express-rate-limit)
 *   - API key authentication
 *   - Proxy to FastAPI scoring engine
 *
 * What this does NOT do: business logic, scoring, Redis/Postgres I/O.
 */

const express = require("express");
const Joi = require("joi");
const axios = require("axios");
const crypto = require("crypto");
const rateLimit = require("express-rate-limit");
const helmet = require("helmet");
const morgan = require("morgan");
const { v4: uuidv4 } = require("uuid");

require("dotenv").config();

const app = express();
const PORT = process.env.PORT || 3000;
const SCORING_ENGINE_URL =
  process.env.SCORING_ENGINE_URL || "http://localhost:8000";
const API_KEY = process.env.API_KEY || "dev-api-key-change-in-production";

// ---------------------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------------------

app.use(helmet());
app.use(express.json({ limit: "1mb" }));
app.use(morgan("combined"));

// Rate limiting: 100 requests per minute per IP
const limiter = rateLimit({
  windowMs: 60 * 1000,
  max: 100,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    error: "Too many requests. Please try again later.",
    retry_after_ms: 60000,
  },
});
app.use("/v1/", limiter);

// ---------------------------------------------------------------------------
// API Key Authentication
// ---------------------------------------------------------------------------

function apiKeyAuth(req, res, next) {
  const key = req.headers["x-api-key"] || req.query.api_key;
  if (!key || key !== API_KEY) {
    return res.status(401).json({
      error: "Unauthorized",
      message: "Invalid or missing API key. Provide X-API-Key header.",
    });
  }
  next();
}

// ---------------------------------------------------------------------------
// Joi Validation Schema — 50 3DS Fields
// ---------------------------------------------------------------------------

const areqSchema = Joi.object({
  // Transaction Details
  acctNumber: Joi.string().required().messages({
    "any.required": "acctNumber (card number) is required",
  }),
  acctType: Joi.string().valid("01", "02").default("01"),
  mcc: Joi.string().max(10).default(""),
  merchantCountryCode: Joi.string().max(5).default(""),
  purchaseAmount: Joi.number().min(0).required(),
  purchaseCurrency: Joi.string().max(5).default(""),
  purchaseDate: Joi.string().default(""),
  cardSecurityCodeStatus: Joi.string()
    .valid("01", "02", "03", "04")
    .default("01"),

  // 3DS Requestor Details
  threeDSRequestorID: Joi.string().default(""),
  threeDSRequestorName: Joi.string().default(""),
  threeDSRequestorURL: Joi.string().default(""),
  threeDSRequestorAuthenticationInd: Joi.string().default("01"),
  threeDSReqAuthMethod: Joi.string().default(""),

  // acctInfo
  chAccAgeInd: Joi.string().valid("01", "02", "03", "04", "05").default("05"),
  chAccChangeInd: Joi.string()
    .valid("01", "02", "03", "04", "05")
    .default("01"),
  chAccPwChangeInd: Joi.string()
    .valid("01", "02", "03", "04", "05")
    .default("01"),
  txnActivityDay: Joi.number().integer().min(0).default(0),
  txnActivityYear: Joi.number().integer().min(0).default(0),
  provisionAttemptsDay: Joi.number().integer().min(0).default(0),
  nbPurchaseAccount: Joi.number().integer().min(0).default(0),
  suspiciousAccActivity: Joi.string().valid("01", "02").default("02"),
  shipNameIndicator: Joi.string().valid("01", "02").default("01"),

  // Merchant Details
  acquirerMerchantID: Joi.string().default(""),
  acquirerBIN: Joi.string().default(""),
  shipIndicator: Joi.string().default("01"),
  billAddrLine1: Joi.string().default(""),
  billAddrCity: Joi.string().default(""),
  billAddrCountry: Joi.string().default(""),
  billAddrPostCode: Joi.string().default(""),
  email: Joi.string().email({ tlds: false }).allow("").default(""),
  mobilePhone: Joi.string().default(""),
  shipAddrCity: Joi.string().default(""),
  shipAddrCountry: Joi.string().default(""),

  // Device Details (SDK channel)
  sdkInterface: Joi.string().default(""),
  sdkUiType: Joi.string().default(""),
  Platform: Joi.string().default(""),
  DeviceModel: Joi.string().default(""),
  OSName: Joi.string().default(""),
  OSVersion: Joi.string().default(""),
  Locale: Joi.string().default(""),
  TimeZone: Joi.string().default(""),
  ScreenResolution: Joi.string().default(""),
  DeviceName: Joi.string().default(""),
  IPAddress: Joi.string().default(""),
  Latitude: Joi.number().min(-90).max(90).default(0),
  Longitude: Joi.number().min(-180).max(180).default(0),
  ApplicationPackageName: Joi.string().default(""),
  SDKAppID: Joi.string().default(""),
  SDKVersion: Joi.string().default(""),
  SDKRefNumber: Joi.string().default(""),
  dateTime: Joi.string().default(""),
}).options({ stripUnknown: true });

// ---------------------------------------------------------------------------
// SHA-256 Helper
// ---------------------------------------------------------------------------

function sha256(input) {
  return crypto.createHash("sha256").update(input).digest("hex");
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

// Health check
app.get("/health", (req, res) => {
  res.json({
    status: "healthy",
    service: "3DS Anomaly Detection — API Gateway",
    version: "1.0.0",
    scoring_engine: SCORING_ENGINE_URL,
  });
});

// Root
app.get("/", (req, res) => {
  res.json({
    service: "3DS Anomaly Detection — API Gateway",
    version: "1.0.0",
    endpoint: "POST /v1/score",
    docs: "See API documentation",
  });
});

// Main scoring endpoint
app.post("/v1/score", apiKeyAuth, async (req, res) => {
  try {
    // 1. Validate schema
    const { error, value } = areqSchema.validate(req.body);
    if (error) {
      return res.status(400).json({
        error: "Validation Error",
        details: error.details.map((d) => ({
          field: d.path.join("."),
          message: d.message,
        })),
      });
    }

    // 2. Hash PAN — never forward raw acctNumber
    const card_id_hash = sha256(value.acctNumber);

    // 3. Build enriched payload (PAN removed)
    const enriched = {
      ...value,
      card_id_hash: card_id_hash,
    };
    delete enriched.acctNumber;

    // 4. Proxy to FastAPI scoring engine
    const response = await axios.post(
      `${SCORING_ENGINE_URL}/internal/score`,
      enriched,
      {
        headers: { "Content-Type": "application/json" },
        timeout: 10000, // 10s timeout
      }
    );

    // 5. Return scoring result
    res.json(response.data);
  } catch (err) {
    if (err.response) {
      // Scoring engine returned an error
      return res.status(err.response.status).json({
        error: "Scoring Engine Error",
        message: err.response.data?.detail || err.message,
      });
    }
    if (err.code === "ECONNREFUSED") {
      return res.status(503).json({
        error: "Service Unavailable",
        message: "Scoring engine is not reachable. Please try again later.",
      });
    }
    console.error("Unexpected error:", err.message);
    res.status(500).json({
      error: "Internal Server Error",
      message: "An unexpected error occurred.",
    });
  }
});

// ---------------------------------------------------------------------------
// Start Server
// ---------------------------------------------------------------------------

app.listen(PORT, () => {
  console.log(`
╔══════════════════════════════════════════════════════════╗
║  3DS Anomaly Detection — API Gateway                     ║
║  Running on port ${PORT}                                     ║
║  Scoring engine: ${SCORING_ENGINE_URL.padEnd(38)}║
╚══════════════════════════════════════════════════════════╝
  `);
});

module.exports = app;
